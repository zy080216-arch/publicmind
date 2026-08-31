"""Provider-neutral search contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


class SearchProviderError(RuntimeError):
    """Raised when a configured search provider cannot return results."""


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    published_at: Optional[str] = None


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, count: int = 10) -> List[SearchHit]:
        ...
