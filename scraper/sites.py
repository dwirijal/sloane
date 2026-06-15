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

    def extract_year(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract release year. Override per site."""
        return None

    def extract_rating(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract rating (0-10). Override per site."""
        return None

    def extract_genres(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract comma-separated genres. Override per site."""
        return None

    def extract_status(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract status (ongoing/completed). Override per site."""
        return None


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
    """Scraper for keikomik.web.id - Indonesian comics.

    NOTE: This site uses client-side rendering (Next.js). Static HTML scraping
    with httpx will only return "Loading..." placeholders. Requires Playwright
    or similar headless browser for proper extraction.
    """

    def __init__(self):
        super().__init__("https://keikomik.web.id/", "comic")

    def extract_pages(self, soup: BeautifulSoup) -> List[Dict]:
        # Static scraping won't work for this site
        import logging
        logging.warning("Keikomik requires JavaScript rendering - skipping static extraction")
        return []


class OploverzScraper(SiteScraper):
    """Scraper for oploverz.fans - Indonesian anime/manga."""

    def __init__(self):
        super().__init__("https://oploverz.fans/", "anime")
        self.title_strip_patterns = [
            r'\s*[-–]\s*oploverz\.best\s*\|\s*Situs\s*Oploverz\s*yang\s*asli$',
            r'^oploverz\.best\s*\|\s*Situs\s*Oploverz\s*yang\s*asli\s*[-–]\s*',
        ]

    def clean_title(self, title: str) -> str:
        """Strip common site suffixes, but preserve navigation page titles."""
        if 'List Mode - oploverz.best' in title:
            return title
        for pattern in self.title_strip_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()
        return title.strip(' –-— ')


class OtakuDesuScraper(SiteScraper):
    """Scraper for otakudesu.blog - Indonesian anime streaming."""

    def __init__(self):
        super().__init__("https://otakudesu.blog/", "anime")

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract title, stripping 'Sub Indo' suffix."""
        title = super().extract_title(soup)
        # Remove common "Sub Indo" suffixes
        title = re.sub(r'\s*Sub\s*Indo.*$', '', title, flags=re.IGNORECASE)
        return title.strip()


class MangaPlusScraper(SiteScraper):
    """Scraper for mangaplus.shueisha.co.jp - Official manga platform."""

    def __init__(self):
        super().__init__("https://mangaplus.shueisha.co.jp/", "manga")


class AnimasuScraper(SiteScraper):
    """Scraper for animasu.care - Indonesian anime streaming."""

    def __init__(self):
        super().__init__("https://animasu.care/", "anime")


class KanzeninScraper(SiteScraper):
    """Scraper for kanzenin.info - Indonesian manga/comic platform."""

    def __init__(self):
        super().__init__("https://kanzenin.info/", "manga")


class BridgesScraper(SiteScraper):
    """Scraper for bridgestoabrighterfuture.org - Indonesian movie streaming."""

    def __init__(self):
        super().__init__("https://bridgestoabrighterfuture.org/", "movie")

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract title from movie detail page or card structure."""
        # First try: h1.entry-title (movie detail page)
        h1 = soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_title(h1.get_text(strip=True))

        # Second try: <a> tag with title attribute (movie list cards)
        link = soup.find('a', attrs={'title': True})
        if link and link.get('title'):
            title = link.get('title')
            # Remove "Permalink ke: " prefix if present
            title = re.sub(r'^Permalink ke:\s*', '', title, flags=re.IGNORECASE)
            return self.clean_title(title)

        # Fallback to parent class method
        return super().extract_title(soup)

    def extract_year(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract release year from movie detail page."""
        # Look for year in the main content area, not the whole page
        content = soup.find('div', class_=re.compile(r'gmr-content|entry-content|post-content', re.I))
        if not content:
            content = soup  # Fallback to whole page

        text = content.get_text()
        # Look for patterns like "2025" in the content area
        matches = re.findall(r'\b(20\d{2})\b', text)
        if matches:
            # Return the most recent year (likely the release year)
            return max(int(y) for y in matches if int(y) >= 2000)
        return None

    def extract_rating(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract rating from movie detail page."""
        rating_div = soup.find('div', class_='gmr-rating-item')
        if rating_div:
            text = rating_div.get_text()
            matches = re.findall(r'\b(\d{1,2}\.\d+)\b', text)
            if matches:
                rating = float(matches[0])
                # Clamp to 0-10 range
                return min(10.0, max(0.0, rating))
        return None

    def extract_genres(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract genres if available in meta tags or card."""
        # Check for genre in meta tags
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return meta_keywords['content']
        return None

    def extract_status(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract movie status (usually 'completed' for movies)."""
        # Movies are typically completed, not ongoing
        return 'completed'


class KusonimeScraper(SiteScraper):
    """Scraper for kusonime.com - Indonesian anime download site."""

    def __init__(self):
        super().__init__("https://kusonime.com/", "anime")


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
    "otakudesu.blog": OtakuDesuScraper,
    "animasu.care": AnimasuScraper,
    "kanzenin.info": KanzeninScraper,
    "bridgestoabrighterfuture.org": BridgesScraper,
    "kusonime.com": KusonimeScraper,
    "mangaplus.shueisha.co.jp": MangaPlusScraper,
}


def get_scraper_for_url(url: str) -> SiteScraper:
    """Get appropriate scraper for a URL."""
    domain = urlparse(url).netloc.lower()
    scraper_class = SCRAPER_REGISTRY.get(domain, GenericScraper)
    if scraper_class == GenericScraper:
        return scraper_class(url)
    return scraper_class()
