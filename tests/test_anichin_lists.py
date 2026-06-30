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
