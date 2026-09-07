"""Public, attributable person imagery from Wikipedia and Wikimedia Commons."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def _identity_match(person_name: str, value: str) -> bool:
    expected = _normalized(person_name)
    actual = _normalized(value)
    if not expected or not actual:
        return False
    if expected == actual or expected in actual:
        return True
    return len(expected) >= 6 and SequenceMatcher(None, expected, actual).ratio() >= 0.86


def _html_metadata(markup: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for match in re.finditer(r"<meta\b([^>]+)>", markup, flags=re.I):
        pairs = dict(
            (key.lower(), html.unescape(value).strip())
            for key, value in re.findall(
                r"([:\w-]+)\s*=\s*['\"]([^'\"]*)['\"]", match.group(1), flags=re.I
            )
        )
        key = pairs.get("property") or pairs.get("name")
        if key and pairs.get("content"):
            values[key.casefold()] = pairs["content"]
    return values


def _youtube_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0] or None
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return None
    value = parse_qs(parsed.query).get("v", [None])[0]
    if value:
        return value
    match = re.search(r"/(?:shorts|embed|live)/([^/?#]+)", parsed.path)
    return match.group(1) if match else None


class WikimediaImageProvider:
    """Find a Wikipedia lead image plus a small Commons portrait set."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.headers = {"User-Agent": "PublicMind/0.1 (local research tool)"}

    @staticmethod
    def _reference_page(
        person_name: str, reference_urls: List[str]
    ) -> Optional[tuple[str, str, str]]:
        for url in reference_urls:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if not host.endswith(".wikipedia.org") or "/wiki/" not in parsed.path:
                continue
            language = host.split(".", 1)[0]
            title = unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ")
            if title and _identity_match(person_name, title):
                return language, title, url
        return None

    def _lead_image(self, person_name: str, reference_urls: List[str]) -> List[Dict[str, str]]:
        page = self._reference_page(person_name, reference_urls)
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

    def _commons_images(self, person_name: str, query: str, limit: int) -> List[Dict[str, str]]:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": '"%s" portrait' % query,
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
            if not _identity_match(person_name, "%s %s" % (title, caption)):
                continue
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

    @staticmethod
    def _github_image(person_name: str, url: str) -> Optional[Dict[str, str]]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        parts = [part for part in parsed.path.split("/") if part]
        if host != "github.com" or len(parts) != 1:
            return None
        handle = parts[0]
        if handle.casefold() in {"about", "features", "marketplace", "topics"}:
            return None
        return {
            "url": "https://github.com/%s.png?size=1200" % handle,
            "full_url": "https://github.com/%s.png?size=1200" % handle,
            "caption": "%s 的 GitHub 头像" % person_name,
            "source_url": url,
            "source_label": "GitHub",
            "author": handle,
            "license": "来自公开个人主页",
        }

    @staticmethod
    def _youtube_image(person_name: str, url: str) -> Optional[Dict[str, str]]:
        video_id = _youtube_id(url)
        if not video_id:
            return None
        return {
            "url": "https://i.ytimg.com/vi/%s/hqdefault.jpg" % video_id,
            "full_url": "https://i.ytimg.com/vi/%s/maxresdefault.jpg" % video_id,
            "caption": "%s 的访谈视频封面" % person_name,
            "source_url": url,
            "source_label": "YouTube",
            "author": "",
            "license": "查看视频原页面",
        }

    def _open_graph_image(self, person_name: str, url: str) -> Optional[Dict[str, str]]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if (
            host.endswith(".wikipedia.org")
            or host in {
                "x.com",
                "twitter.com",
                "github.com",
                "youtube.com",
                "m.youtube.com",
                "music.youtube.com",
                "youtu.be",
            }
        ):
            return None
        response = httpx.get(
            url,
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        metadata = _html_metadata(response.text[:1_500_000])
        page_title = metadata.get("og:title") or metadata.get("twitter:title") or ""
        if not _identity_match(person_name, page_title):
            return None
        image_url = metadata.get("og:image") or metadata.get("twitter:image") or ""
        image_url = urljoin(str(response.url), image_url.strip())
        if not image_url:
            return None
        lowered = image_url.casefold()
        if any(marker in lowered for marker in ("logo", "favicon", "icon", "sprite")):
            return None
        return {
            "url": image_url,
            "full_url": image_url,
            "caption": page_title[:240] or "%s 的公开影像" % person_name,
            "source_url": url,
            "source_label": host or "公开网页",
            "author": "",
            "license": "查看原页面许可",
        }

    def _source_images(
        self, person_name: str, reference_urls: List[str], limit: int
    ) -> List[Dict[str, str]]:
        images: List[Dict[str, str]] = []
        for url in reference_urls[:12]:
            item = self._github_image(person_name, url) or self._youtube_image(person_name, url)
            if item:
                images.append(item)
                if len(images) >= limit:
                    return images
        # Two direct profile/interview images are preferable to filling the grid
        # with generic article cards, publication logos, or social-share artwork.
        if len(images) >= 2:
            return images
        for url in reference_urls[:8]:
            try:
                item = self._open_graph_image(person_name, url)
            except (httpx.HTTPError, ValueError, TypeError):
                continue
            if item:
                images.append(item)
                if len(images) >= limit:
                    break
        return images

    def discover(
        self, person_name: str, reference_urls: List[str], limit: int = 4
    ) -> List[Dict[str, str]]:
        limit = min(max(int(limit), 1), 6)
        images: List[Dict[str, str]] = []
        try:
            images.extend(self._lead_image(person_name, reference_urls))
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        images.extend(self._source_images(person_name, reference_urls, limit + 2))
        page = self._reference_page(person_name, reference_urls)
        # Commons keyword search is only safe after a matching Wikipedia identity
        # page has established the subject. A nickname alone can otherwise return
        # unrelated people or objects with the same word in their title.
        if page:
            try:
                images.extend(self._commons_images(person_name, page[1], limit + 2))
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
