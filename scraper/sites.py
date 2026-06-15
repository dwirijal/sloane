"""
Site-specific scraper for each target domain.
Implements custom extraction logic per site structure.
"""
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import re

from bs4 import BeautifulSoup


class SiteScraper:
    """Base class for site-specific scrapers."""

    def __init__(self, base_url: str, content_type: str = "other"):
        self.base_url = base_url.rstrip('/')
        self.content_type = content_type
        self.domain = urlparse(base_url).netloc
        # Common site name suffixes to strip from titles
        self.title_strip_patterns = []

    def clean_title(self, title: str) -> str:
        """Strip common site suffixes from title."""
        for pattern in self.title_strip_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()
        return title.strip(' –-— ')

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract title from page."""
        if soup.title:
            return self.clean_title(soup.title.string.strip())
        h1 = soup.find('h1')
        title = h1.get_text(strip=True) if h1 else "Unknown Title"
        return self.clean_title(title)

    def extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract description/synopsis with multiple fallback strategies."""
        # Strategy 1: meta description tag
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()

        # Strategy 2: og:description meta tag
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            return og_desc['content'].strip()

        # Strategy 3: twitter:description meta tag
        tw_desc = soup.find('meta', attrs={'name': 'twitter:description'})
        if tw_desc and tw_desc.get('content'):
            return tw_desc['content'].strip()

        # Strategy 4: entry-content class (common for WordPress sites)
        entry_content = soup.find(class_=re.compile(r'entry-content|post-content|article-body|desc', re.I))
        if entry_content:
            text = entry_content.get_text(strip=True)
            if len(text) > 50:
                return text

        # Strategy 5: content class
        content = soup.find(class_=re.compile(r'content|description|synopsis|info', re.I))
        if content:
            text = content.get_text(strip=True)
            if len(text) > 50:
                return text

        return None

    def extract_cover(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract cover image URL with multiple fallback strategies."""
        # Strategy 1: og:image meta tag (most reliable)
        og_image = soup.find('meta', attrs={'property': 'og:image'})
        if og_image and og_image.get('content'):
            return urljoin(self.base_url, og_image['content'])

        # Strategy 2: twitter:image meta tag
        tw_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            return urljoin(self.base_url, tw_image['content'])

        # Strategy 3: Image with class containing cover/poster/thumb/featured
        img = soup.find('img', class_=re.compile(r'cover|poster|thumb|featured|wp-post-image|attachment-', re.I))
        if img:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and not src.endswith(('.gif', '.svg')):
                return urljoin(self.base_url, src)

        # Strategy 4: First large image in article/content area
        article = soup.find(['article', 'main', 'div'], class_=re.compile(r'content|post|entry|main', re.I))
        if article:
            img = article.find('img')
            if img:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src and not src.endswith(('.gif', '.svg')):
                    return urljoin(self.base_url, src)

        # Strategy 5: Any reasonably-sized image
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and not src.endswith(('.gif', '.svg', '.ico')):
                return urljoin(self.base_url, src)

        return None

    def extract_streams(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract streaming URLs. Override per site."""
        return []

    def extract_downloads(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract download URLs. Override per site."""
        return []

    def extract_pages(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract manga page URLs. Override per site."""
        return []


class SamehadakuScraper(SiteScraper):
    """Scraper for v2.samehadaku.how - Indonesian anime streaming."""

    def __init__(self):
        super().__init__("https://v2.samehadaku.how/", "anime")

    def extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find('h1', class_='entry-title')
        return title_tag.get_text(strip=True) if title_tag else super().extract_title(soup)

    def extract_streams(self, soup: BeautifulSoup) -> List[Dict]:
        streams = []
        iframe = soup.find('iframe', src=True)
        if iframe:
            streams.append({
                'episode': 1,
                'url': iframe['src'],
                'quality': '720p'
            })
        return streams


class AnichinScraper(SiteScraper):
    """Scraper for anichin.cafe - Chinese anime (donghua)."""

    def __init__(self):
        super().__init__("https://anichin.cafe/", "donghua")
        self.title_strip_patterns = [
            r'\bAnichin\b', r'\bFansub\b', r'\bDonghua\b', r'\bSubtitle\b', r'\bIndonesia\b',
            r'\b–\s*Anichin\b', r'\b–\s*Fansub\b', r'\|\s*Anichin\b',
        ]

    def extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find('h1', class_='title')
        return title_tag.get_text(strip=True) if title_tag else super().extract_title(soup)


class KomikuScraper(SiteScraper):
    """Scraper for komiku.org - Indonesian manga."""

    def __init__(self):
        super().__init__("https://komiku.org/", "manga")
        self.title_strip_patterns = [
            r'\bKomiku\b', r'\bManga\b', r'\bBaca Komik\b', r'\bDownload\b',
        ]

    def extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find('h1', class_='entry-title')
        return title_tag.get_text(strip=True) if title_tag else super().extract_title(soup)

    def extract_cover(self, soup: BeautifulSoup) -> Optional[str]:
        # Komiku uses wp-post-image or attachment-post-thumbnail class for covers
        img = soup.find('img', class_=re.compile(r'wp-post-image|post-thumbnail|attachment-', re.I))
        if img:
            src = img.get('src') or img.get('data-src')
            if src:
                return urljoin(self.base_url, src)
        return super().extract_cover(soup)

    def extract_pages(self, soup: BeautifulSoup) -> List[Dict]:
        pages = []
        imgs = soup.find_all('img', class_=re.compile(r'page|chapter', re.I))
        for i, img in enumerate(imgs):
            if img.get('src'):
                pages.append({
                    'chapter': 1,
                    'page_number': i + 1,
                    'url': urljoin(self.base_url, img['src'])
                })
        return pages


class KeikomikScraper(SiteScraper):
    """Scraper for keikomik.web.id - Indonesian comics."""

    def __init__(self):
        super().__init__("https://keikomik.web.id/", "comic")

    def extract_pages(self, soup: BeautifulSoup) -> List[Dict]:
        pages = []
        imgs = soup.find_all('img', {'data-src': True})
        for i, img in enumerate(imgs):
            src = img.get('data-src') or img.get('src')
            if src and not src.endswith(('.gif', '.svg')):
                pages.append({
                    'chapter': 1,
                    'page_number': i + 1,
                    'url': urljoin(self.base_url, src)
                })
        return pages


class OploverzScraper(SiteScraper):
    """Scraper for oploverz.fans - Indonesian anime/manga."""

    def __init__(self):
        super().__init__("https://oploverz.fans/", "anime")


class MangaPlusScraper(SiteScraper):
    """Scraper for mangaplus.shueisha.co.jp - Official manga platform."""

    def __init__(self):
        super().__init__("https://mangaplus.shueisha.co.jp/", "manga")


class GenericScraper(SiteScraper):
    """Generic scraper for unknown sites."""

    def __init__(self, base_url: str):
        super().__init__(base_url, "other")


# Registry of scrapers
SCRAPER_REGISTRY = {
    "v2.samehadaku.how": SamehadakuScraper,
    "anichin.cafe": AnichinScraper,
    "komiku.org": KomikuScraper,
    "keikomik.web.id": KeikomikScraper,
    "oploverz.fans": OploverzScraper,
    "mangaplus.shueisha.co.jp": MangaPlusScraper,
}


def get_scraper_for_url(url: str) -> SiteScraper:
    """Get appropriate scraper for a URL."""
    domain = urlparse(url).netloc.lower()
    scraper_class = SCRAPER_REGISTRY.get(domain, GenericScraper)
    if scraper_class == GenericScraper:
        return scraper_class(url)
    return scraper_class()
