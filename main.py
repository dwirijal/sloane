#!/usr/bin/env python3
"""
Sloane Scraper CLI
Entry point for running the scraper engine.
"""
import asyncio
import os
import logging
from typing import List

import asyncpg

from scraper.engine import scrape_site_links
from scraper.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Target sites to scrape
TARGET_SITES = [
    "https://v2.samehadaku.how/",
    "https://anichin.cafe/",
    "https://komiku.org/",
    "https://keikomik.web.id/",
    "https://oploverz.fans/",
    "https://mangaplus.shueisha.co.jp",
    "http://168.144.97.24/",
    "https://139.59.196.140/",
    "http://154.203.167.63/",
    "https://otakudesu.blog/",
]


async def main():
    """Main entry point."""
    # Database connection
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sloane:sloane_secure_password@localhost:5432/sloane"
    )

    logger.info("Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
    storage = Storage(pool)

    try:
        logger.info(f"Starting scraper for {len(TARGET_SITES)} sites")
        total_scraped = 0
        total_failed = 0

        for site_url in TARGET_SITES:
            logger.info(f"Scraping {site_url}...")
            try:
                result = await scrape_site_links(storage, site_url, max_links=15)
                total_scraped += result["scraped"]
                total_failed += result["failed"]
                logger.info(
                    f"✓ {site_url}: scraped={result['scraped']}, failed={result['failed']}"
                )
            except Exception as e:
                logger.error(f"✗ {site_url}: {e}")
                total_failed += 1

        # Print stats
        stats = await storage.stats()
        logger.info("=" * 60)
        logger.info("Scraping completed!")
        logger.info(f"Total scraped: {total_scraped}")
        logger.info(f"Total failed: {total_failed}")
        logger.info("Database stats:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
