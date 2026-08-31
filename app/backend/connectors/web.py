"""Web article connector with a useful standard-library fallback."""

from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..models import RawDocument
from .base import ConnectorError, SourceConnector


_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "ul",
}
_IGNORED_TAGS = {"aside", "canvas", "footer", "form", "nav", "noscript", "script", "style", "svg"}


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class _HTMLToMarkdownParser(HTMLParser):
    """Conservative HTML-to-Markdown fallback for article-shaped pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines = []  # type: list[str]
        self.current = []  # type: list[str]
        self.title_parts = []  # type: list[str]
        self._title_depth = 0
        self._ignored_depth = 0
        self._pre_depth = 0
        self._list_depth = 0
        self._pending_list_marker = False

    def _flush(self) -> None:
        text = "".join(self.current)
        self.current = []
        if self._pre_depth:
            text = text.rstrip("\n")
        else:
            text = _clean_space(text)
        if text:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        tag = tag.lower()
        if tag == "title":
            self._title_depth += 1
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "pre":
            self._flush()
            self._pre_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self.current.append("%s " % ("#" * int(tag[1])))
            elif tag == "li":
                self.current.append("- ")
        if tag in {"ul", "ol"}:
            self._list_depth += 1

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
            self._flush()
        elif tag in _BLOCK_TAGS or tag in {"ul", "ol"}:
            self._flush()
            if tag in {"ul", "ol"} and self._list_depth:
                self._list_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
            return
        self.current.append(data)

    def finish(self) -> Tuple[str, str]:
        self._flush()
        output = []  # type: list[str]
        previous_blank = False
        for line in self.lines:
            if not line:
                if not previous_blank:
                    output.append("")
                previous_blank = True
            else:
                output.append(line)
                previous_blank = False
        return _clean_space(" ".join(self.title_parts)), "\n\n".join(
            line for line in output if line
        ).strip()


def _meta_values(html: str) -> Dict[str, str]:
    values = {}  # type: Dict[str, str]
    for match in re.finditer(r"<meta\b([^>]+)>", html, flags=re.I):
        attrs = match.group(1)
        pairs = dict(
            (key.lower(), value)
            for key, value in re.findall(
                r"([:\w-]+)\s*=\s*['\"]([^'\"]*)['\"]", attrs, flags=re.I
            )
        )
        key = pairs.get("property") or pairs.get("name")
        content = pairs.get("content")
        if key and content:
            values[key.lower()] = content.strip()
    return values


def _extract_published_at(html: str, metadata: Dict[str, str]) -> Optional[str]:
    for key in (
        "article:published_time",
        "og:published_time",
        "datepublished",
        "date",
        "pubdate",
    ):
        if metadata.get(key):
            return metadata[key]
    match = re.search(r"<time\b[^>]*datetime=['\"]([^'\"]+)['\"]", html, flags=re.I)
    return match.group(1).strip() if match else None


def _extract_with_trafilatura(html: str, url: str) -> Optional[Tuple[str, str, Dict[str, str]]]:
    """Use the optional extractor when installed; return None otherwise."""
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return None
    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            include_links=True,
            include_formatting=True,
            output_format="markdown",
        )
    except Exception:
        return None
    if not extracted:
        return None
    metadata = {}
    try:
        info = trafilatura.extract_metadata(html)
        if info:
            if getattr(info, "title", None):
                metadata["title"] = info.title
            if getattr(info, "author", None):
                metadata["author"] = info.author
            if getattr(info, "date", None):
                metadata["date"] = info.date
            if getattr(info, "description", None):
                metadata["description"] = info.description
    except Exception:
        pass
    return metadata.get("title", ""), extracted.strip(), metadata


def html_to_markdown(html: str, url: str = "") -> Tuple[str, str, Dict[str, str]]:
    """Extract title, Markdown-ish article text and metadata from HTML."""
    advanced = _extract_with_trafilatura(html, url)
    if advanced:
        title, text, extracted_metadata = advanced
        metadata = _meta_values(html)
        metadata.update(extracted_metadata)
        return title or metadata.get("og:title", ""), text, metadata

    parser = _HTMLToMarkdownParser()
    parser.feed(html)
    title, text = parser.finish()
    metadata = _meta_values(html)
    title = title or metadata.get("og:title", "") or metadata.get("twitter:title", "")
    return title, text, metadata


class WebConnector(SourceConnector):
    platform = "web"

    def __init__(
        self,
        timeout: int = 20,
        user_agent: str = "PublicMind/0.1 (+https://github.com/publicmind)",
        opener: Optional[Callable[[str, int], Tuple[bytes, Dict[str, str], str]]] = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self._opener = opener or self._open

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _open(url: str, timeout: int) -> Tuple[bytes, Dict[str, str], str]:
        request = Request(
            url,
            headers={
                "User-Agent": "PublicMind/0.1",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310 - user supplied public URL
                body = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return body, headers, response.geturl()
        except Exception as exc:
            raise ConnectorError("Failed to fetch %s: %s" % (url, exc)) from exc

    def _fetch_sync(self, url: str) -> RawDocument:
        body, headers, final_url = self._opener(url, self.timeout)
        charset = "utf-8"
        content_type = headers.get("content-type", "")
        match = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
        if match:
            charset = match.group(1)
        try:
            html = body.decode(charset, errors="replace")
        except LookupError:
            html = body.decode("utf-8", errors="replace")
        title, text, metadata = html_to_markdown(html, final_url)
        parsed = urlparse(final_url)
        title = title or parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.netloc
        if not text:
            raise ConnectorError("No readable article text found at %s" % url)
        author = metadata.get("author") or metadata.get("article:author")
        return RawDocument(
            source_url=final_url,
            source_type="article",
            title=title,
            author=author,
            published_at=_extract_published_at(html, metadata),
            raw_text=text,
            raw_html=html,
            metadata={
                "content_type": content_type,
                "requested_url": url,
                "final_url": final_url,
                "description": metadata.get("description") or metadata.get("og:description"),
            },
        )

    async def fetch(self, url: str) -> RawDocument:
        return await asyncio.to_thread(self._fetch_sync, url)
