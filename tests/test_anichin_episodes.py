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
