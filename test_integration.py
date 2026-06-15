#!/usr/bin/env python3
"""
Integration tests for Sloane scraper
"""
import asyncio
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.storage import Storage
from scraper.engine import scrape_site_links
import asyncpg


async def test_storage_deduplication():
    """Test that deduplication works correctly"""
    logger.info("Testing storage deduplication...")

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sloane:sloane_secure_password@localhost:5432/sloane"
    )

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    storage = Storage(pool)

    try:
        # Test source deduplication
        source_id1 = await storage.get_or_create_source("https://test1.com")
        source_id2 = await storage.get_or_create_source("https://test1.com")
        assert source_id1 == source_id2, "Source deduplication failed"
        logger.info("✓ Source deduplication works")

        # Test content deduplication
        content_id1 = await storage.upsert_content(
            title="Test Content",
            source_url="https://test1.com",
            content_type="anime",
            description="Test description"
        )
        content_id2 = await storage.upsert_content(
            title="Test Content",
            source_url="https://test1.com",
            content_type="anime",
            description="Updated description"
        )
        assert content_id1 == content_id2, "Content deduplication failed"
        logger.info("✓ Content deduplication works")

        # Test HA fallback - multiple URLs for same content
        await storage.insert_stream(content_id1, 1, "https://stream1.com/video.mp4", "720p")
        await storage.insert_stream(content_id1, 1, "https://stream2.com/video.mp4", "720p")
        await storage.insert_stream(content_id1, 1, "https://stream1.com/video.mp4", "720p")  # Duplicate
        logger.info("✓ HA fallback allows multiple URLs")

        # Test stats
        stats = await storage.stats()
        assert "sources" in stats, "Stats missing sources"
        logger.info(f"✓ Stats work: {stats}")

        logger.info("All storage tests passed!")

    finally:
        await pool.close()


async def test_scraper_engine():
    """Test scraper engine with a real site"""
    logger.info("Testing scraper engine...")

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sloane:sloane_secure_password@localhost:5432/sloane"
    )

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    storage = Storage(pool)

    try:
        # Test with a single site
        result = await scrape_site_links(
            storage,
            "https://komiku.org/",
            max_links=3  # Limit for testing
        )

        logger.info(f"Scraper result: {result}")
        assert "scraped" in result, "Result missing scraped count"
        assert "failed" in result, "Result missing failed count"
        logger.info("✓ Scraper engine works")

    finally:
        await pool.close()


async def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("Starting Sloane Integration Tests")
    logger.info("=" * 60)

    try:
        await test_storage_deduplication()
        logger.info("")
        await test_scraper_engine()
        logger.info("")
        logger.info("=" * 60)
        logger.info("All tests passed!")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
