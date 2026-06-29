from pathlib import Path
from sloane.sources.samehadaku._feed import parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "samehadaku_feed.xml"

def test_parse_feed_returns_items():
    items = parse_feed(FIXTURE.read_text())
    assert items, "feed parsed no items"
    first = items[0]
    assert "url" in first and "pubdate" in first and "kind" in first
    assert first["url"].startswith("https://v2.samehadaku.how/")

def test_kind_inference_episode_and_batch():
    items = parse_feed(FIXTURE.read_text())
    kinds = {i["kind"] for i in items}
    assert "episode" in kinds  # -episode- URLs dominate the feed
    # batch posts may or may not be present; at least episode + valid kinds
    assert kinds <= {"episode", "batch", "post"}
    # an episode URL must classify as episode
    ep = next(i for i in items if "-episode-" in i["url"])
    assert ep["kind"] == "episode"
