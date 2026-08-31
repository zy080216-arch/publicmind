"""Provider-neutral structured generation contract."""

from __future__ import annotations

from typing import Any, Dict, Protocol


class LLMProviderError(RuntimeError):
    """Raised when the configured model cannot produce a usable response."""


class LLMProvider(Protocol):
    name: str

    def generate_json(self, system: str, prompt: str) -> Dict[str, Any]:
        ...
