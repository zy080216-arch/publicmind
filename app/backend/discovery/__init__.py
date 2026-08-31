"""Search-backed, explainable source discovery."""

from .base import SearchHit, SearchProvider, SearchProviderError
from .brave import BraveSearchProvider
from .service import DiscoveryService
from .wikipedia import WikipediaSearchProvider

__all__ = [
    "BraveSearchProvider",
    "DiscoveryService",
    "SearchHit",
    "SearchProvider",
    "SearchProviderError",
    "WikipediaSearchProvider",
]
