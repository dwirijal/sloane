"""Canonical data contract for sloane output.

sloane is source-agnostic: it ingests any data type (anime, manga, movie,
weather, astronomy, time, ...) and emits a normalized envelope. avicenna
(the data hub) consumes this envelope and re-shapes per consumer (jawatch,
etc.). Schema is consumer-driven: sloane adapts to what avicenna asks for.

The envelope is intentionally minimal + extensible via `kind` + `payload`.
One row = one canonical entity. Dedup by (source, external_id).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

# Entity kinds sloane knows today. Extensible — add as new products need data.
KIND_ANIME = "anime"
KIND_MANGA = "manga"
KIND_MOVIE = "movie"
KIND_SERIES = "series"
KIND_COMIC = "comic"
KIND_NOVEL = "novel"
KNOWN_KINDS = {KIND_ANIME, KIND_MANGA, KIND_MOVIE, KIND_SERIES, KIND_COMIC, KIND_NOVEL}


@dataclass(frozen=True)
class CanonicalEntity:
    """One normalized record emitted by a source plugin.

    source:        slug identifying the scraper (e.g. "oploverz")
    external_id:   id as seen at the source (stable across rescrape)
    kind:          entity kind (anime/manga/movie/...)
    title:         display title (non-empty)
    url:           canonical source URL
    payload:       kind-specific structured fields (episodes, chapters, ...)
    """

    source: str
    external_id: str
    kind: str
    title: str
    url: str
    payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Trust-boundary validation. Raises on malformed entity."""
        if not self.source or not self.external_id:
            raise ValueError(f"missing identity: source={self.source!r} external_id={self.external_id!r}")
        if self.kind not in KNOWN_KINDS:
            raise ValueError(f"unknown kind={self.kind!r} (known: {KNOWN_KINDS})")
        if not self.title or not self.title.strip():
            raise ValueError(f"empty title for {self.source}:{self.external_id}")
        if not self.url:
            raise ValueError(f"empty url for {self.source}:{self.external_id}")

    def dedup_key(self) -> tuple[str, str]:
        return (self.source, self.external_id)
