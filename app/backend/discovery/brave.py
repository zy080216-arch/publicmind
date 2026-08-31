"""Adapter for the official Brave Search API."""

from __future__ import annotations

import os
from typing import List, Optional

import httpx

from .base import SearchHit, SearchProviderError


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")
        self.timeout = timeout

    def search(self, query: str, count: int = 10) -> List[SearchHit]:
        if not self.api_key:
            raise SearchProviderError(
                "自动检索尚未配置：请在本机环境设置 BRAVE_SEARCH_API_KEY 后重启服务。"
            )
        try:
            response = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(max(count, 1), 20), "safesearch": "moderate"},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("搜索服务暂时不可用：%s" % exc) from exc

        hits: List[SearchHit] = []
        for item in payload.get("web", {}).get("results", []):
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title", "")).strip(),
                    snippet=str(item.get("description", "")).strip(),
                    published_at=item.get("page_age"),
                )
            )
        return hits
