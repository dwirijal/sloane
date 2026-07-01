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
