"""Source plugin interface. One source = one Python module under sloane/sources/.

A source is anything that produces CanonicalEntity rows: an HTML scraper, an
RSS feed, an API, a calendar. Adding a data type (weather, astronomy) later =
drop a new module + register it in the registry. No core code changes.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator

from shared.schema_contract import CanonicalEntity


class BaseSource(ABC):
    """Contract every source plugin implements."""

    # stable slug, used as `source` field on emitted entities
    slug: str = ""
    # entity kind this source produces (anime/manga/movie/...)
    kind: str = ""

    @abstractmethod
    def fetch(self) -> Iterator[CanonicalEntity]:
        """Yield canonical entities. Called by the pipeline; must validate each."""
        raise NotImplementedError


def register(cls: type[BaseSource]) -> type[BaseSource]:
    """Decorator: register a source class in the global registry by its slug."""
    from sloane.sources.registry import REGISTRY
    if not cls.slug:
        raise ValueError(f"{cls.__name__} missing slug")
    REGISTRY[cls.slug] = cls
    return cls
