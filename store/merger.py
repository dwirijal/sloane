"""Merge layer: raw_entities -> canonical_entities + links.

Three-phase merge (per agreed key: "MAL ID + jikan + OMDB + ... + LLM + normalized title"):
  1. ID-first: raw carries a registry ID (mal/anilist/omdb/tvdb) -> match external_ids.
  2. Title exact: cleaned+normalized title + kind match. Catches "One Piece" == "One Piece (Sub Indo)".
  3. LLM fuzzy: query candidate canonicals of same kind, ask LLM if same entity.
     Catches "86 Eighty-Six Part 1" vs "86 Episode 1" — residual where normalization can't decide.

No pgvector embeddings (YAGNI: LLM direct on title pairs is simpler + matches spec
"dibantu dengan LLM"). Embeddings column stays NULL; add when LLM cost/calls dominate.

Emits: new canonical row OR links raw to existing. Always inserts a link.
raw_id -> canonical_id is 1:1 (one raw backs one canonical).
"""
from __future__ import annotations
import re

import httpx
import psycopg
from psycopg.types.json import Json

from shared.config import pg_dsn, ROUTER_BASE_URL, ROUTER_API_KEY, MODEL_WORKER

_NORM = re.compile(r"[^a-z0-9]+")

# Noise suffixes scraped sites append to titles. Strip before normalize so
# "One Piece Batch Subtitle Indonesia" == "One Piece". Order matters: longer first.
_NOISE = [
    r"bd\s*batch\s*subtitle\s*indonesia",
    r"batch\s*subtitle\s*indonesia",
    r"batch\s*sub\s*indo",
    r"subtitle\s*indonesia",
    r"sub\s*indo",
    r"\bbd\s*batch\b",
    r"\bbatch\b",
    r"\(sub\s*indo\)",
    r"\bsub\s*indo\b",
    r"\(bd\)",
    r"\bbd\b",
    r"\bcomplete\b",
    r"\(.*?batch.*?\)",
]
_NOISE_RE = re.compile("|".join(_NOISE), re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation/whitespace. 'One Piece' -> 'onepiece'.

    Stores the FULL normalized title (season preserved). Used for exact match.
    """
    return _NORM.sub("", title.lower()).strip()


def clean_title(title: str) -> str:
    """Strip site noise (batch/sub-indo/BD) then normalize.

    'One Piece Batch Subtitle Indonesia' -> 'onepiece'.
    Season markers (S2, Season 2, Part 1) are NOT noise — they distinguish real entities.
    """
    stripped = _NOISE_RE.sub(" ", title)
    return _NORM.sub("", stripped.lower()).strip()


def _llm_same_entity(title_a: str, title_b: str, kind: str) -> bool:
    """Ask 9router LLM: are these two titles the same real-world entity?

    Conservative: returns False on any error/ambiguity (creates new canonical
    rather than wrongly merging). Tracing the 'no' beats a false positive merge
    that corrupts the canonical.
    """
    if not ROUTER_API_KEY:
        return False
    # Bare prompt: the "different naming/spelling" hint + quoted 'yes' made Gemini
    # flash over-think and emit nothing within the token budget (empty answer → False).
    # Keep it blunt. 256 leaves room for thinking tokens before the one-word answer.
    prompt = (
        f"Are these two {kind} titles the same real-world work "
        f"(same season, same entry; alternate titles/translations count as same)? "
        f"Answer ONLY yes or no.\n"
        f"A: {title_a}\nB: {title_b}\nAnswer:"
    )
    try:
        # stream:False → router returns single JSON, not SSE chunks.
        # max_tokens>=256: Gemini flash emits thinking tokens before answering;
        # 64 cut it off mid-think → empty answer.
        r = httpx.post(
            f"{ROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {ROUTER_API_KEY}"},
            json={"model": MODEL_WORKER, "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 256, "temperature": 0, "stream": False},
            timeout=20,
        )
        if r.status_code != 200:
            return False
        ans = r.json()["choices"][0]["message"]["content"].strip().lower()
        return ans.startswith("y")
    except Exception:
        return False


def _find_llm_candidate(cur, title: str, kind: str, norm: str) -> int | None:
    """LLM fuzzy: scan same-kind canonicals, ask LLM per pair. Returns canonical_id or None.

    ponytail: O(n) scan over same-kind canonicals. Fine at smoke scale (dozens).
    Add a pgvector ANN index when canonicals exceed ~5k — LLM-per-pair won't scale.
    """
    cur.execute(
        "SELECT id, title FROM canonical_entities WHERE kind=%s AND normalized_title<>%s "
        "ORDER BY id LIMIT 200",
        (kind, norm),
    )
    for cid, cand_title in cur.fetchall():
        if _llm_same_entity(title, cand_title, kind):
            return cid
    return None


def merge_raw_to_canonical(raw_id: int, title: str, kind: str,
                           payload: dict, registry_ids: dict | None = None,
                           dsn: str | None = None) -> dict:
    """Resolve + write canonical for one raw row.

    Returns {canonical_id, merged, method} where method in
    {id, title_exact, llm_fuzzy, created}.
    """
    dsn = dsn or pg_dsn()
    norm = normalize_title(title)
    if not norm:
        raise ValueError(f"empty normalized title for raw_id={raw_id}")
    reg = registry_ids or {}
    method = "created"

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        canonical_id = None

        # 1. ID-first
        for registry, ext_id in reg.items():
            row = cur.execute(
                "SELECT canonical_id FROM external_ids WHERE registry=%s AND external_id=%s",
                (registry, str(ext_id)),
            ).fetchone()
            if row:
                canonical_id, method = row[0], "id"
                break

        # 2. title exact (cleaned)
        if canonical_id is None:
            cleaned = clean_title(title)
            row = cur.execute(
                "SELECT id FROM canonical_entities WHERE kind=%s AND normalized_title=%s",
                (kind, cleaned),
            ).fetchone()
            if row:
                canonical_id, method = row[0], "title_exact"
                # keep cleaned title as canonical's normalized key
                cur.execute(
                    "UPDATE canonical_entities SET normalized_title=%s WHERE id=%s",
                    (cleaned, canonical_id),
                )

        # 3. LLM fuzzy (residual)
        if canonical_id is None:
            cid = _find_llm_candidate(cur, title, kind, norm)
            if cid:
                canonical_id, method = cid, "llm_fuzzy"

        merged = False
        if canonical_id is None:
            canonical_id = cur.execute(
                "INSERT INTO canonical_entities (kind, title, normalized_title, best_payload) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (kind, title, clean_title(title), Json(payload)),
            ).fetchone()[0]
            merged = True
        else:
            cur.execute(
                "UPDATE canonical_entities SET best_payload = best_payload || %s::jsonb, updated_at=now() WHERE id=%s",
                (Json(payload), canonical_id),
            )

        for registry, ext_id in reg.items():
            cur.execute(
                "INSERT INTO external_ids (canonical_id, registry, external_id) "
                "VALUES (%s,%s,%s) ON CONFLICT (registry, external_id) DO NOTHING",
                (canonical_id, registry, str(ext_id)),
            )

        cur.execute(
            "INSERT INTO entity_source_links (canonical_id, raw_id, is_primary) "
            "VALUES (%s,%s, true) "
            "ON CONFLICT (canonical_id, raw_id) DO UPDATE SET is_primary=true",
            (canonical_id, raw_id),
        )
        cur.execute(
            "UPDATE entity_source_links SET is_primary=false "
            "WHERE canonical_id=%s AND raw_id<>%s",
            (canonical_id, raw_id),
        )
        conn.commit()
    return {"canonical_id": canonical_id, "merged": merged, "method": method}


if __name__ == "__main__":
    # self-check: noise strip + normalize behave as claimed
    assert clean_title("One Piece Batch Subtitle Indonesia") == "onepiece"
    assert clean_title("One Piece (Sub Indo)") == "onepiece"
    assert clean_title("86 Eighty-Six Part 1") == "86eightysixpart1"
    assert normalize_title("One Piece Batch Subtitle Indonesia") == "onepiecebatchsubtitleindonesia"
    assert _NORM.sub("", "a.b c") == "abc"
    print("merger self-check OK")
