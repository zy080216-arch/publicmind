"""Search-backed, explainable source discovery."""

from .base import SearchHit, SearchProvider, SearchProviderError
from .academic import AcademicIndexProvider
from .brave import BraveSearchProvider
from .openalex import OpenAlexAcademicProvider
from .service import DiscoveryService
from .wikipedia import WikipediaSearchProvider

__all__ = [
    "BraveSearchProvider",
    "AcademicIndexProvider",
    "DiscoveryService",
    "OpenAlexAcademicProvider",
    "SearchHit",
    "SearchProvider",
    "SearchProviderError",
    "WikipediaSearchProvider",
]
