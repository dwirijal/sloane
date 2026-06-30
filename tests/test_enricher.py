"""enricher.resolve_mal_id tests: exact + conservative tier-2.

Tier-2 catches titles Jikan returns correctly but exact-match rejects
because of suffixes (Season 2, (Cour 2), 0, Reze-hen). Guard: never map
a season-suffixed query onto a base-series MAL entry (S2 -> S1 poison).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _monkeypatch import MonkeyPatch
import sloane.store.enricher as E


class _Resp:
    def __init__(self, data, status=200): self._d = data; self.status_code = status
    def json(self): return {"data": self._d}


def _mal(mal_id, title, type_="TV"):
    return {"mal_id": mal_id, "title": title, "type": type_}


def test_exact_match_still_works():
    # current behavior preserved: exact title -> that entry.
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(21, "One Piece"), _mal(20, "Naruto")]))
    r = E.resolve_mal_id("One Piece")
    mp.undo()
    assert r and r["mal_id"] == 21


def test_tier2_suffix_match_recovers_easy_miss():
    # Jujutsu Kaisen 0 -> MAL "Jujutsu Kaisen 0 Movie" (top hit, exact failed).
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(48561, "Jujutsu Kaisen 0 Movie", "Movie")]))
    r = E.resolve_mal_id("Jujutsu Kaisen 0")
    mp.undo()
    assert r and r["mal_id"] == 48561, r


def test_tier2_season_guard_blocks_s2_to_s1_poison():
    # query "Tomozaki-kun Season 2" but top Jikan hit is the S1 entry.
    # WRONG to map S2 -> S1 mal_id. Guard must reject -> None.
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(49676, "Jaku-Chara Tomozaki-kun", "TV")]))
    r = E.resolve_mal_id("Jaku-Chara Tomozaki-kun Season 2")
    mp.undo()
    assert r is None, f"guard failed: mapped S2 onto S1 {r}"


def test_tier2_season_guard_allows_when_mal_has_season_marker():
    # Mahoutsukai no Yome Season 2 -> MAL "Mahoutsukai no Yome Season 2" (has marker).
    # Same season marker on both sides -> safe to map.
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(54464, "Mahoutsukai no Yome Season 2", "TV")]))
    r = E.resolve_mal_id("Mahoutsukai no Yome Season 2 Cour 2")
    mp.undo()
    assert r and r["mal_id"] == 54464, r


def test_low_overlap_returns_none():
    # genuinely ambiguous / no close hit -> None, never fabricate.
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(1, "Totally Unrelated Anime", "TV")]))
    r = E.resolve_mal_id("Kanteishi")
    mp.undo()
    assert r is None


def test_movie_arc_series_resolves_without_movie_filter():
    # Jujutsu Kaisen 0 is a movie samehadaku lists as series — must still resolve
    # (the non-movie filter would have dropped mal 48561).
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(48561, "Jujutsu Kaisen 0 Movie", "Movie"),
                                      _mal(40748, "Jujutsu Kaisen", "TV")]))
    r = E.resolve_mal_id("Jujutsu Kaisen 0")
    mp.undo()
    assert r and r["mal_id"] == 48561, r


def test_recap_movie_does_not_shadow_base_series():
    # base-series query "Kimetsu no Yaiba" must NOT map onto a recap movie with
    # extra tokens (low overlap drops it) — guard against removing the Movie filter.
    mp = MonkeyPatch()
    mp.setattr((E.httpx, "get"),
               lambda *a, **k: _Resp([_mal(40456, "Kimetsu no Yaiba Movie: Mugen Ressha-hen", "Movie"),
                                      _mal(38000, "Kimetsu no Yaiba", "TV")]))
    r = E.resolve_mal_id("Kimetsu no Yaiba")
    mp.undo()
    assert r and r["mal_id"] == 38000, r
