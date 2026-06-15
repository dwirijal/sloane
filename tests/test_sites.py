import sys
import os

# Add scraper directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scraper'))

from sites import get_scraper_for_url, SamehadakuScraper, AnichinScraper, KomikuScraper, KeikomikScraper, OploverzScraper, MangaPlusScraper, GenericScraper

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