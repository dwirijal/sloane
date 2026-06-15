"""
Storage module: PostgreSQL operations with deduplication.
"""
from typing import Optional, List, Dict, Any

import asyncpg


class Storage:
    """Database operations wrapper with deduplication logic."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_or_create_source(self, url: str) -> int:
        """Get or create a source record, returns ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM sources WHERE url = $1", url)
            if row:
                return row['id']
            row = await conn.fetchrow(
                "INSERT INTO sources (url) VALUES ($1) ON CONFLICT (url) DO NOTHING RETURNING id",
                url,
            ) or await conn.fetchrow("SELECT id FROM sources WHERE url = $1", url)
            return row['id']

    async def upsert_content(
        self,
        title: str,
        source_url: str,
        content_type: str = "other",
        description: str = None,
        cover_url: str = None,
        episode_count: int = None,
        chapter_count: int = None,
        status: str = None,
        genres: str = None,
        year: int = None,
        rating: float = None,
    ) -> int:
        """Upsert content; returns content ID. Dedup on (title, source_id)."""
        source_id = await self.get_or_create_source(source_url)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO contents (title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (title, source_id) DO UPDATE
                    SET description = COALESCE(EXCLUDED.description, contents.description),
                        cover_url   = COALESCE(EXCLUDED.cover_url, contents.cover_url),
                        episode_count = COALESCE(EXCLUDED.episode_count, contents.episode_count),
                        chapter_count = COALESCE(EXCLUDED.chapter_count, contents.chapter_count),
                        status = COALESCE(EXCLUDED.status, contents.status),
                        genres = COALESCE(EXCLUDED.genres, contents.genres),
                        year = COALESCE(EXCLUDED.year, contents.year),
                        rating = COALESCE(EXCLUDED.rating, contents.rating),
                        scraped_at = NOW(),
                        last_scraped_at = NOW()
                RETURNING id
                """,
                title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating,
            )
            return row['id']

    async def insert_stream(self, content_id: int, episode: int, url: str, quality: str = None) -> None:
        """Insert stream URL; ignore duplicate."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO streams (content_id, episode, url, quality)
                   VALUES ($1, $2, $3, $4) ON CONFLICT (content_id, episode, url) DO NOTHING""",
                content_id, episode, url, quality,
            )

    async def insert_download(self, content_id: int, episode: int, url: str, label: str = None) -> None:
        """Insert download URL; ignore duplicate."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO downloads (content_id, episode, url, label)
                   VALUES ($1, $2, $3, $4) ON CONFLICT (content_id, episode, url) DO NOTHING""",
                content_id, episode, url, label,
            )

    async def insert_page(self, content_id: int, chapter: int, page_number: int, url: str) -> None:
        """Insert page URL; ignore duplicate."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO pages (content_id, chapter, page_number, url)
                   VALUES ($1, $2, $3, $4) ON CONFLICT (content_id, chapter, page_number, url) DO NOTHING""",
                content_id, chapter, page_number, url,
            )

    async def insert_image(self, content_id: int, url: str, image_type: str = "cover") -> None:
        """Insert image URL; ignore duplicate."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO images (content_id, url, image_type)
                   VALUES ($1, $2, $3) ON CONFLICT (content_id, url) DO NOTHING""",
                content_id, url, image_type,
            )

    async def stats(self) -> Dict[str, int]:
        """Return database statistics."""
        async with self.pool.acquire() as conn:
            sources = await conn.fetchval("SELECT count(*) FROM sources")
            contents = await conn.fetchval("SELECT count(*) FROM contents")
            streams = await conn.fetchval("SELECT count(*) FROM streams")
            downloads = await conn.fetchval("SELECT count(*) FROM downloads")
            pages = await conn.fetchval("SELECT count(*) FROM pages")
            images = await conn.fetchval("SELECT count(*) FROM images")
            return {
                "sources": sources,
                "contents": contents,
                "streams": streams,
                "downloads": downloads,
                "pages": pages,
                "images": images,
            }