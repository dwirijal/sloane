"""Source package. Importing registers all source plugins."""
from sloane.sources import stub, oploverz  # noqa: F401  (side-effect: register)

__all__ = ["stub", "oploverz"]
