"""anichin ingest runner tests — ep-number delta diff + discover + backfill resume.

The core invariant: ingest_updates must fetch ONLY new episode pages (n > old_max),
not re-fetch the whole episode list. This is what makes the no-RSS delta cheap.
"""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from sloane.tests._monkeypatch import MonkeyPatch

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
        mp.setattr((A, "load_series_payload"), lambda dsn, slug: {"title": "Martial Master", **existing_payload})
        mp.setattr((A, "patch_series"), lambda dsn, slug, title, url, payload: 1)
        mp.setattr((A, "merge_raw_to_canonical"), lambda *a, **k: {"canonical_id": 1})
        mp.setattr((A, "enrich_canonical"), lambda *a, **k: {})

        # _lists.parse_update_list returns one series.
        from sloane.sources.anichin import _lists, _detail, _episodes, _http
        mp.setattr((_lists, "parse_update_list"), lambda html: [{"slug": "martial-master", "title": "Martial Master"}])

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
        mp.setattr((_detail, "parse_detail"), fake_parse_detail)

        # parse_episode records which ep pages were fetched.
        def fake_parse_episode(html):
            # the runner fetches ep.url then calls parse_episode on the result;
            # we can't see the url here, so track via a wrapper on cx.get below.
            return {"n": None, "stream_url": "https://geo.dailymotion.com/x"}
        mp.setattr((_episodes, "parse_episode"), fake_parse_episode)

        # Fake client: update-list page -> detail page; ep-page fetches tracked.
        cx = MagicMock()
        cx.__enter__.return_value = cx
        cx.__exit__.return_value = False
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
        mp.setattr((_http, "client"), lambda: cx)

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
        mp.setattr((A, "load_series_payload"), lambda dsn, slug: None)
        mp.setattr((A, "patch_series"), lambda *a, **k: 1)
        mp.setattr((A, "merge_raw_to_canonical"), lambda *a, **k: {"canonical_id": 1})
        mp.setattr((A, "enrich_canonical"), lambda *a, **k: {})
        from sloane.sources.anichin import _lists, _http
        mp.setattr((_lists, "parse_update_list"), lambda html: [{"slug": "new-series", "title": "New"}])
        cx = MagicMock()
        cx.__enter__.return_value = cx
        cx.__exit__.return_value = False
        cx.get.return_value.text = ""
        mp.setattr((_http, "client"), lambda: cx)
        result = A.ingest_updates(dsn="dummy")
        assert result["updated_series"] == 0
        assert result["skipped"] == 1
    finally:
        mp.undo()


def test_discover_new_series_skips_existing():
    mp = MonkeyPatch()
    try:
        mp.setattr((A, "load_series_payload"), lambda dsn, slug: {"title": slug} if slug == "martial-master" else None)
        mp.setattr((A, "patch_series"), lambda *a, **k: 1)
        mp.setattr((A, "merge_raw_to_canonical"), lambda *a, **k: {"canonical_id": 1})
        mp.setattr((A, "enrich_canonical"), lambda *a, **k: {})
        from sloane.sources.anichin import _lists, _detail, _http
        mp.setattr((_lists, "walk_directory"), lambda cx: [{"slug": "martial-master", "title": "Martial Master"},
                                                         {"slug": "new-one", "title": "New One"}])
        mp.setattr((_detail, "parse_detail"), lambda html, base=None: {"slug": "new-one", "title": "New One",
                    "cover_url": None, "synopsis": "x", "infox": {"genres": []},
                    "episodes": [{"n": 1, "url": "/new-one-episode-1-subtitle-indonesia/"}]})
        cx = MagicMock()
        cx.__enter__.return_value = cx
        cx.__exit__.return_value = False
        cx.get.return_value.text = ""
        mp.setattr((_http, "client"), lambda: cx)
        result = A.discover_new_series(dsn="dummy")
        assert result["discovered"] == 1  # only new-one (martial-master already in DB)
        assert result["ingested"] == 1
    finally:
        mp.undo()
