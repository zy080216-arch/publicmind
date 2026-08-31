"""Public, attributable person imagery from Wikipedia and Wikimedia Commons."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import unquote, urlparse

import httpx


class ImageProvider(Protocol):
    def discover(
        self, person_name: str, reference_urls: List[str], limit: int = 4
    ) -> List[Dict[str, str]]:
        ...


def _plain(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _metadata_value(metadata: Dict[str, Any], key: str) -> str:
    item = metadata.get(key, {})
    return _plain(item.get("value", "")) if isinstance(item, dict) else ""


class WikimediaImageProvider:
    """Find a Wikipedia lead image plus a small Commons portrait set."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.headers = {"User-Agent": "PublicMind/0.1 (local research tool)"}

    @staticmethod
    def _reference_page(reference_urls: List[str]) -> Optional[tuple[str, str, str]]:
        for url in reference_urls:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if not host.endswith(".wikipedia.org") or "/wiki/" not in parsed.path:
                continue
            language = host.split(".", 1)[0]
            title = unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ")
            if title:
                return language, title, url
        return None

    def _lead_image(self, reference_urls: List[str]) -> List[Dict[str, str]]:
        page = self._reference_page(reference_urls)
        if not page:
            return []
        language, title, page_url = page
        response = httpx.get(
            "https://%s.wikipedia.org/w/api.php" % language,
            params={
                "action": "query",
                "prop": "pageimages",
                "piprop": "thumbnail|original|name",
                "pithumbsize": 1400,
                "titles": title,
                "format": "json",
                "formatversion": 2,
            },
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
        if not pages:
            return []
        item = pages[0]
        original = item.get("original", {})
        thumbnail = item.get("thumbnail", {})
        image_url = str(thumbnail.get("source") or original.get("source") or "").strip()
        if not image_url:
            return []
        return [
            {
                "url": image_url,
                "full_url": str(original.get("source") or image_url),
                "caption": "%s 的 Wikipedia 主图" % title,
                "source_url": page_url,
                "source_label": "Wikipedia",
                "author": "",
                "license": "查看原页面许可",
            }
        ]

    def _commons_images(self, query: str, limit: int) -> List[Dict[str, str]]:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": min(max(limit * 4, 8), 24),
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": 1400,
                "format": "json",
                "formatversion": 2,
            },
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        results: List[Dict[str, str]] = []
        for page in response.json().get("query", {}).get("pages", []):
            title = str(page.get("title", ""))
            info_items = page.get("imageinfo", [])
            if not info_items:
                continue
            info = info_items[0]
            mime = str(info.get("mime", ""))
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            metadata = info.get("extmetadata", {}) if isinstance(info.get("extmetadata"), dict) else {}
            description_url = str(info.get("descriptionurl") or "").strip()
            thumb_url = str(info.get("thumburl") or info.get("url") or "").strip()
            if not thumb_url or not description_url:
                continue
            caption = (
                _metadata_value(metadata, "ImageDescription")
                or title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " ")
            )
            results.append(
                {
                    "url": thumb_url,
                    "full_url": str(info.get("url") or thumb_url),
                    "caption": caption[:240],
                    "source_url": description_url,
                    "source_label": "Wikimedia Commons",
                    "author": _metadata_value(metadata, "Artist")[:160],
                    "license": (
                        _metadata_value(metadata, "LicenseShortName")
                        or _metadata_value(metadata, "UsageTerms")
                        or "查看原页面许可"
                    )[:100],
                }
            )
            if len(results) >= limit:
                break
        return results

    def discover(
        self, person_name: str, reference_urls: List[str], limit: int = 4
    ) -> List[Dict[str, str]]:
        limit = min(max(int(limit), 1), 6)
        images: List[Dict[str, str]] = []
        try:
            images.extend(self._lead_image(reference_urls))
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        page = self._reference_page(reference_urls)
        query = page[1] if page else person_name
        try:
            images.extend(self._commons_images(query, limit + 2))
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        deduplicated: List[Dict[str, str]] = []
        seen = set()
        for item in images:
            key = item.get("full_url") or item.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            deduplicated.append(item)
            if len(deduplicated) >= limit:
                break
        return deduplicated
