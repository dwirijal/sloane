"""Source package. Importing this registers all source plugins."""
from sloane.sources import stub  # noqa: F401  (side-effect: registers slug)

__all__ = ["stub"]
