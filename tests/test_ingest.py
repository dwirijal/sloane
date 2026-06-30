"""ingest.samehadaku tests — mocked HTTP + DB, no live network required.

Verifies the delta logic (only unseen posts ingested) and idempotency
(re-run ingests 0 new). Live end-to-end is the Task 6 integration smoke.
"""
from unittest.mock import MagicMock

from sloane.ingest.samehadaku import ingest_feed
import sloane.ingest.samehadaku as _ingest_mod
from sloane.tests._monkeypatch import MonkeyPatch

# Captured feed HTML: 2 episode posts for the one-piece series.
FEED_HTML = """<?xml version="1.0"?>
<rss><channel>
<item><link>https://v2.samehadaku.how/one-piece-episode-9999/</link><pubDate>Mon, 30 Jun 2026</pubDate></item>
<item><link>https://v2.samehadaku.how/one-piece-episode-9998/</link><pubDate>Sun, 29 Jun 2026</pubDate></item>
</channel></rss>"""

EP_PAGE_HTML = (
    '<div class="download-eps"><ul><li><strong>720p</strong>'
    '<span><a href="https://pixeldrain.com/u/x">Pixeldrain</a></span></li></ul></div>'
)

DSN = "postgresql://test:test@localhost/test"  # mocked; no real connect


def _mock_client():
    cx = MagicMock()
    feed_resp = MagicMock(); feed_resp.text = FEED_HTML
    ep_resp = MagicMock(); ep_resp.text = EP_PAGE_HTML
    # fetch_feed calls cx.get("/feed/"); then each new post page fetched.
    cx.get.side_effect = [feed_resp, ep_resp, ep_resp]
    # `with _http.client() as cx:` binds __enter__'s return — make it self.
    cx.__enter__.return_value = cx
    cx.__exit__.return_value = False
    return cx


def test_ingest_feed_deltas_and_ingests():
    mp = MonkeyPatch()
    # seen already has ep-9998 -> only ep-9999 is new.
    mp.setattr("sloane.ingest.samehadaku.get_state",
               lambda *a, default=None, **k: ["https://v2.samehadaku.how/one-piece-episode-9998/"])
    add_seen_calls = []
    mp.setattr("sloane.ingest.samehadaku.add_seen",
               lambda d, s, k, urls: add_seen_calls.extend(urls))
    mp.setattr((_ingest_mod._http, "client"), _mock_client)
    # existing series payload has no episodes yet.
    mp.setattr("sloane.ingest.samehadaku.load_series_payload",
               lambda d, s: {"title": "One Piece", "episodes": [], "batches": []})
    patched = {}
    mp.setattr("sloane.ingest.samehadaku.patch_series",
               lambda d, slug, title, url, p: patched.update(slug=slug, payload=p) or 1)
    mp.setattr("sloane.ingest.samehadaku.merge_raw_to_canonical",
               lambda *a, **k: {"canonical_id": 1})

    r = ingest_feed(dsn=DSN)
    mp.undo()
    assert r["ingested"] == 1, r
    assert any("one-piece-episode-9999" in u for u in add_seen_calls)
    # the new episode was appended to payload.episodes
    assert any(e["url"].endswith("episode-9999/") for e in patched["payload"]["episodes"])


def test_ingest_feed_idempotent_re_run():
    mp = MonkeyPatch()
    # both eps already seen -> ingested 0, no add_seen calls, no patch calls.
    seen = ["https://v2.samehadaku.how/one-piece-episode-9999/",
            "https://v2.samehadaku.how/one-piece-episode-9998/"]
    mp.setattr("sloane.ingest.samehadaku.get_state", lambda *a, default=None, **k: seen)
    add = []
    mp.setattr("sloane.ingest.samehadaku.add_seen", lambda *a, **k: add.append(1))
    mp.setattr((_ingest_mod._http, "client"), _mock_client)
    mp.setattr("sloane.ingest.samehadaku.patch_series", MagicMock())
    r = ingest_feed(dsn=DSN)
    mp.undo()
    assert r["ingested"] == 0
    assert r["new_urls"] == []
    assert add == []  # nothing new, no seen update


def test_ingest_feed_skips_when_series_missing():
    mp = MonkeyPatch()
    # brand-new series not in DB yet -> skipped, marked seen (don't retry).
    mp.setattr("sloane.ingest.samehadaku.get_state", lambda *a, default=None, **k: [])
    add_seen_calls = []
    mp.setattr("sloane.ingest.samehadaku.add_seen",
               lambda d, s, k, urls: add_seen_calls.extend(urls))
    mp.setattr((_ingest_mod._http, "client"), _mock_client)
    mp.setattr("sloane.ingest.samehadaku.load_series_payload", lambda d, s: None)
    mp.setattr("sloane.ingest.samehadaku.patch_series", MagicMock())
    r = ingest_feed(dsn=DSN)
    mp.undo()
    assert r["ingested"] == 0
    assert r["skipped"] == 2  # both posts skipped (series absent)
    # both URLs marked seen so we don't retry them forever
    assert len(add_seen_calls) == 2
