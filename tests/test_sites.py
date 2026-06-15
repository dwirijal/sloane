import sys
import os

# Add scraper directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scraper'))

from sites import get_scraper_for_url, SamehadakuScraper, AnichinScraper, KomikuScraper, KeikomikScraper, OploverzScraper, OtakuDesuScraper, AnimasuScraper, KanzeninScraper, BridgesScraper, MangaPlusScraper, GenericScraper

def test_get_scraper_for_url_samehadaku():
    scraper = get_scraper_for_url("https://v2.samehadaku.how/some-path")
    assert isinstance(scraper, SamehadakuScraper)
    assert scraper.content_type == "anime"

def test_get_scraper_for_url_anichin():
    scraper = get_scraper_for_url("https://anichin.cafe/")
    assert isinstance(scraper, AnichinScraper)
    assert scraper.content_type == "donghua"

def test_get_scraper_for_url_komiku():
    scraper = get_scraper_for_url("https://komiku.org/manga/")
    assert isinstance(scraper, KomikuScraper)
    assert scraper.content_type == "manga"

def test_get_scraper_for_url_keikomik():
    scraper = get_scraper_for_url("https://keikomik.web.id/comic/")
    assert isinstance(scraper, KeikomikScraper)
    assert scraper.content_type == "comic"

def test_get_scraper_for_url_oploverz():
    scraper = get_scraper_for_url("https://oploverz.fans/")
    assert isinstance(scraper, OploverzScraper)
    assert scraper.content_type == "anime"

def test_get_scraper_for_url_mangaplus():
    scraper = get_scraper_for_url("https://mangaplus.shueisha.co.jp/")
    assert isinstance(scraper, MangaPlusScraper)
    assert scraper.content_type == "manga"

def test_get_scraper_for_url_generic():
    scraper = get_scraper_for_url("https://unknown-site.com/")
    assert isinstance(scraper, GenericScraper)
    assert scraper.content_type == "other"
    assert scraper.base_url == "https://unknown-site.com"

def test_get_scraper_for_url_case_insensitive():
    scraper = get_scraper_for_url("HTTPS://V2.SAMEHADAKU.HOW/")
    assert isinstance(scraper, SamehadakuScraper)

def test_get_scraper_for_url_otakudesu():
    scraper = get_scraper_for_url("https://otakudesu.blog/anime/")
    assert isinstance(scraper, OtakuDesuScraper)
    assert scraper.content_type == "anime"
    assert scraper.domain == "otakudesu.blog"

def test_ip3_is_targeted():
    """Verify ip3 is in TARGET_SITES."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from main import TARGET_SITES
    assert "http://154.203.167.63/" in TARGET_SITES
    assert "https://otakudesu.blog/" in TARGET_SITES
    assert "https://animasu.care/" in TARGET_SITES
    assert "https://kanzenin.info/" in TARGET_SITES
    assert "https://bridgestoabrighterfuture.org/" in TARGET_SITES

def test_get_scraper_for_url_animasu():
    scraper = get_scraper_for_url("https://animasu.care/")
    assert isinstance(scraper, AnimasuScraper)
    assert scraper.content_type == "anime"

def test_get_scraper_for_url_kanzenin():
    scraper = get_scraper_for_url("https://kanzenin.info/")
    assert isinstance(scraper, KanzeninScraper)
    assert scraper.content_type == "manga"

def test_get_scraper_for_url_bridges():
    scraper = get_scraper_for_url("https://bridgestoabrighterfuture.org/")
    assert isinstance(scraper, BridgesScraper)
    assert scraper.content_type == "movie"