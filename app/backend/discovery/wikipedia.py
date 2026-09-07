"""Keyless identity baseline from Wikipedia's official read-only API."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Optional
from urllib.parse import quote

import httpx

from .base import SearchHit


class WikipediaSearchProvider:
    name = "wikipedia"

    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout

    @staticmethod
    def _is_identity_match(query: str, title: str) -> bool:
        def normalized(value: str) -> str:
            value = unicodedata.normalize("NFKD", value).casefold()
            return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)

        expected = normalized(query)
        actual = normalized(title)
        if not expected or not actual:
            return False
        if expected == actual or expected in actual:
            return True
        # Allow small spelling mistakes such as "rafa nadel" while rejecting
        # unrelated autocomplete results such as "Tibo" -> "Time".
        return len(expected) >= 6 and SequenceMatcher(None, expected, actual).ratio() >= 0.86

    def _search_language(self, language: str, query: str) -> List[SearchHit]:
        endpoint = "https://%s.wikipedia.org/w/api.php" % language
        current = query
        for _ in range(3):
            response = httpx.get(
                endpoint,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": current,
                    "srlimit": 5,
                    "format": "json",
                    "utf8": 1,
                },
                headers={"User-Agent": "PublicMind/0.1 (local research tool)"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json().get("query", {})
            results = payload.get("search", [])
            suggestion: Optional[str] = payload.get("searchinfo", {}).get("suggestion")
            if suggestion and suggestion.casefold() != current.casefold():
                if not self._is_identity_match(current, suggestion):
                    return []
                current = suggestion
                continue
            hits: List[SearchHit] = []
            for item in results:
                title = str(item.get("title", "")).strip()
                if not title or not self._is_identity_match(current, title):
                    continue
                snippet = html.unescape(re.sub(r"<[^>]+>", "", str(item.get("snippet", ""))))
                hits.append(
                    SearchHit(
                        url="https://%s.wikipedia.org/wiki/%s"
                        % (language, quote(title.replace(" ", "_"), safe="_()")),
                        title="%s — Wikipedia" % title,
                        snippet=snippet.strip(),
                        published_at=item.get("timestamp"),
                    )
                )
                break
            return hits
        return []

    def search(self, query: str, count: int = 10) -> List[SearchHit]:
        languages = ["zh", "en"] if re.search(r"[\u3400-\u9fff]", query) else ["en", "zh"]
        hits: List[SearchHit] = []
        seen = set()
        for language in languages:
            try:
                language_hits = self._search_language(language, query)
            except (httpx.HTTPError, ValueError, TypeError):
                continue
            for hit in language_hits:
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                hits.append(hit)
                if len(hits) >= min(max(count, 1), 4):
                    return hits
        return hits
