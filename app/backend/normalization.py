"""Turn raw connector output into deterministic documents and chunks."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import List

from .connectors.youtube import transcript_markdown
from .models import Chunk, Document, RawDocument


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    output = []  # type: List[str]
    blank = False
    for line in lines:
        if not line:
            if not blank:
                output.append("")
            blank = True
        else:
            output.append(line)
            blank = False
    return "\n".join(output).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def normalize_raw_document(raw: RawDocument, person_id: str, source_id: str) -> Document:
    if raw.transcript_segments:
        content = transcript_markdown(raw.transcript_segments)
    else:
        content = raw.raw_text or ""
    content = normalize_text(content)
    if not content:
        raise ValueError("Cannot normalize an empty source document")
    title = normalize_text(raw.title or raw.source_url) or raw.source_url
    fetched_at = datetime.now(timezone.utc).isoformat()
    return Document(
        person_id=person_id,
        source_id=source_id,
        source_url=raw.source_url,
        source_type=raw.source_type,
        title=title,
        author=raw.author,
        published_at=raw.published_at,
        fetched_at=fetched_at,
        content=content,
        content_hash=content_hash(content),
        metadata=raw.metadata,
        external_id=raw.metadata.get("video_id") or raw.source_url,
    )


def build_chunks(document: Document, max_chars: int = 1800) -> List[Chunk]:
    """Chunk by timestamped transcript segments or paragraphs, retaining offsets."""
    if document.source_type == "video":
        blocks = []  # type: List[tuple]
        for match in re.finditer(
            r"###\s+(\d{2}:\d{2}(?::\d{2})?)\n(.+?)(?=\n###\s+|\Z)",
            document.content,
            flags=re.S,
        ):
            stamp, text = match.group(1), normalize_text(match.group(2))
            if not text:
                continue
            parts = stamp.split(":")
            seconds = float(parts[-1]) + float(parts[-2]) * 60
            if len(parts) == 3:
                seconds += float(parts[0]) * 3600
            blocks.append((match.start(), match.end(), text, seconds, seconds))
    else:
        blocks = []  # type: List[tuple]
        for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", document.content):
            text = normalize_text(match.group(0))
            if text:
                blocks.append((match.start(), match.end(), text, None, None))

    chunks = []  # type: List[Chunk]
    pending = []  # type: List[tuple]
    pending_chars = 0

    def flush() -> None:
        nonlocal pending, pending_chars
        if not pending:
            return
        first = pending[0]
        last = pending[-1]
        content = "\n\n".join(item[2] for item in pending)
        chunks.append(
            Chunk(
                document_id=document.id or document.content_hash,
                index=len(chunks),
                content=content,
                start_char=first[0],
                end_char=last[1],
                start_time=first[3],
                end_time=last[4],
            )
        )
        pending = []
        pending_chars = 0

    for block in blocks:
        block_len = len(block[2])
        if pending and pending_chars + block_len > max_chars:
            flush()
        pending.append(block)
        pending_chars += block_len
    flush()
    return chunks

