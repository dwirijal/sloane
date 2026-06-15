#!/usr/bin/env python3
"""
Backfill script for Sloane scraper
Rate-limited parallel scraping to avoid system overload
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import List

import asyncpg

from scraper.engine import scrape_site_links
from scraper.storage import Storage

log_dir = os.environ.get('LOG_DIR', '/app/logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'{log_dir}/backfill.log')
    ]
)
logger = logging.getLogger(__name__)

TARGET_SITES = [
    "https://v2.samehadaku.how/",
    "https://anichin.cafe/",
    "https://komiku.org/",
    "https://keikomik.web.id/",
    "https://oploverz.fans/",
    "https://mangaplus.shueisha.co.jp",
    "http://168.144.97.24/",
    "http://139.59.196.140/",
]


async def backfill_site(storage: Storage, site_url: str, max_links: int = 20) -> dict:
    """Backfill a single site with rate limiting"""
    start_time = datetime.now()
    logger.info(f"Starting backfill for {site_url}")

    try:
        result = await scrape_site_links(storage, site_url, max_links=max_links)
        duration = (datetime.now() - start_time).total_seconds()

        logger.info(
            f"Completed {site_url}: "
            f"scraped={result['scraped']}, "
            f"failed={result['failed']}, "
            f"duration={duration:.1f}s"
        )

        return {
            "site": site_url,
            "scraped": result["scraped"],
            "failed": result["failed"],
            "duration": duration,
            "status": "success"
        }

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Failed {site_url}: {str(e)}")

        return {
            "site": site_url,
            "error": str(e),
            "duration": duration,
            "status": "error"
        }


async def backfill_all(
    storage: Storage,
    max_concurrent: int = 3,
    delay_between_sites: float = 2.0,
    max_links_per_site: int = 20
) -> List[dict]:
    """
    Backfill all sites with controlled concurrency and rate limiting

    Args:
        storage: Database storage instance
        max_concurrent: Max simultaneous site scrapes (default 3 for 2GB system)
        delay_between_sites: Seconds to wait between site batches
        max_links_per_site: Max pages to scrape per site
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async def limited_backfill(site_url: str):
        async with semaphore:
            result = await backfill_site(storage, site_url, max_links=max_links_per_site)
            results.append(result)
            await asyncio.sleep(delay_between_sites)

    tasks = [limited_backfill(site) for site in TARGET_SITES]
    await asyncio.gather(*tasks)

    return results


async def main():
    """Main entry point"""
    # Get config from environment
    max_concurrent = int(os.getenv("BACKFILL_CONCURRENCY", "3"))
    delay = float(os.getenv("BACKFILL_DELAY", "2.0"))
    max_links = int(os.getenv("BACKFILL_MAX_LINKS", "20"))

    logger.info(
        f"Starting backfill: "
        f"concurrency={max_concurrent}, "
        f"delay={delay}s, "
        f"max_links={max_links}"
    )

    # Connect to database
    database_url = os.getenv("DATABASE_URL", "postgresql://sloane:sloane_secure_password@localhost:5432/sloane")

    try:
        pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )

        storage = Storage(pool)

        start_time = datetime.now()
        results = await backfill_all(
            storage,
            max_concurrent=max_concurrent,
            delay_between_sites=delay,
            max_links_per_site=max_links
        )
        duration = (datetime.now() - start_time).total_seconds()

        # Summary
        successful = [r for r in results if r["status"] == "success"]
        failed = [r for r in results if r["status"] == "error"]
        total_scraped = sum(r["scraped"] for r in successful)
        total_failed = sum(r["failed"] for r in successful)

        logger.info(
            f"Backfill complete: "
            f"successful={len(successful)}/{len(results)}, "
            f"total_scraped={total_scraped}, "
            f"total_failed={total_failed}, "
            f"duration={duration:.1f}s"
        )

        if failed:
            logger.warning(f"Failed sites: {[r['site'] for r in failed]}")

        await pool.close()

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
