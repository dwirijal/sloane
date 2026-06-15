"""
StealthyFetcher - Cloudflare bypass using curl_cffi
Implements browser fingerprint impersonation to bypass bot detection
"""
import asyncio
import logging
from typing import Optional
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Browser impersonation targets (Supported by curl_cffi)
BROWSER_TARGETS = [
    "chrome120",
    "chrome124",
    "safari17_0",
    "firefox133",
]

# Common user agents for fallback
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


async def fetch_html_stealthy(
    url: str,
    retries: int = 3,
    timeout: float = 30.0,
) -> Optional[str]:
    """
    Fetch HTML content with Cloudflare bypass using curl_cffi.

    Args:
        url: Target URL to fetch
        retries: Number of retry attempts (default: 3)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        HTML content as string, or None if all attempts fail
    """
    for attempt in range(retries):
        try:
            # Rotate browser impersonation target
            browser_target = BROWSER_TARGETS[attempt % len(BROWSER_TARGETS)]

            logger.info(f"Attempt {attempt + 1}/{retries} with {browser_target} for {url}")

            # Use curl_cffi with browser impersonation
            response = curl_requests.get(
                url,
                impersonate=browser_target,
                timeout=timeout,
                allow_redirects=True,  # curl_cffi uses allow_redirects, not follow_redirects
                verify=True,  # Always verify SSL certificates for security
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                }
            )

            # Check for Cloudflare challenge page
            if "challenge-platform" in response.text or "cf-browser-verification" in response.text:
                logger.warning(f"Cloudflare challenge detected for {url}, attempt {attempt + 1}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue

            response.raise_for_status()
            logger.info(f"Successfully fetched {url} with {browser_target}")
            return response.text

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                # Exponential backoff: 1s, 2s, 4s, etc.
                await asyncio.sleep(2 ** attempt)

    logger.error(f"All {retries} attempts failed for {url}")
    return None


async def fetch_html_with_fallback(
    url: str,
    retries: int = 3,
    timeout: float = 30.0,
) -> Optional[str]:
    """
    Fetch HTML with automatic fallback from StealthyFetcher to regular httpx.

    This is useful when some URLs don't need Cloudflare bypass but others do.

    Args:
        url: Target URL to fetch
        retries: Number of retry attempts (default: 3)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        HTML content as string, or None if all attempts fail
    """
    # Try StealthyFetcher first
    html = await fetch_html_stealthy(url, retries, timeout)
    if html:
        return html

    # Fallback to regular httpx if stealthy fetch fails
    logger.info(f"Falling back to regular httpx for {url}")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        logger.error(f"Fallback fetch also failed for {url}: {e}")
        return None
