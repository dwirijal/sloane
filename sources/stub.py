"""Stub source for smoke-testing the pipeline without network/anti-bot deps.

Emits a small, deterministic, valid set of CanonicalEntity rows so the
end-to-end pipeline (fetch -> validate -> dedup -> write PG -> assert) can be
proven 24/7-ready before wiring real scrapers. Real scrapers (oploverz,
samehadaku, ...) are added later by the agent squad as separate plugins.
"""
from __future__ import annotations
from collections.abc import Iterator

from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.sources.base import BaseSource, register


@register
class StubAnimeSource(BaseSource):
    """Deterministic anime stub. Smoke-only — do not ship to prod."""

    slug = "stub-anime"
    kind = KIND_ANIME

    def fetch(self) -> Iterator[CanonicalEntity]:
        rows = [
            ("one-piece", "One Piece", "https://example.test/anime/one-piece",
             {"episodes": 1128, "status": "ongoing"}),
            ("naruto", "Naruto", "https://example.test/anime/naruto",
             {"episodes": 220, "status": "completed"}),
            ("bleach", "Bleach", "https://example.test/anime/bleach",
             {"episodes": 366, "status": "completed"}),
        ]
        for ext_id, title, url, payload in rows:
            yield CanonicalEntity(
                source=self.slug, external_id=ext_id, kind=self.kind,
                title=title, url=url, payload=payload,
            )
