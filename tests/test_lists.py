"""_lists parser tests — both list layouts + directory walk.

Covers the bug backfill exposed: parse_series_list must handle BOTH
anime-terbaru (.thumb layout) and daftar-anime-2 (article.animpost layout).
"""
from unittest.mock import MagicMock

from sloane.sources.samehadaku import _lists


# anime-terbaru layout: .thumb a[itemprop=url] with img.npws
TERBARU_HTML = """
<div class="thumb"><a itemprop="url" title="Liar Game"
  href="https://v2.samehadaku.how/anime/liar-game/">
  <img class="npws" src="https://v2.samehadaku.how/cov/liar.jpg" alt="Liar Game"/></a></div>
<div class="thumb"><a itemprop="url" title="One Piece"
  href="https://v2.samehadaku.how/anime/one-piece/">
  <img class="npws" src="https://v2.samehadaku.how/cov/op.jpg" alt="One Piece"/></a></div>
"""

# daftar-anime-2 layout: article.animpost > .animposx > a (img.anmsa)
DIR_HTML = """
<article class="animpost post-1 anime">
 <div class="animepost"><div class="animposx">
  <a title="#Compass" href="https://v2.samehadaku.how/anime/compass2-0/">
   <div class="content-thumb"><img class="anmsa" src="https://v2.samehadaku.how/cov/comp.jpg" alt="#Compass"/></div></a>
 </div></div></article>
<article class="animpost post-2 anime">
 <div class="animepost"><div class="animposx">
  <a title="Naruto" href="https://v2.samehadaku.how/anime/naruto/">
   <div class="content-thumb"><img class="anmsa" src="https://v2.samehadaku.how/cov/naru.jpg" alt="Naruto"/></div></a>
 </div></div></article>
"""


def test_parse_series_list_anime_terbaru_layout():
    items = _lists.parse_series_list(TERBARU_HTML)
    assert len(items) == 2
    assert items[0] == {"slug": "liar-game", "title": "Liar Game",
                        "cover_url": "https://v2.samehadaku.how/cov/liar.jpg"}
    assert items[1]["slug"] == "one-piece"


def test_parse_series_list_directory_layout():
    # the bug: this returned [] before the union-selector fix.
    items = _lists.parse_series_list(DIR_HTML)
    assert len(items) == 2
    assert items[0]["slug"] == "compass2-0"
    assert items[0]["cover_url"].endswith("comp.jpg")
    assert items[1]["slug"] == "naruto"


def test_parse_series_list_dedups():
    # same slug twice on a page -> one entry.
    html = DIR_HTML + DIR_HTML
    assert len(_lists.parse_series_list(html)) == 2


def test_walk_directory_stops_at_empty_page():
    # page1 returns 2 series, page2 returns [] -> walk stops, returns 2.
    page1 = MagicMock(); page1.text = DIR_HTML
    empty = MagicMock(); empty.text = "<html></html>"
    cx = MagicMock()
    cx.get.side_effect = [page1, empty]
    items = _lists.walk_directory(cx)
    assert len(items) == 2
    assert cx.get.call_count == 2  # fetched page1 + page2 (empty) then stopped
