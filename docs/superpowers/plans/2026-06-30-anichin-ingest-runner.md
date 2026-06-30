# anichin Ingest Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add anichin.moe (donghua streaming site) as a second sloane source: parsers + ingest runner (2h delta, daily discover, resumable backfill) storing series + episodes with Dailymotion `stream_url`.

**Architecture:** Mirror `sources/samehadaku/` + `ingest/samehadaku.py` structure. anichin differs from samehadaku in two load-bearing ways: (1) no RSS feed — delta is ep-number diff against the `/anime/?order=update` list; (2) streaming-only — episodes store `stream_url` (iframe src), not download-host links. Same 3-layer model (raw → canonical → links), same `write_entities`/`merge_raw_to_canonical`/`enrich_canonical`, same `ingest_state` table (migration 004, unchanged — just new `source='anichin'` rows).

**Tech Stack:** Python 3.12 stdlib + httpx (sync client + AsyncClient), beautifulsoup4 + lxml parser, psycopg3. No new dependencies (all already installed for samehadaku). Tests via stdlib harness (no pytest) using `tests/_monkeypatch.py` shim.

## Global Constraints

- Python interpreter: `/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python`
- `PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ`
- DB DSN via `from shared.config import pg_dsn` (sloane does NOT hardcode DSNs). Live DB is homeserver pgbouncer via `sloane-db-tunnel.service`; local Docker `:5432` is NOT sloane's DB.
- `CanonicalEntity` contract: `from shared.schema_contract import CanonicalEntity, KIND_ANIME`. `write_entities(dsn, entities)` validates + UPSERTs raw rows (replaces `payload` wholesale — load-mutate-upsert, NOT a SQL per-field patch). `merge_raw_to_canonical(raw_id, title, kind, payload, registry_ids=None, dsn=None)` links raw→canonical. `enrich_canonical(canonical_id, title, dsn=None)` resolves MAL id.
- Source name constant: `SOURCE = "anichin"` (matches `raw_entities.source`, `ingest_state.source`, systemd unit names).
- anichin has NO download-host links and NO RSS feed — do NOT add `_downloads.py` or `_feed.py` modules. Do NOT invent download/batch logic.
- Tests run via the repo's stdlib harness (see CLAUDE.md), NOT `pytest`. Test functions are module-level `def test_*()`; use `tests/_monkeypatch.py` `MonkeyPatch` for mocking; fixtures live in `tests/fixtures/`.
- Fixtures (already saved to repo by this plan's author, do not re-fetch): `tests/fixtures/anichin_update.html`, `anichin_detail.html`, `anichin_episode.html`, `anichin_az.html`.
- Ultra-terse code style, stdlib-first, YAGNI. `ponytail:` comment for deliberate simplifications.
- Browser UA `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36` suffices (no anti-bot observed 2026-06-30).

---

## File Structure

```
sources/anichin/
  __init__.py     — package docstring only (mirrors sources/samehadaku/__init__.py)
  _http.py        — BASE_URL, HEADERS, client() [mirrors samehadaku/_http.py minus dead selectors]
  _lists.py       — parse_update_list(html), walk_directory(cx)
  _detail.py      — parse_detail(html, base) -> dict (metadata + episodes:[{n,url}])
  _episodes.py    — parse_episode(html) -> {n, stream_url}
ingest/anichin.py — ingest_updates, discover_new_series, backfill_all + helpers
ingest/__main__.py — MODIFY: add "anichin" to source choices + dispatch
tests/
  fixtures/anichin_*.html — EXIST (saved by plan author)
  test_anichin_lists.py, test_anichin_detail.py, test_anichin_episodes.py, test_anichin_ingest.py
deploy/
  sloane-anichin-ingest.{service,timer}     — 2h delta
  sloane-anichin-discover.{service,timer}   — daily 05:00
```

Each source module has one responsibility; the ingest runner composes them. No new tables, no schema changes.

---

### Task 1: `sources/anichin/_http.py` + `sources/anichin/__init__.py`

**Files:**
- Create: `sources/anichin/__init__.py`
- Create: `sources/anichin/_http.py`
- Test: none (trivial — covered transitively by Task 2+)

**Interfaces:**
- Produces: `sources.anichin._http.BASE_URL` (str), `HEADERS` (dict), `client()` (returns `httpx.Client`).

- [ ] **Step 1: Create `sources/anichin/__init__.py`**

```python
"""anichin source package: parser modules (_http, _lists, _detail, _episodes).

Live ingest runner lives at sloane.ingest.anichin (latest-update delta + daily
discovery + backfill). These modules are the parsing layer it composes.
"""
```

- [ ] **Step 2: Create `sources/anichin/_http.py`**

```python
"""Shared HTTP client + selectors for the anichin source.

anichin.moe is plain WordPress — no Cloudflare challenge, no JS gating, but the
RSS /feed/ is disabled (returns 500). httpx with a browser UA fetches every page
directly (verified 2026-06-30).
"""
from __future__ import annotations

import httpx

BASE_URL = "https://anichin.moe"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Sidebar .subSchh appears on every page (6 latest series) and would pollute
# list/directory parsing — strip it before scanning for series anchors.
SEL_SIDEBAR = ".subSchh"


def client() -> httpx.Client:
    """Fresh httpx client. Caller owns lifecycle (with-statement)."""
    return httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
```

- [ ] **Step 3: Verify import works**

Run: `.venv-adk/bin/python -c "from sloane.sources.anichin import _http; print(_http.BASE_URL, _http.client().headers.get('user-agent')[:20])"`
Expected: prints `https://anichin.moe` + UA prefix, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add sources/anichin/__init__.py sources/anichin/_http.py
git commit -m "feat(sloane/anichin): add _http client + package init"
```

---

### Task 2: `sources/anichin/_lists.py` — update list + A-Z directory walk

**Files:**
- Create: `sources/anichin/_lists.py`
- Test: `tests/test_anichin_lists.py`

**Interfaces:**
- Consumes: `sources.anichin._http.BASE_URL`, `client()`.
- Produces: `parse_update_list(html: str) -> list[dict]` returning `[{slug, title}]`; `walk_directory(cx) -> list[dict]` returning `[{slug, title}]` (cx is an httpx.Client-like with `.get(url).text`; caller owns lifecycle).

- [ ] **Step 1: Write the failing test `tests/test_anichin_lists.py`**

```python
"""_lists parser tests — update-list body + A-Z directory walk.

anichin's series anchors are ROOT-slug (/slug/), not /anime/{slug}/ — and a
sidebar .subSchh (6 latest series) appears on every page and must be stripped.
"""
from pathlib import Path
from unittest.mock import MagicMock

from sloane.sources.anichin import _lists

FIX = Path(__file__).parent / "fixtures"


def test_parse_update_list_returns_series():
    items = _lists.parse_update_list((FIX / "anichin_update.html").read_text())
    assert items, "update list parsed no series"
    first = items[0]
    assert "slug" in first and "title" in first
    # root-slug anchors only: no /anime/ index, no episode URLs
    assert "/" not in first["slug"]
    assert all(not i["slug"].startswith("anime") for i in items)


def test_parse_update_list_strips_sidebar():
    # sidebar .subSchh would add 6 duplicate latest-series; ensure dedup holds.
    items = _lists.parse_update_list((FIX / "anichin_update.html").read_text())
    slugs = [i["slug"] for i in items]
    assert len(slugs) == len(set(slugs)), "duplicate slugs — sidebar not stripped"


def test_walk_directory_paginates_until_empty():
    # show "0-9": page1 empty -> stop. show "A": page1 has 2, page2 empty -> stop.
    # shows B..Z: page1 empty -> stop. Total series = 2. Feed empties for all
    # remaining shows so the test is deterministic across the 27-show walk.
    page1 = MagicMock(); page1.text = '<a title="Ape" href="/ape/"></a><a title="Ark" href="/ark/"></a>'
    empty = MagicMock(); empty.text = "<html></html>"
    cx = MagicMock()
    cx.get.side_effect = [empty, page1, empty] + [empty] * 25
    items = _lists.walk_directory(cx)
    assert len(items) == 2
    assert {i["slug"] for i in items} == {"ape", "ark"}
```

- [ ] **Step 2: Run test to verify it fails**

Run (repo stdlib harness — see CLAUDE.md; quick form):
```bash
.venv-adk/bin/python -c "
import importlib, inspect, sys
for m in list(sys.modules):
    if 'anichin' in m: del sys.modules[m]
mod = importlib.import_module('sloane.tests.test_anichin_lists')
f = p = 0
for n, fn in inspect.getmembers(mod, inspect.isfunction):
    if not n.startswith('test_'): continue
    try: fn(); p += 1
    except Exception as e: f += 1; print(f'FAIL {n}: {e}')
print(f'{p} passed, {f} failed')
"
```
Expected: FAIL — `ModuleNotFoundError: No module named 'sloane.sources.anichin._lists'` (or similar).

- [ ] **Step 3: Write minimal implementation `sources/anichin/_lists.py`**

```python
"""Parse anichin list endpoints into series discovery rows.

anichin series anchors are ROOT-slug (`/<slug>/`) with a `title` attr — NOT
`/anime/<slug>/` (those are the sidebar .subSchh, which appears on every page).
walk_directory paginates /az-lists/?show=<LETTER> front-to-back for the full
series set (backfill + discover seed). parse_update_list reads the latest-updated
list body (used by the 2h delta job).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import _http

# Root-slug anchor: href is exactly "/<slug>/" with a non-empty title attr.
# Excludes /anime/, /az-lists/, /genres/, episode URLs, and bare "/".
_SLUG_RE = re.compile(r"^/([a-z0-9][a-z0-9-]+)/?$")
# Paths that look like slugs but are site sections, not series.
_SECTIONS = {"anime", "az-lists", "genres", "page"}

# /az-lists/?show= walks 0-9 then A..Z.
_SHOWS = ["0-9"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def _strip_sidebar(soup: BeautifulSoup) -> None:
    """Remove .subSchh (latest-series sidebar) so it doesn't pollute parsing."""
    for sb in soup.select(_http.SEL_SIDEBAR):
        sb.decompose()


def _series_anchors(soup: BeautifulSoup) -> list[dict]:
    """Collect root-slug anchors with title attrs -> [{slug, title}]. Dedup."""
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", title=True):
        href = a.get("href", "")
        m = _SLUG_RE.match(urlparse(href).path)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen or slug in _SECTIONS:
            continue
        title = a.get("title", "").strip()
        seen.add(slug)
        out.append({"slug": slug, "title": title or slug})
    return out


def parse_update_list(html: str) -> list[dict]:
    """/anime/?order=update body -> [{slug, title}]. Strips sidebar first."""
    soup = BeautifulSoup(html, "lxml")
    _strip_sidebar(soup)
    return _series_anchors(soup)


def walk_directory(cx) -> list[dict]:
    """Walk /az-lists/?show=<LETTER> pagination front-to-back, return ALL series.

    For each show (0-9, A..Z), paginate /az-lists/page/N/?show=<LETTER> (N=1..)
    until a page returns zero series. ~700 series total. Sync (used by discover
    + backfill seeding). Caller owns cx lifecycle.
    """
    all_series: list[dict] = []
    seen: set[str] = set()
    for show in _SHOWS:
        page = 0
        while True:
            page += 1
            url = f"{_http.BASE_URL}/az-lists/page/{page}/?show={show}"
            html = cx.get(url).text
            soup = BeautifulSoup(html, "lxml")
            _strip_sidebar(soup)
            anchors = _series_anchors(soup)
            if not anchors:
                break  # letter exhausted
            for a in anchors:
                if a["slug"] not in seen:
                    seen.add(a["slug"])
                    all_series.append(a)
    return all_series
```

- [ ] **Step 4: Run test to verify it passes**

Run the same harness command as Step 2.
Expected: `3 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add sources/anichin/_lists.py tests/test_anichin_lists.py
git commit -m "feat(sloane/anichin): add _lists parser (update list + A-Z walk)"
```

---

### Task 3: `sources/anichin/_detail.py` — series detail + episode list

**Files:**
- Create: `sources/anichin/_detail.py`
- Test: `tests/test_anichin_detail.py`

**Interfaces:**
- Consumes: `sources.anichin._http.BASE_URL`.
- Produces: `parse_detail(html: str, base: str = _http.BASE_URL) -> dict` with keys `slug, title, cover_url, synopsis, infox (dict), episodes (list[{n, url}])`. `infox` keys: `type, status, studio, season, released, duration, country, genres (list[str])`. Episodes sorted ascending by `n`.

- [ ] **Step 1: Write the failing test `tests/test_anichin_detail.py`**

```python
"""_detail parser tests — series metadata + episode anchor list."""
from pathlib import Path

from sloane.sources.anichin import _detail

FIX = Path(__file__).parent / "fixtures"


def test_parse_detail_metadata():
    d = _detail.parse_detail((FIX / "anichin_detail.html").read_text())
    assert d["title"] == "Martial Master"
    assert d["cover_url"] and d["cover_url"].startswith("http")
    assert d["synopsis"] and len(d["synopsis"]) > 20
    # infox subset (labels verified live: Tipe/Status/Studio/Season/etc, no Score)
    assert d["infox"]["type"] == "Donghua"
    assert d["infox"]["status"] == "Ongoing"
    assert "genres" in d["infox"] and isinstance(d["infox"]["genres"], list)
    assert "Action" in d["infox"]["genres"]


def test_parse_detail_episodes_deduped_and_sorted():
    d = _detail.parse_detail((FIX / "anichin_detail.html").read_text())
    eps = d["episodes"]
    assert eps, "no episodes parsed"
    ns = [e["n"] for e in eps]
    assert len(ns) == len(set(ns)), "duplicate episode numbers"
    assert ns == sorted(ns), "episodes not sorted ascending"
    # each ep has n + url
    assert all("url" in e and e["url"] for e in eps)
    # ep URL is root-relative or absolute, contains -episode-
    assert "-episode-" in eps[0]["url"]


def test_parse_detail_no_score_field():
    # anichin has no Score/Skor label — must not fabricate one.
    d = _detail.parse_detail((FIX / "anichin_detail.html").read_text())
    assert "score" not in d["infox"] and "rating" not in d["infox"]
```

- [ ] **Step 2: Run test to verify it fails**

Run the stdlib harness (same pattern as Task 2 Step 2, module `sloane.tests.test_anichin_detail`).
Expected: FAIL — `ModuleNotFoundError: No module named 'sloane.sources.anichin._detail'`.

- [ ] **Step 3: Write minimal implementation `sources/anichin/_detail.py`**

```python
"""Parse an anichin series detail page (/anime/{slug}).

Metadata lives in .infox as <b>Label:</b><span> Value</span> pairs (verified live
2026-06-30). Labels are Indonesian: Tipe (type), Status, Studio, Season, Tanggal
rilis (released), Durasi, Negara (country). Genres are trailing unlabeled text
in .infox. anichin has NO Score field. The synopsis is the longest <p> in
.entry-content. Episode links live at /{slug}-episode-{N}-subtitle-indonesia/.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from . import _http

_EP_NUM_RE = re.compile(r"-episode-(\d+)-subtitle")

# .infox <b>Label:</b> -> payload key. Case-insensitive, trailing colon stripped.
# Only the subset that matters for canonical merge/enrich; admin/noise dropped.
_FIELD_LABELS = {
    "tipe": "type",
    "status": "status",
    "studio": "studio",
    "season": "season",
    "tanggal rilis": "released",
    "durasi": "duration",
    "negara": "country",
}


def parse_detail(html: str, base: str = _http.BASE_URL) -> dict:
    """Series detail -> metadata + episode links (no stream_url yet).

    Returns {slug, title, cover_url, synopsis, infox:{...}, episodes:[{n,url}]}.
    Unknown infox labels tolerated (robust to markup drift).
    """
    soup = BeautifulSoup(html, "lxml")
    infox: dict = {"genres": []}

    # Metadata: .infox <b>Label:</b><span> Value</span>. Walk .infox children.
    box = soup.select_one(".infox")
    if box:
        for b in box.find_all("b"):
            label = b.get_text(strip=True).lower().rstrip(":").strip()
            # value: the <span> sibling that follows this <b>.
            sib = b.find_next_sibling("span")
            val = sib.get_text(" ", strip=True) if sib else None
            key = _FIELD_LABELS.get(label)
            if key:
                infox[key] = val or None

        # Genres: <a> tags inside .infox that link to /genres/ (the trailing
        # unlabeled block). Collect their text, dedup, preserve order.
        ga = [g.get_text(strip=True) for g in box.select("a[href*='/genres/']")
              if g.get_text(strip=True)]
        if ga:
            infox["genres"] = list(dict.fromkeys(ga))

    # Title: first <h1> (entry-title or bare h1).
    h1 = soup.select_one("h1.entry-title, h1")
    title = h1.get_text(" ", strip=True) if h1 else None

    # Cover: .wp-post-image or itemprop=image img.
    img = soup.select_one("img.wp-post-image, [itemprop='image'] img, .thumb img")
    cover_url = img.get("src") if img else None

    # Synopsis: longest <p> in the description container.
    syn = soup.select_one(".entry-content, [itemprop='description']")
    synopsis = None
    if syn:
        paras = [p.get_text(" ", strip=True) for p in syn.select("p") if p.get_text(strip=True)]
        synopsis = max(paras, key=len) if paras else syn.get_text(" ", strip=True)

    # Slug: derive from canonical <link> or og:url if present, else from title fallback.
    slug = None
    canon = soup.select_one("link[rel='canonical']")
    if canon and canon.get("href"):
        m = re.search(r"/anime/([^/]+)/?", urlparse(canon.get("href")).path)
        if m:
            slug = m.group(1)

    # Episode links: /{slug}-episode-{N}-subtitle-indonesia/. Dedup by URL;
    # extract N from the URL path; sort ascending by N.
    seen: set[str] = set()
    episodes: list[dict] = []
    for a in soup.select("a[href*='-episode-']"):
        href = a.get("href", "").strip()
        if not href or href in seen:
            continue
        # skip share/social links that happen to contain -episode-
        if "/sharer" in href or "/share" in href:
            continue
        seen.add(href)
        m = _EP_NUM_RE.search(urlparse(href).path)
        if not m:
            continue
        if not href.startswith("http"):
            href = f"{base.rstrip('/')}/{href.lstrip('/')}"
        episodes.append({"n": int(m.group(1)), "url": href})
    episodes.sort(key=lambda e: e["n"])

    return {
        "slug": slug,
        "title": title,
        "cover_url": cover_url,
        "synopsis": synopsis,
        "infox": infox,
        "episodes": episodes,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run the stdlib harness (module `sloane.tests.test_anichin_detail`).
Expected: `3 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add sources/anichin/_detail.py tests/test_anichin_detail.py
git commit -m "feat(sloane/anichin): add _detail parser (metadata + episode list)"
```

---

### Task 4: `sources/anichin/_episodes.py` — episode page stream src

**Files:**
- Create: `sources/anichin/_episodes.py`
- Test: `tests/test_anichin_episodes.py`

**Interfaces:**
- Consumes: none (pure HTML parse).
- Produces: `parse_episode(html: str) -> dict` with keys `n (int|None), stream_url (str|None)`. `stream_url` is the first `iframe[src*="dailymotion"]` src, or `None` if no iframe.

- [ ] **Step 1: Write the failing test `tests/test_anichin_episodes.py`**

```python
"""_episodes parser tests — episode number + Dailymotion stream src."""
from pathlib import Path

from sloane.sources.anichin import _episodes

FIX = Path(__file__).parent / "fixtures"


def test_parse_episode_extracts_n_and_stream():
    d = _episodes.parse_episode((FIX / "anichin_episode.html").read_text())
    assert d["n"] == 670
    assert d["stream_url"] and "dailymotion" in d["stream_url"]


def test_parse_episode_no_iframe_returns_none_stream():
    # detail page has no dailymotion iframe -> stream_url None, n still parsed.
    d = _episodes.parse_episode((FIX / "anichin_detail.html").read_text())
    assert d["stream_url"] is None


def test_parse_episode_missing_n_returns_none():
    html = "<html><body><h1>Some title without episode number</h1></body></html>"
    d = _episodes.parse_episode(html)
    assert d["n"] is None
    assert d["stream_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run the stdlib harness (module `sloane.tests.test_anichin_episodes`).
Expected: FAIL — `ModuleNotFoundError: No module named 'sloane.sources.anichin._episodes'`.

- [ ] **Step 3: Write minimal implementation `sources/anichin/_episodes.py`**

```python
"""Parse an anichin episode page (/{slug}-episode-{N}-subtitle-indonesia/).

anichin episodes are streaming-only: the page embeds a Dailymotion iframe. There
are NO download-host links on the page (the word "Download" appears only in the
JSON-LD meta description). We extract the episode number + the iframe stream src.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_EP_NUM_RE = re.compile(r"-episode-(\d+)-subtitle")


def parse_episode(html: str) -> dict:
    """Episode page -> {n, stream_url}.

    n: int from the -episode-{N}-subtitle pattern (h1 or <title>), else None.
    stream_url: first iframe[src*="dailymotion"] src, else None (page may be
    JS-gated on some episodes — don't fail ingest for a missing iframe).
    """
    soup = BeautifulSoup(html, "lxml")

    # Episode number: prefer h1, fall back to <title>.
    n = None
    h1 = soup.select_one("h1.entry-title, h1")
    title_el = soup.select_one("title")
    for el in (h1, title_el):
        if el:
            m = _EP_NUM_RE.search(el.get_text(" ", strip=True))
            if m:
                n = int(m.group(1))
                break

    # Stream src: first Dailymotion iframe.
    iframe = soup.select_one("iframe[src*='dailymotion']")
    stream_url = iframe.get("src") if iframe else None

    return {"n": n, "stream_url": stream_url}
```

- [ ] **Step 4: Run test to verify it passes**

Run the stdlib harness (module `sloane.tests.test_anichin_episodes`).
Expected: `3 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add sources/anichin/_episodes.py tests/test_anichin_episodes.py
git commit -m "feat(sloane/anichin): add _episodes parser (stream src)"
```

---

### Task 5: `ingest/anichin.py` — delta + discover + backfill runner

**Files:**
- Create: `ingest/anichin.py`
- Test: `tests/test_anichin_ingest.py`

**Interfaces:**
- Consumes: `sources.anichin._http` (BASE_URL, HEADERS, client), `sources.anichin._lists` (parse_update_list, walk_directory), `sources.anichin._detail` (parse_detail), `sources.anichin._episodes` (parse_episode), `shared.config.pg_dsn`, `shared.schema_contract.{CanonicalEntity, KIND_ANIME}`, `sloane.db.writer.write_entities`, `sloane.store.merger.merge_raw_to_canonical`, `sloane.store.enricher.enrich_canonical`, `sloane.store.state.{get_state, set_state, add_seen}`.
- Produces: `ingest_updates(dsn=None, max_new=None) -> dict` `{fetched, updated_series, new_episodes, skipped}`; `discover_new_series(dsn=None, max_new=None) -> dict` `{discovered, ingested}`; `backfill_all(dsn=None, workers=6, limit=None, log=print) -> dict` `{total, ingested, failed, skipped_existing}`. Module constants `SOURCE = "anichin"`, `BACKFILL_KEY = "backfill_done"`.

- [ ] **Step 1: Write the failing test `tests/test_anichin_ingest.py`**

```python
"""anichin ingest runner tests — ep-number delta diff + discover + backfill resume.

The core invariant: ingest_updates must fetch ONLY new episode pages (n > old_max),
not re-fetch the whole episode list. This is what makes the no-RSS delta cheap.
"""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from tests._monkeypatch import MonkeyPatch

from sloane.ingest import anichin as A

FIX = Path(__file__).parent / "fixtures"


def _fake_http_client(get_map: dict):
    """Build a fake httpx.Client whose .get(url).text returns get_map[url]."""
    cx = MagicMock()
    def _get(url, **kw):
        r = MagicMock()
        r.text = get_map.get(url, "")
        r.raise_for_status = lambda: None
        return r
    cx.get.side_effect = _get
    return cx


def test_ingest_updates_fetches_only_new_episode_pages():
    """old_max=668 in DB, detail lists eps up to 670 -> only ep 669 + 670 fetched."""
    mp = MonkeyPatch()
    try:
        # DB returns existing payload with eps up to 668.
        existing_payload = {"episodes": [{"n": i, "url": f"/martial-master-episode-{i}-subtitle-indonesia/"} for i in range(668, 0, -1)]}
        mp.setattr(A, "load_series_payload", lambda dsn, slug: {"title": "Martial Master", **existing_payload})
        mp.setattr(A, "patch_series", lambda dsn, slug, title, url, payload: 1)
        mp.setattr(A, "merge_raw_to_canonical", lambda *a, **k: {"canonical_id": 1})
        mp.setattr(A, "enrich_canonical", lambda *a, **k: {})

        # _lists.parse_update_list returns one series.
        from sloane.sources.anichin import _lists, _detail, _episodes, _http
        mp.setattr(_lists, "parse_update_list", lambda html: [{"slug": "martial-master", "title": "Martial Master"}])

        # detail: parse_detail returns eps 668,669,670 (old_max=668 -> new = 669,670).
        detail_html = (FIX / "anichin_detail.html").read_text()
        ep_html = (FIX / "anichin_episode.html").read_text()

        fetched_eps = []
        def fake_parse_detail(html, base=None):
            # return a controlled episode list so the test is deterministic
            return {"slug": "martial-master", "title": "Martial Master", "cover_url": None,
                    "synopsis": "x", "infox": {"type": "Donghua", "status": "Ongoing", "genres": []},
                    "episodes": [{"n": 668, "url": "/martial-master-episode-668-subtitle-indonesia/"},
                                 {"n": 669, "url": "/martial-master-episode-669-subtitle-indonesia/"},
                                 {"n": 670, "url": "/martial-master-episode-670-subtitle-indonesia/"}]}
        mp.setattr(_detail, "parse_detail", fake_parse_detail)

        # parse_episode records which ep pages were fetched.
        def fake_parse_episode(html):
            # the runner fetches ep.url then calls parse_episode on the result;
            # we can't see the url here, so track via a wrapper on cx.get below.
            return {"n": None, "stream_url": "https://geo.dailymotion.com/x"}
        mp.setattr(_episodes, "parse_episode", fake_parse_episode)

        # Fake client: update-list page -> detail page; ep-page fetches tracked.
        cx = MagicMock()
        ep_urls_seen = []
        def _get(url, **kw):
            r = MagicMock(); r.raise_for_status = lambda: None
            if "order=update" in url:
                r.text = "LIST"
            elif url.endswith("/anime/martial-master/"):
                r.text = detail_html
            elif "-episode-" in url:
                ep_urls_seen.append(url)
                r.text = ep_html
            else:
                r.text = ""
            return r
        cx.get.side_effect = _get
        mp.setattr(_http, "client", lambda: cx)

        result = A.ingest_updates(dsn="dummy")
        # only ep 669 + 670 should have been fetched (old_max=668)
        assert len(ep_urls_seen) == 2, f"expected 2 ep fetches, got {len(ep_urls_seen)}: {ep_urls_seen}"
        assert result["new_episodes"] == 2
        assert result["updated_series"] == 1
    finally:
        mp.undo()


def test_ingest_updates_skips_series_not_in_db():
    """Series absent from DB -> skipped (discover job will add it)."""
    mp = MonkeyPatch()
    try:
        mp.setattr(A, "load_series_payload", lambda dsn, slug: None)
        mp.setattr(A, "patch_series", lambda *a, **k: 1)
        mp.setattr(A, "merge_raw_to_canonical", lambda *a, **k: {"canonical_id": 1})
        mp.setattr(A, "enrich_canonical", lambda *a, **k: {})
        from sloane.sources.anichin import _lists, _http
        mp.setattr(_lists, "parse_update_list", lambda html: [{"slug": "new-series", "title": "New"}])
        cx = MagicMock()
        cx.get.return_value.text = ""
        mp.setattr(_http, "client", lambda: cx)
        result = A.ingest_updates(dsn="dummy")
        assert result["updated_series"] == 0
        assert result["skipped"] == 1
    finally:
        mp.undo()


def test_discover_new_series_skips_existing():
    mp = MonkeyPatch()
    try:
        mp.setattr(A, "load_series_payload", lambda dsn, slug: {"title": slug} if slug == "martial-master" else None)
        mp.setattr(A, "patch_series", lambda *a, **k: 1)
        mp.setattr(A, "merge_raw_to_canonical", lambda *a, **k: {"canonical_id": 1})
        mp.setattr(A, "enrich_canonical", lambda *a, **k: {})
        from sloane.sources.anichin import _lists, _detail, _http
        mp.setattr(_lists, "walk_directory", lambda cx: [{"slug": "martial-master", "title": "Martial Master"},
                                                         {"slug": "new-one", "title": "New One"}])
        mp.setattr(_detail, "parse_detail", lambda html, base=None: {"slug": "new-one", "title": "New One",
                    "cover_url": None, "synopsis": "x", "infox": {"genres": []},
                    "episodes": [{"n": 1, "url": "/new-one-episode-1-subtitle-indonesia/"}]})
        cx = MagicMock(); cx.get.return_value.text = ""
        mp.setattr(_http, "client", lambda: cx)
        result = A.discover_new_series(dsn="dummy")
        assert result["discovered"] == 1  # only new-one (martial-master already in DB)
        assert result["ingested"] == 1
    finally:
        mp.undo()
```

- [ ] **Step 2: Run test to verify it fails**

Run the stdlib harness (module `sloane.tests.test_anichin_ingest`).
Expected: FAIL — `ModuleNotFoundError: No module named 'sloane.ingest.anichin'`.

- [ ] **Step 3: Write minimal implementation `ingest/anichin.py`**

```python
"""anichin incremental ingest runner.

2h job (ingest_updates): fetch /anime/?order=update, and for each listed series
diff the detail page's max episode number against the DB payload's max. Fetch
ONLY the new episode pages (n > old_max), parse their Dailymotion stream_url,
and load-mutate-upsert the parent series raw_entities row (write_entities replaces
payload wholesale, so we SELECT the existing payload, append new eps with
stream_url, UPSERT the full entity). Then merge_raw. No RSS feed (disabled) —
ep-number diff is the delta primitive.

daily job (discover_new_series): A-Z directory walk -> slugs absent from
raw_entities -> full series fetch -> write_entities -> merge -> enrich. Stores
episodes WITHOUT stream_url (deferred — full-eps fetch is too heavy for a daily
sweep; stream_url filled later by ingest_updates for new eps or by backfill).

backfill (backfill_all): full historical ingest of every series from the A-Z
directory (~700), each with ALL episode pages parsed for stream_url. Concurrent
(httpx.AsyncClient + N workers) because the scale (~50k episode pages for the
long donghua runners) makes sequential impractical. Resumable via ingest_state
backfill_done slug set.

Idempotency (write_entities ON CONFLICT + merge_raw ON CONFLICT) protects a
mid-run crash: redundant work at worst, never duplicate data.
"""
from __future__ import annotations

import asyncio

import httpx
import psycopg

from shared.config import pg_dsn
from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.db.writer import write_entities
from sloane.store.merger import merge_raw_to_canonical
from sloane.store.enricher import enrich_canonical
from sloane.store.state import get_state, set_state
from sloane.sources.anichin import _detail, _episodes, _http, _lists

SOURCE = "anichin"
BACKFILL_KEY = "backfill_done"


def load_series_payload(dsn: str, slug: str) -> dict | None:
    """SELECT existing raw_entities.payload for this series slug. None if absent."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        row = cur.execute(
            "SELECT payload, title FROM raw_entities WHERE source=%s AND external_id=%s",
            (SOURCE, slug),
        ).fetchone()
    if not row:
        return None
    return {"title": row[1], **(row[0] or {})}


def patch_series(dsn: str, slug: str, title: str, url: str, payload: dict) -> int:
    """Build + UPSERT the series CanonicalEntity. Returns raw_id."""
    res = write_entities(dsn, [
        CanonicalEntity(
            source=SOURCE, external_id=slug, kind=KIND_ANIME,
            title=title, url=url, payload=payload,
        )
    ])
    return res.raw_ids[0]


def _max_ep(payload: dict) -> int:
    """Highest episode number in payload['episodes'], or 0 if none."""
    eps = payload.get("episodes") or []
    return max((e.get("n") or 0 for e in eps), default=0)


def _merge_episodes(old: list, new: list) -> list:
    """Union old + new episode dicts, dedup by n (new wins), sorted ascending."""
    by_n = {e["n"]: e for e in old if "n" in e}
    for e in new:
        if "n" in e:
            by_n[e["n"]] = e
    return sorted(by_n.values(), key=lambda e: e["n"])


def ingest_updates(dsn: str | None = None, max_new: int | None = None) -> dict:
    """2h job: latest-update-list delta ingest of new episodes.

    Returns {fetched, updated_series, new_episodes, skipped}.
    """
    dsn = dsn or pg_dsn()
    updated = skipped = new_eps_total = 0

    with _http.client() as cx:
        list_html = cx.get(f"{_http.BASE_URL}/anime/?status=&type=&order=update").text
        series = _lists.parse_update_list(list_html)
        if max_new is not None:
            series = series[:max_new]

        for item in series:
            slug = item["slug"]
            existing = load_series_payload(dsn, slug)
            if existing is None:
                # series not yet in DB; discover job will add it. skip.
                skipped += 1
                continue
            try:
                detail_html = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)
            except Exception:
                skipped += 1
                continue

            old_max = _max_ep({"episodes": existing.get("episodes", [])})
            new_eps = [e for e in detail["episodes"] if e["n"] > old_max]
            if not new_eps:
                continue  # up to date

            # Fetch only new episode pages -> parse stream_url.
            for ep in new_eps:
                try:
                    ep_html = cx.get(ep["url"]).text
                    parsed = _episodes.parse_episode(ep_html)
                    ep["stream_url"] = parsed.get("stream_url")
                except Exception:
                    ep["stream_url"] = None

            title = existing.get("title") or item["title"]
            payload = {k: v for k, v in existing.items() if k != "title"}
            payload["episodes"] = _merge_episodes(
                payload.get("episodes", []),
                [{"n": e["n"], "url": e["url"], "stream_url": e.get("stream_url")} for e in new_eps],
            )
            # carry detail metadata forward if missing (first delta after discover)
            payload.setdefault("cover_url", detail.get("cover_url"))
            payload.setdefault("synopsis", detail.get("synopsis"))
            payload.setdefault("infox", detail.get("infox"))

            raw_id = patch_series(dsn, slug, title, f"{_http.BASE_URL}/anime/{slug}/", payload)
            merge_raw_to_canonical(raw_id, title, KIND_ANIME, payload, dsn=dsn)
            # No enrich here: canonical + mal_id already resolved at discover time.
            updated += 1
            new_eps_total += len(new_eps)

    return {"fetched": len(series), "updated_series": updated,
            "new_episodes": new_eps_total, "skipped": skipped}


def discover_new_series(dsn: str | None = None, max_new: int | None = None) -> dict:
    """daily job: A-Z directory walk -> slugs absent from raw_entities -> full fetch.

    Stores episodes WITHOUT stream_url (deferred to ingest_updates / backfill).
    Returns {discovered, ingested}.
    """
    dsn = dsn or pg_dsn()
    discovered = ingested = 0
    with _http.client() as cx:
        all_series = _lists.walk_directory(cx)
        if max_new is not None:
            all_series = all_series[:max_new]
        for item in all_series:
            slug = item["slug"]
            if load_series_payload(dsn, slug) is not None:
                continue  # already in DB
            discovered += 1
            try:
                detail_html = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)
                payload = {
                    "cover_url": detail.get("cover_url"),
                    "synopsis": detail.get("synopsis"),
                    "infox": detail.get("infox"),
                    "episodes": detail["episodes"],  # [{n,url}] — no stream_url yet
                }
                raw_id = patch_series(dsn, slug, item["title"],
                                      f"{_http.BASE_URL}/anime/{slug}/", payload)
                mr = merge_raw_to_canonical(raw_id, item["title"], KIND_ANIME,
                                            payload, dsn=dsn)
                enrich_canonical(mr["canonical_id"], item["title"], dsn=dsn)
                ingested += 1
            except Exception:
                continue
    return {"discovered": discovered, "ingested": ingested}


# ---------------------------------------------------------------------------
# Backfill: full historical ingest (all series + all episode stream_urls).
# ---------------------------------------------------------------------------

# Episode page fetches are the cost driver (Martial Master alone = 720). Cap
# concurrency to respect the site. ponytail: raise to 12-16 once a run confirms
# no rate-limit 429s.
BACKFILL_WORKERS = 6


async def _fetch_one(cx: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> str | None:
    """Fetch one page under the concurrency semaphore. None on failure."""
    async with sem:
        try:
            r = await cx.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception:
            return None


async def _fetch_series_full(cx, sem, slug: str, title: str) -> dict | None:
    """Fetch a series detail + ALL its episode pages concurrently.

    Returns the full payload dict (episodes with stream_url) for one series,
    or None if the detail page itself failed.
    """
    series_url = f"{_http.BASE_URL}/anime/{slug}/"
    detail_html = await _fetch_one(cx, series_url, sem)
    if not detail_html:
        return None
    detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)

    ep_urls = [e["url"] for e in detail["episodes"]]
    ep_htmls = await asyncio.gather(*[_fetch_one(cx, u, sem) for u in ep_urls])
    episodes = []
    for ep, html in zip(detail["episodes"], ep_htmls):
        stream_url = None
        if html:
            stream_url = _episodes.parse_episode(html).get("stream_url")
        episodes.append({"n": ep["n"], "url": ep["url"], "stream_url": stream_url})

    return {
        "cover_url": detail.get("cover_url"),
        "synopsis": detail.get("synopsis"),
        "infox": detail.get("infox"),
        "episodes": episodes,
    }


async def _backfill_async(dsn, series, workers, log) -> dict:
    sem = asyncio.Semaphore(workers)
    ingested = failed = 0
    done: set[str] = set(get_state(dsn, SOURCE, BACKFILL_KEY, default=[]) or [])
    async with httpx.AsyncClient(headers=_http.HEADERS, follow_redirects=True) as cx:
        BATCH = 10
        for i in range(0, len(series), BATCH):
            chunk = [s for s in series[i:i + BATCH] if s["slug"] not in done]
            if not chunk:
                continue
            results = await asyncio.gather(
                *[_fetch_series_full(cx, sem, s["slug"], s["title"]) for s in chunk]
            )
            for s, payload in zip(chunk, results):
                slug = s["slug"]
                if payload is None:
                    failed += 1
                    continue
                try:
                    raw_id = patch_series(dsn, slug, s["title"],
                                          f"{_http.BASE_URL}/anime/{slug}/", payload)
                    mr = merge_raw_to_canonical(raw_id, s["title"], KIND_ANIME,
                                                payload, dsn=dsn)
                    enrich_canonical(mr["canonical_id"], s["title"], dsn=dsn)
                    ingested += 1
                    done.add(slug)
                except Exception:
                    failed += 1
            # persist progress so a crash resumes past completed slugs
            set_state(dsn, SOURCE, BACKFILL_KEY, sorted(done))
            log(f"backfill: {min(i + BATCH, len(series))}/{len(series)} "
                f"(ingested {ingested}, failed {failed})")
    return {"total": len(series), "ingested": ingested, "failed": failed}


def backfill_all(dsn: str | None = None, workers: int = BACKFILL_WORKERS,
                 limit: int | None = None, log=print) -> dict:
    """Full historical ingest: every series from A-Z + all episode stream_urls.

    Resumable via ingest_state backfill_done slug set — a crash + re-run skips
    completed series. `limit` caps the series count (smoke).
    """
    dsn = dsn or pg_dsn()
    with _http.client() as cx:
        all_series = _lists.walk_directory(cx)
    if limit is not None:
        all_series = all_series[:limit]

    done: set[str] = set(get_state(dsn, SOURCE, BACKFILL_KEY, default=[]) or [])
    new_series = [s for s in all_series if s["slug"] not in done]
    log(f"backfill: {len(all_series)} series in directory, "
        f"{len(new_series)} new ({len(all_series) - len(new_series)} already done)")

    if not new_series:
        return {"total": 0, "ingested": 0, "failed": 0,
                "skipped_existing": len(all_series)}

    return asyncio.run(_backfill_async(dsn, all_series, workers, log))
```

- [ ] **Step 4: Run test to verify it passes**

Run the stdlib harness (module `sloane.tests.test_anichin_ingest`).
Expected: `3 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add ingest/anichin.py tests/test_anichin_ingest.py
git commit -m "feat(sloane/anichin): add ingest runner (delta + discover + backfill)"
```

---

### Task 6: Wire `anichin` into `ingest/__main__.py` CLI

**Files:**
- Modify: `ingest/__main__.py`
- Test: manual smoke (no new test file — trivial dispatch).

**Interfaces:**
- Consumes: `sloane.ingest.anichin.{ingest_updates, discover_new_series, backfill_all}`.

- [ ] **Step 1: Modify `ingest/__main__.py`**

Add `anichin` to source choices and dispatch. The updated file:

```python
"""CLI entry for sloane ingest runners.

Usage:
  python -m sloane.ingest samehadaku              # 2h feed-delta ingest
  python -m sloane.ingest samehadaku --discover   # daily new-series sweep
  python -m sloane.ingest samehadaku --backfill   # full historical ingest
  python -m sloane.ingest anichin                 # 2h latest-update delta ingest
  python -m sloane.ingest anichin --discover      # daily A-Z new-series sweep
  python -m sloane.ingest anichin --backfill      # full historical ingest
  python -m sloane.ingest <source> --max-new 5    # smoke cap

Prints JSON result to stdout (journald captures it under systemd).
"""
from __future__ import annotations
import argparse
import json
import sys

from sloane.ingest.samehadaku import ingest_feed, discover_new_series as discover_samehadaku, backfill_all as backfill_samehadaku
from sloane.ingest.anichin import ingest_updates as ingest_anichin, discover_new_series as discover_anichin, backfill_all as backfill_anichin


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sloane-ingest")
    p.add_argument("source", choices=["samehadaku", "anichin"])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--discover", action="store_true",
                   help="run new-series discovery instead of delta ingest")
    g.add_argument("--backfill", action="store_true",
                   help="full historical ingest (all series + all episodes)")
    p.add_argument("--max-new", type=int, default=None,
                   help="cap new items ingested (smoke); for --backfill caps series count")
    p.add_argument("--workers", type=int, default=6,
                   help="concurrency for --backfill (default 6)")
    args = p.parse_args(argv)

    if args.source == "samehadaku":
        if args.backfill:
            result = backfill_samehadaku(workers=args.workers, limit=args.max_new)
        elif args.discover:
            result = discover_samehadaku(max_new=args.max_new)
        else:
            result = ingest_feed(max_new=args.max_new)
    elif args.source == "anichin":
        if args.backfill:
            result = backfill_anichin(workers=args.workers, limit=args.max_new)
        elif args.discover:
            result = discover_anichin(max_new=args.max_new)
        else:
            result = ingest_anichin(max_new=args.max_new)
    else:
        p.error(f"unknown source {args.source}")
        return 2

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify CLI wiring (no DB needed — argparse + import only)**

Run: `.venv-adk/bin/python -m sloane.ingest anichin --help`
Expected: prints usage mentioning `anichin`, exit 0.

Run: `.venv-adk/bin/python -c "from sloane.ingest.anichin import ingest_updates, discover_new_series, backfill_all; print('ok')"`
Expected: prints `ok`, no ImportError.

- [ ] **Step 3: Commit**

```bash
git add ingest/__main__.py
git commit -m "feat(sloane): wire anichin into ingest CLI dispatch"
```

---

### Task 7: Integration smoke + systemd deploy units

**Files:**
- Create: `deploy/sloane-anichin-ingest.service`
- Create: `deploy/sloane-anichin-ingest.timer`
- Create: `deploy/sloane-anichin-discover.service`
- Create: `deploy/sloane-anichin-discover.timer`
- Modify: `deploy/README.md` (add anichin units to the list)

**Interfaces:**
- Consumes: `sloane.ingest.anichin` via `python -m sloane.ingest anichin`.

- [ ] **Step 1: Read existing samehadaku units to mirror exactly**

Run: `cat deploy/sloane-samehadaku-ingest.service deploy/sloane-samehadaku-ingest.timer deploy/sloane-samehadaku-discover.service deploy/sloane-samehadaku-discover.timer`

Note the `ExecStart`, `WorkingDirectory`, `Environment` lines — anichin units differ ONLY in `ExecStart` source arg and unit Description.

- [ ] **Step 2: Create `deploy/sloane-anichin-ingest.service`**

Mirror the samehadaku ingest service exactly, changing only the Description and the `anichin` arg in ExecStart:

```ini
[Unit]
Description=sloane anichin 2h latest-update delta ingest
After=network-online.target sloane-db-tunnel.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin
```

(If the samehadaku unit sets `Environment=DOS_PGB_URL=...` or other env, copy that line verbatim — match the existing unit exactly except for source arg + Description.)

- [ ] **Step 3: Create `deploy/sloane-anichin-ingest.timer`**

```ini
[Unit]
Description=sloane anichin 2h delta ingest timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=2h
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Create `deploy/sloane-anichin-discover.service`**

```ini
[Unit]
Description=sloane anichin daily A-Z new-series discovery
After=network-online.target sloane-db-tunnel.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --discover
```

- [ ] **Step 5: Create `deploy/sloane-anichin-discover.timer`**

```ini
[Unit]
Description=sloane anichin daily discovery timer

[Timer]
OnCalendar=*-*-* 05:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 6: Update `deploy/README.md`**

Add an anichin section mirroring the samehadaku section: list the two timers (`sloane-anichin-ingest.timer` 2h, `sloane-anichin-discover.timer` daily 05:00), note they depend on `sloane-db-tunnel.service`, and the `systemctl --user enable --now` install command.

- [ ] **Step 7: Integration smoke (manual, requires tunnel + DOS_PGB_URL)**

Run: `.venv-adk/bin/python -m sloane.ingest anichin --max-new 1`
Expected: exits 0, prints JSON with `updated_series` or `skipped` count, no traceback. Verify in DB:
`.venv-adk/bin/python -c "import psycopg,os; from shared.config import pg_dsn; c=psycopg.connect(pg_dsn()); print(c.execute(\"SELECT external_id, jsonb_array_length(payload->'episodes') FROM raw_entities WHERE source='anichin' LIMIT 3\").fetchall())"`
Expected: rows present with episode counts.

- [ ] **Step 8: Commit**

```bash
git add deploy/sloane-anichin-*.service deploy/sloane-anichin-*.timer deploy/README.md
git commit -m "feat(sloane/anichin): add systemd ingest + discover timers"
```

---

## Self-Review Notes

**Spec coverage:** every spec section maps to a task — site map (Tasks 2-4 parsers), architecture/components (Tasks 1-5), data flow delta/discover/backfill (Task 5), error handling (Task 5 try/except per-series), testing (Tasks 2-5 tests + Task 7 smoke), restart resilience (Task 5 `backfill_done` state), infox labels (Task 3 verified live). No gaps.

**Key type consistency:** `parse_detail` returns `episodes:[{n,url}]` (int n) — `ingest_updates` reads `e["n"]`, `_merge_episodes` keys by `e["n"]`, backfill appends `{n,url,stream_url}`. `parse_episode` returns `{n, stream_url}`. `load_series_payload`/`patch_series` signatures match samehadaku's. `discover_new_series` + `backfill_all` signatures match `__main__.py` dispatch in Task 6.

**Testing caveat:** anichin tests use the saved fixtures (no live network). `test_anichin_ingest` monkeypatches `load_series_payload`/`patch_series`/`merge_raw_to_canonical`/`enrich_canonical` AND the source parsers, so no DB or network is needed. `test_state.py` (existing) already covers `ingest_state` CRUD — anichin reuses the same table, no new state tests needed.
