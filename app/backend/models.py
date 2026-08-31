"""Small, dependency-free domain models used by the first MVP slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class RawDocument:
    source_url: str
    source_type: str
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    raw_text: Optional[str] = None
    raw_html: Optional[str] = None
    transcript_segments: List[TranscriptSegment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    person_id: str
    source_id: str
    source_url: str
    source_type: str
    title: str
    author: Optional[str]
    published_at: Optional[str]
    fetched_at: str
    content: str
    content_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    external_id: Optional[str] = None
    summary: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)


@dataclass
class Chunk:
    document_id: str
    index: int
    content: str
    start_char: int
    end_char: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    id: Optional[str] = None


@dataclass
class Person:
    name: str
    slug: str
    id: Optional[str] = None
    description: Optional[str] = None


@dataclass
class Source:
    person_id: str
    url: str
    platform: str
    id: Optional[str] = None
    status: str = "pending"
    source_role: str = "unclassified"


@dataclass
class SourceCandidate:
    person_id: str
    url: str
    title: str
    snippet: str
    provider: str
    query: str
    score: int
    source_role: str
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    id: Optional[str] = None
    status: str = "pending"
    source_id: Optional[str] = None


@dataclass
class CrawlJob:
    person_id: str
    source_id: str
    status: str = "queued"
    progress: float = 0.0
    id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Claim:
    person_id: str
    document_id: str
    source_id: str
    chunk_id: str
    statement: str
    evidence_quote: str
    claim_type: str
    speaker: str
    attribution_confidence: str
    source_role: str
    start_char: int
    end_char: int
    id: Optional[str] = None
    status: str = "pending"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    rationale: Optional[str] = None
    review_note: Optional[str] = None


@dataclass
class BuildJob:
    person_id: str
    status: str = "queued"
    stage: str = "准备开始"
    progress: float = 0.0
    id: Optional[str] = None
    error: Optional[str] = None
    report_id: Optional[str] = None
    archive_path: Optional[str] = None


@dataclass
class PersonReport:
    person_id: str
    content: Dict[str, Any]
    id: Optional[str] = None
