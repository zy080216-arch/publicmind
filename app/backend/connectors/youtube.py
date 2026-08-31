"""YouTube connector: metadata plus official/automatic subtitle transcript."""

from __future__ import annotations

import asyncio
import json
import re
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from ..models import RawDocument, TranscriptSegment
from .base import ConnectorError, SourceConnector


_VTT_TIME = re.compile(
    r"(?:(?P<hours>\d{1,2}):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})[\.,](?P<millis>\d{3})"
)
_SHORT_VTT_TIME = re.compile(r"(?P<minutes>\d{1,3}):(?P<seconds>\d{2})[\.,](?P<millis>\d{3})")


def _time_to_seconds(value: str) -> float:
    value = value.strip()
    match = _VTT_TIME.search(value) or _SHORT_VTT_TIME.search(value)
    if not match:
        raise ValueError("Invalid subtitle timestamp: %s" % value)
    parts = match.groupdict()
    hours = float(parts.get("hours") or 0)
    minutes = float(parts["minutes"])
    seconds = float(parts["seconds"])
    millis = float(parts["millis"])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _strip_caption_markup(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _json3_segments(payload: Dict[str, Any]) -> List[TranscriptSegment]:
    segments = []  # type: List[TranscriptSegment]
    for event in payload.get("events", []):
        if not event.get("segs"):
            continue
        text = "".join(str(part.get("utf8", "")) for part in event["segs"])
        text = _strip_caption_markup(text)
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000
        duration = float(event.get("dDurationMs", 0)) / 1000
        segments.append(TranscriptSegment(start=start, end=start + duration, text=text))
    return segments


def parse_subtitle(text: str, extension: str = "vtt") -> List[TranscriptSegment]:
    """Parse VTT/SRT or YouTube JSON3 captions into timestamped segments."""
    stripped = text.lstrip("\ufeff \n\r\t")
    if extension.lower() in {"json", "json3"} or stripped.startswith("{"):
        try:
            return _json3_segments(json.loads(stripped))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ConnectorError("Could not parse JSON3 subtitles: %s" % exc) from exc

    lines = stripped.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments = []  # type: List[TranscriptSegment]
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, right = [part.strip().split(" ", 1)[0] for part in line.split("-->", 1)]
        try:
            start = _time_to_seconds(left)
            end = _time_to_seconds(right)
        except ValueError:
            index += 1
            continue
        index += 1
        caption_lines = []  # type: List[str]
        while index < len(lines) and lines[index].strip():
            caption_lines.append(lines[index].strip())
            index += 1
        caption = _strip_caption_markup(" ".join(caption_lines))
        if caption:
            # Automatic captions may repeat the tail of the previous cue.
            if segments and segments[-1].text == caption:
                continue
            segments.append(TranscriptSegment(start=start, end=end, text=caption))
        index += 1
    return segments


def transcript_markdown(segments: Iterable[TranscriptSegment]) -> str:
    lines = ["## Transcript", ""]
    for segment in segments:
        total_seconds = max(0, int(segment.start))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        stamp = "%02d:%02d:%02d" % (hours, minutes, seconds) if hours else "%02d:%02d" % (minutes, seconds)
        lines.extend(["### %s" % stamp, segment.text, ""])
    return "\n".join(lines).strip()


def _youtube_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"/(?:shorts|embed|live)/([^/?#]+)", parsed.path)
    return match.group(1) if match else None


def _youtube_date(value: Optional[str]) -> Optional[str]:
    if value and re.fullmatch(r"\d{8}", value):
        return "%s-%s-%s" % (value[:4], value[4:6], value[6:])
    return value


class YoutubeConnector(SourceConnector):
    platform = "youtube"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }

    @staticmethod
    def _subtitle_entries(info: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
        for container_name in ("subtitles", "automatic_captions"):
            container = info.get(container_name) or {}
            for language, entries in container.items():
                for entry in entries or []:
                    yield language, entry

    def _fetch_sync(self, url: str) -> RawDocument:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise ConnectorError(
                "YouTube support needs the optional dependency yt-dlp; install with "
                "python3 -m pip install -e '.[youtube]'"
            ) from exc

        options = {"quiet": True, "no_warnings": True, "skip_download": True, "writesubtitles": False}
        try:
            with yt_dlp.YoutubeDL(options) as client:
                info = client.extract_info(url, download=False)
        except Exception as exc:
            raise ConnectorError("Failed to fetch YouTube metadata: %s" % exc) from exc

        segments = []  # type: List[TranscriptSegment]
        selected_language = None
        for language, entry in self._subtitle_entries(info):
            subtitle_url = entry.get("url")
            if not subtitle_url:
                continue
            try:
                with urlopen(subtitle_url, timeout=self.timeout) as response:  # nosec B310 - provider URL
                    subtitle_text = response.read().decode("utf-8", errors="replace")
                segments = parse_subtitle(subtitle_text, entry.get("ext", "vtt"))
            except Exception:
                continue
            if segments:
                selected_language = language
                break

        if not segments:
            raise ConnectorError(
                "No YouTube subtitles were available; audio download/ASR is not enabled in this slice"
            )
        video_id = info.get("id") or _youtube_id(url)
        return RawDocument(
            source_url=info.get("webpage_url") or url,
            source_type="video",
            title=info.get("title") or video_id or "YouTube video",
            author=info.get("uploader") or info.get("channel"),
            published_at=_youtube_date(info.get("upload_date")),
            raw_text=transcript_markdown(segments),
            transcript_segments=segments,
            metadata={
                "video_id": video_id,
                "channel": info.get("channel"),
                "duration": info.get("duration"),
                "subtitle_language": selected_language,
                "subtitle_source": "official" if info.get("subtitles") else "automatic",
            },
        )

    async def fetch(self, url: str) -> RawDocument:
        return await asyncio.to_thread(self._fetch_sync, url)
