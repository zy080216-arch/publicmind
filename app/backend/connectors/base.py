"""Connector contract and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List

from ..models import RawDocument


class ConnectorError(RuntimeError):
    """A source could not be fetched or parsed."""


class SourceConnector(ABC):
    """Every platform adapter exposes the same small asynchronous interface."""

    platform = "unknown"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return whether this connector owns the URL."""

    @abstractmethod
    async def fetch(self, url: str) -> RawDocument:
        """Fetch one source and return raw, source-labelled content."""

    async def discover(self, profile_url: str) -> List[str]:
        """Discovery is intentionally opt-in; MVP connectors do not need it."""
        return []


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[SourceConnector] = ()) -> None:
        self._connectors = list(connectors)

    def register(self, connector: SourceConnector) -> None:
        self._connectors.append(connector)

    def resolve(self, url: str) -> SourceConnector:
        for connector in self._connectors:
            if connector.can_handle(url):
                return connector
        raise ConnectorError("No connector can handle this URL: %s" % url)

    @property
    def connectors(self) -> List[SourceConnector]:
        return list(self._connectors)

