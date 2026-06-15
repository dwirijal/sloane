"""
Sloane Scraper Engine
Reusable scraping engine using httpx and BeautifulSoup.
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .sites import get_scraper_for_url, SiteScraper
from .storage import Storage

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    retries: int = 3,
) -> Optional[str]:
    """Fetch HTML content with retry and timeout."""
    for attempt in range(retries):
        try:
            response = await client.get(url, headers=HEADERS, timeout=30.0)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1 * (attempt + 1))  # backoff
    logger.error(f"All {retries} attempts failed for {url}")
    return None


async def scrape_batch(
    storage: Storage,
    site_url: str,
    paths: List[str],
    concurrency: int = 3,
) -> Dict[str, Any]:
    """Scrape a batch of pages from one site."""
    scraper = get_scraper_for_url(site_url)
    results = {"scraped": 0, "failed": 0, "errors": []}

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, limits=httpx.Limits(max_keepalive_connections=10)
    ) as client:
        async def scrape_one(path: str) -> Optional[bool]:
            async with sem:
                url = urljoin(site_url, path)
                html = await fetch_html(client, url)
                if not html:
                    results["failed"] += 1
                    results["errors"].append(url)
                    return None

                soup = BeautifulSoup(html, 'lxml')
                try:
                    # Extract metadata
                    title = scraper.extract_title(soup)
                    if not title:
                        results["failed"] += 1
                        return None

                    # Skip non-content pages (navigation, utilities, etc.)
                    skip_titles = {'search', 'history', 'list', 'home', 'bookmark', 'schedule',
                                   'login', 'register', 'about', 'contact', 'privacy', 'dmca',
                                   'completed', 'ongoing', 'networks', 'countries', 'years', 'genres',
                                   'bookmarks', 'settings', 'profile', 'rss', 'feed', 'sitemap',
                                   'index', 'archive', 'categories', 'tags', 'authors'}
                    if title.strip().lower() in skip_titles:
                        logger.info(f"Skipping non-content page: {title} ({url})")
                        results["failed"] += 1
                        return None

                    content_type = scraper.content_type
                    cover = scraper.extract_cover(soup)
                    description = None
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    if meta_desc and meta_desc.get("content"):
                        description = meta_desc["content"].strip()

                    # Store content (deduplication handled by ON CONFLICT)
                    content_id = await storage.upsert_content(
                        title=title,
                        source_url=site_url,
                        content_type=content_type,
                        description=description,
                        cover_url=cover,
                    )

                    # Store streams/downloads/pages
                    for s in scraper.extract_streams(soup):
                        await storage.insert_stream(
                            content_id, s.get("episode", 1), s["url"], s.get("quality")
                        )
                    for d in scraper.extract_downloads(soup):
                        await storage.insert_download(
                            content_id, d.get("episode", 1), d["url"], d.get("label")
                        )
                    for p in scraper.extract_pages(soup):
                        await storage.insert_page(
                            content_id, p.get("chapter", 1), p["page_number"], p["url"]
                        )
                    if cover:
                        await storage.insert_image(content_id, cover, "cover")

                    results["scraped"] += 1
                    return True

                except Exception as e:
                    logger.error(f"Error parsing {url}: {e}")
                    results["failed"] += 1
                    results["errors"].append(url)
                    return None

        tasks = [scrape_one(path) for path in paths]
        await asyncio.gather(*tasks)

    return results


async def scrape_site_links(
    storage: Storage,
    site_url: str,
    max_links: int = 20,
) -> Dict[str, Any]:
    """Scrape site homepage to discover links, then scrape each linked page."""
    scraper = get_scraper_for_url(site_url)
    sem = asyncio.Semaphore(3)

    # Skip non-content paths
    SKIP_PATTERNS = [
        '#', 'javascript:', '/about', '/contact', '/dmca', '/privacy',
        '/schedule', '/bookmark', '/login', '/register', '/genre/',
        '/tag/', '/category/', '/page/', '/feed', '/xmlrpc',
        '/wp-admin', '/wp-login', '/wp-content/plugins',
    ]

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        html = await fetch_html(client, site_url)
        if not html:
            return {"scraped": 0, "failed": 1, "errors": [site_url]}

        soup = BeautifulSoup(html, 'lxml')

        # Discover content links from homepage
        paths = []
        seen_paths = set()
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()

            # Skip non-content links
            if any(href.lower().startswith(p) or href.lower() == p.rstrip('/') for p in SKIP_PATTERNS):
                continue

            # Normalize relative URLs
            full_url = urljoin(site_url, href)
            # Only scrape paths under same domain
            parsed_site = urlparse(site_url)
            parsed_full = urlparse(full_url)
            if parsed_full.netloc != parsed_site.netloc:
                continue
            if href not in seen_paths and full_url != site_url and full_url != site_url.rstrip('/') + '/':
                seen_paths.add(href)
                path = full_url.replace(site_url, "/")
                # Only keep paths that look like content (deep enough, not just root)
                if path != '/' and path != '':
                    paths.append(path)

        logger.info(f"Discovered {len(paths)} content links on {site_url}")

        # Limit to max_links
        paths = paths[:max_links]

        return await scrape_batch(storage, site_url, paths, concurrency=3)