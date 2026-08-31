"""SQLite repository for the first vertical slice.

The domain layer deliberately does not depend on SQLAlchemy yet. This keeps the
MVP runnable on the current machine while leaving a clean database URL boundary
for the PostgreSQL migration described by the design document.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .models import BuildJob, Chunk, Claim, CrawlJob, Document, Person, PersonReport, Source, SourceCandidate


def slugify(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_]+", "-", value).strip("-").lower()
    return value or "person"


def platform_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
        return "youtube"
    return "web"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, database: str = "data/publicmind.db") -> None:
        self.database = database
        path = self._sqlite_path(database)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    @staticmethod
    def _sqlite_path(database: str) -> str:
        if database.startswith("sqlite:///"):
            return database[len("sqlite:///") :]
        if database.startswith("sqlite://"):
            return database[len("sqlite://") :]
        if "://" in database and not database.startswith("sqlite://"):
            raise ValueError(
                "The dependency-free MVP Repository currently supports SQLite only; "
                "use a sqlite:/// URL or a file path"
            )
        return database

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS persons (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source_role TEXT NOT NULL DEFAULT 'unclassified',
                last_crawled_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(person_id, url)
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                external_id TEXT,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                summary TEXT,
                topics_json TEXT NOT NULL DEFAULT '[]',
                entities_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'completed',
                UNIQUE(source_url, content_hash)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                start_time REAL,
                end_time REAL,
                content TEXT NOT NULL,
                UNIQUE(document_id, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_candidates (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                snippet TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL,
                query TEXT NOT NULL,
                score INTEGER NOT NULL,
                source_role TEXT NOT NULL DEFAULT 'unclassified',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                risks_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(person_id, url)
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                statement TEXT NOT NULL,
                evidence_quote TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                speaker TEXT NOT NULL,
                attribution_confidence TEXT NOT NULL,
                source_role TEXT NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                start_time REAL,
                end_time REAL,
                rationale TEXT,
                review_note TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(document_id, chunk_id, start_char, end_char)
            );
            CREATE TABLE IF NOT EXISTS person_reports (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(person_id)
            );
            CREATE TABLE IF NOT EXISTS build_jobs (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                error TEXT,
                report_id TEXT REFERENCES person_reports(id) ON DELETE SET NULL,
                archive_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        source_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(sources)").fetchall()
        }
        if "source_role" not in source_columns:
            self.connection.execute(
                "ALTER TABLE sources ADD COLUMN source_role TEXT NOT NULL DEFAULT 'unclassified'"
            )
        self.connection.commit()

    def create_person(self, name: str, description: Optional[str] = None) -> Person:
        base_slug = slugify(name)
        slug = base_slug
        counter = 2
        while self.connection.execute("SELECT 1 FROM persons WHERE slug = ?", (slug,)).fetchone():
            slug = "%s-%d" % (base_slug, counter)
            counter += 1
        person = Person(name=name.strip(), slug=slug, id=str(uuid.uuid4()), description=description)
        now = _now()
        self.connection.execute(
            "INSERT INTO persons(id,name,slug,description,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (person.id, person.name, person.slug, person.description, now, now),
        )
        self.connection.commit()
        return person

    def get_person(self, person_id: str) -> Optional[Person]:
        row = self.connection.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
        if not row:
            return None
        return Person(id=row["id"], name=row["name"], slug=row["slug"], description=row["description"])

    def list_persons(self) -> List[Person]:
        rows = self.connection.execute(
            "SELECT * FROM persons ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [
            Person(
                id=row["id"],
                name=row["name"],
                slug=row["slug"],
                description=row["description"],
            )
            for row in rows
        ]

    def add_source(
        self, person_id: str, url: str, source_role: str = "unclassified"
    ) -> Source:
        row = self.connection.execute(
            "SELECT * FROM sources WHERE person_id = ? AND url = ?", (person_id, url)
        ).fetchone()
        if row:
            return Source(
                id=row["id"],
                person_id=row["person_id"],
                url=row["url"],
                platform=row["platform"],
                status=row["status"],
                source_role=row["source_role"],
            )
        source = Source(
            id=str(uuid.uuid4()),
            person_id=person_id,
            url=url,
            platform=platform_for_url(url),
            source_role=source_role,
        )
        self.connection.execute(
            "INSERT INTO sources(id,person_id,platform,url,status,source_role,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                source.id,
                source.person_id,
                source.platform,
                source.url,
                source.status,
                source.source_role,
                _now(),
            ),
        )
        self.connection.commit()
        return source

    def get_source(self, source_id: str) -> Optional[Source]:
        row = self.connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            return None
        return Source(
            id=row["id"],
            person_id=row["person_id"],
            url=row["url"],
            platform=row["platform"],
            status=row["status"],
            source_role=row["source_role"],
        )

    def list_sources(self, person_id: str) -> List[Source]:
        rows = self.connection.execute(
            "SELECT * FROM sources WHERE person_id = ? ORDER BY created_at", (person_id,)
        ).fetchall()
        return [
            Source(
                id=row["id"],
                person_id=row["person_id"],
                url=row["url"],
                platform=row["platform"],
                status=row["status"],
                source_role=row["source_role"],
            )
            for row in rows
        ]

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> SourceCandidate:
        return SourceCandidate(
            id=row["id"],
            person_id=row["person_id"],
            url=row["url"],
            title=row["title"],
            snippet=row["snippet"],
            provider=row["provider"],
            query=row["query"],
            score=int(row["score"]),
            source_role=row["source_role"],
            reasons=json.loads(row["reasons_json"] or "[]"),
            risks=json.loads(row["risks_json"] or "[]"),
            status=row["status"],
            source_id=row["source_id"],
        )

    def upsert_candidate(self, candidate: SourceCandidate) -> SourceCandidate:
        existing = self.connection.execute(
            "SELECT * FROM source_candidates WHERE person_id = ? AND url = ?",
            (candidate.person_id, candidate.url),
        ).fetchone()
        now = _now()
        if existing:
            self.connection.execute(
                """
                UPDATE source_candidates
                SET title=?, snippet=?, provider=?, query=?, score=?, source_role=?,
                    reasons_json=?, risks_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    candidate.title,
                    candidate.snippet,
                    candidate.provider,
                    candidate.query,
                    candidate.score,
                    candidate.source_role,
                    json.dumps(candidate.reasons, ensure_ascii=False),
                    json.dumps(candidate.risks, ensure_ascii=False),
                    now,
                    existing["id"],
                ),
            )
            candidate.id = existing["id"]
            candidate.status = existing["status"]
            candidate.source_id = existing["source_id"]
        else:
            candidate.id = candidate.id or str(uuid.uuid4())
            self.connection.execute(
                """
                INSERT INTO source_candidates(
                    id,person_id,url,title,snippet,provider,query,score,source_role,
                    reasons_json,risks_json,status,source_id,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    candidate.id,
                    candidate.person_id,
                    candidate.url,
                    candidate.title,
                    candidate.snippet,
                    candidate.provider,
                    candidate.query,
                    candidate.score,
                    candidate.source_role,
                    json.dumps(candidate.reasons, ensure_ascii=False),
                    json.dumps(candidate.risks, ensure_ascii=False),
                    candidate.status,
                    candidate.source_id,
                    now,
                    now,
                ),
            )
        self.connection.commit()
        return candidate

    def get_candidate(self, candidate_id: str) -> Optional[SourceCandidate]:
        row = self.connection.execute(
            "SELECT * FROM source_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return self._candidate_from_row(row) if row else None

    def list_candidates(self, person_id: str) -> List[SourceCandidate]:
        rows = self.connection.execute(
            """
            SELECT * FROM source_candidates
            WHERE person_id = ?
            ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END,
                     score DESC, updated_at DESC
            """,
            (person_id,),
        ).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def decide_candidate(self, candidate_id: str, status: str) -> SourceCandidate:
        if status not in {"accepted", "rejected"}:
            raise ValueError("candidate status must be accepted or rejected")
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        source_id = candidate.source_id
        if status == "accepted":
            source = self.add_source(candidate.person_id, candidate.url, candidate.source_role)
            source_id = source.id
        self.connection.execute(
            "UPDATE source_candidates SET status=?, source_id=?, updated_at=? WHERE id=?",
            (status, source_id, _now(), candidate_id),
        )
        self.connection.commit()
        candidate.status = status
        candidate.source_id = source_id
        return candidate

    def update_source_status(self, source_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE sources SET status = ? WHERE id = ?",
            (status, source_id),
        )
        self.connection.commit()

    def save_document(self, document: Document, chunks: List[Chunk]) -> Tuple[bool, str]:
        existing = self.connection.execute(
            "SELECT id FROM documents WHERE source_url = ? AND content_hash = ?",
            (document.source_url, document.content_hash),
        ).fetchone()
        if existing:
            self.connection.execute(
                "UPDATE sources SET status = 'completed', last_crawled_at = ? WHERE id = ?",
                (_now(), document.source_id),
            )
            self.connection.commit()
            return False, existing["id"]
        document_id = document.id or str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO documents(
                id,person_id,source_id,external_id,source_url,source_type,title,author,
                published_at,fetched_at,content,content_hash,metadata_json,summary,
                topics_json,entities_json,status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                document.person_id,
                document.source_id,
                document.external_id,
                document.source_url,
                document.source_type,
                document.title,
                document.author,
                document.published_at,
                document.fetched_at,
                document.content,
                document.content_hash,
                json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
                document.summary,
                json.dumps(document.topics, ensure_ascii=False),
                json.dumps(document.entities, ensure_ascii=False),
                "completed",
            ),
        )
        for chunk in chunks:
            chunk_id = chunk.id or "%s-%04d" % (document_id, chunk.index)
            self.connection.execute(
                """
                INSERT INTO chunks(id,document_id,chunk_index,start_char,end_char,start_time,end_time,content)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    chunk_id,
                    document_id,
                    chunk.index,
                    chunk.start_char,
                    chunk.end_char,
                    chunk.start_time,
                    chunk.end_time,
                    chunk.content,
                ),
            )
        self.connection.execute(
            "UPDATE sources SET status = 'completed', last_crawled_at = ? WHERE id = ?",
            (_now(), document.source_id),
        )
        self.connection.commit()
        return True, document_id

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            person_id=row["person_id"],
            source_id=row["source_id"],
            external_id=row["external_id"],
            source_url=row["source_url"],
            source_type=row["source_type"],
            title=row["title"],
            author=row["author"],
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            content=row["content"],
            content_hash=row["content_hash"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            summary=row["summary"],
            topics=json.loads(row["topics_json"] or "[]"),
            entities=json.loads(row["entities_json"] or "[]"),
        )

    def get_document(self, document_id: str) -> Optional[Document]:
        row = self.connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(self, person_id: str) -> List[Document]:
        rows = self.connection.execute(
            "SELECT * FROM documents WHERE person_id = ? ORDER BY published_at DESC, fetched_at DESC",
            (person_id,),
        ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def list_chunks(self, document_id: str) -> List[Chunk]:
        rows = self.connection.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (document_id,)
        ).fetchall()
        return [
            Chunk(
                id=row["id"],
                document_id=row["document_id"],
                index=row["chunk_index"],
                start_char=row["start_char"],
                end_char=row["end_char"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                content=row["content"],
            )
            for row in rows
        ]

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> Claim:
        return Claim(
            id=row["id"],
            person_id=row["person_id"],
            document_id=row["document_id"],
            source_id=row["source_id"],
            chunk_id=row["chunk_id"],
            statement=row["statement"],
            evidence_quote=row["evidence_quote"],
            claim_type=row["claim_type"],
            speaker=row["speaker"],
            attribution_confidence=row["attribution_confidence"],
            source_role=row["source_role"],
            start_char=row["start_char"],
            end_char=row["end_char"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            rationale=row["rationale"],
            review_note=row["review_note"],
            status=row["status"],
        )

    def save_claims(self, claims: List[Claim]) -> List[Claim]:
        saved: List[Claim] = []
        now = _now()
        for claim in claims:
            existing = self.connection.execute(
                """
                SELECT * FROM claims
                WHERE document_id=? AND chunk_id=? AND start_char=? AND end_char=?
                """,
                (claim.document_id, claim.chunk_id, claim.start_char, claim.end_char),
            ).fetchone()
            if existing:
                saved.append(self._claim_from_row(existing))
                continue
            claim.id = claim.id or str(uuid.uuid4())
            self.connection.execute(
                """
                INSERT INTO claims(
                    id,person_id,document_id,source_id,chunk_id,statement,evidence_quote,
                    claim_type,speaker,attribution_confidence,source_role,start_char,end_char,
                    start_time,end_time,rationale,review_note,status,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    claim.id,
                    claim.person_id,
                    claim.document_id,
                    claim.source_id,
                    claim.chunk_id,
                    claim.statement,
                    claim.evidence_quote,
                    claim.claim_type,
                    claim.speaker,
                    claim.attribution_confidence,
                    claim.source_role,
                    claim.start_char,
                    claim.end_char,
                    claim.start_time,
                    claim.end_time,
                    claim.rationale,
                    claim.review_note,
                    claim.status,
                    now,
                    now,
                ),
            )
            saved.append(claim)
        self.connection.commit()
        return saved

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        row = self.connection.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return self._claim_from_row(row) if row else None

    def list_claims(self, person_id: str, status: Optional[str] = None) -> List[Claim]:
        if status:
            rows = self.connection.execute(
                """
                SELECT * FROM claims WHERE person_id=? AND status=?
                ORDER BY updated_at DESC, document_id, start_char
                """,
                (person_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM claims WHERE person_id=?
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END,
                         updated_at DESC, document_id, start_char
                """,
                (person_id,),
            ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def review_claim(
        self,
        claim_id: str,
        status: str,
        statement: Optional[str] = None,
        claim_type: Optional[str] = None,
        speaker: Optional[str] = None,
        review_note: Optional[str] = None,
    ) -> Claim:
        if status not in {"accepted", "rejected"}:
            raise ValueError("claim status must be accepted or rejected")
        claim = self.get_claim(claim_id)
        if not claim:
            raise KeyError(claim_id)
        next_statement = statement.strip() if statement and statement.strip() else claim.statement
        next_type = claim_type.strip() if claim_type and claim_type.strip() else claim.claim_type
        next_speaker = speaker.strip() if speaker and speaker.strip() else claim.speaker
        self.connection.execute(
            """
            UPDATE claims
            SET status=?, statement=?, claim_type=?, speaker=?, review_note=?, updated_at=?
            WHERE id=?
            """,
            (
                status,
                next_statement,
                next_type,
                next_speaker,
                review_note,
                _now(),
                claim_id,
            ),
        )
        self.connection.commit()
        reviewed = self.get_claim(claim_id)
        if not reviewed:  # pragma: no cover - guarded by the existing row
            raise KeyError(claim_id)
        return reviewed

    def save_report(self, person_id: str, content: Dict[str, Any]) -> PersonReport:
        row = self.connection.execute(
            "SELECT id FROM person_reports WHERE person_id = ?", (person_id,)
        ).fetchone()
        now = _now()
        report_id = row["id"] if row else str(uuid.uuid4())
        if row:
            self.connection.execute(
                "UPDATE person_reports SET content_json=?, updated_at=? WHERE id=?",
                (json.dumps(content, ensure_ascii=False), now, report_id),
            )
        else:
            self.connection.execute(
                "INSERT INTO person_reports(id,person_id,content_json,created_at,updated_at) VALUES (?,?,?,?,?)",
                (report_id, person_id, json.dumps(content, ensure_ascii=False), now, now),
            )
        self.connection.commit()
        return PersonReport(id=report_id, person_id=person_id, content=content)

    def get_report(self, person_id: str) -> Optional[PersonReport]:
        row = self.connection.execute(
            "SELECT * FROM person_reports WHERE person_id = ?", (person_id,)
        ).fetchone()
        if not row:
            return None
        return PersonReport(
            id=row["id"], person_id=row["person_id"], content=json.loads(row["content_json"])
        )

    def create_build_job(self, person_id: str) -> BuildJob:
        job = BuildJob(person_id=person_id, id=str(uuid.uuid4()))
        now = _now()
        self.connection.execute(
            """
            INSERT INTO build_jobs(id,person_id,status,stage,progress,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (job.id, person_id, job.status, job.stage, job.progress, now, now),
        )
        self.connection.commit()
        return job

    def update_build_job(
        self,
        job_id: str,
        status: str,
        stage: str,
        progress: float,
        error: Optional[str] = None,
        report_id: Optional[str] = None,
        archive_path: Optional[str] = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE build_jobs
            SET status=?,stage=?,progress=?,error=?,report_id=COALESCE(?,report_id),
                archive_path=COALESCE(?,archive_path),updated_at=?
            WHERE id=?
            """,
            (status, stage, progress, error, report_id, archive_path, _now(), job_id),
        )
        self.connection.commit()

    def get_build_job(self, job_id: str) -> Optional[BuildJob]:
        row = self.connection.execute("SELECT * FROM build_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        return BuildJob(
            id=row["id"],
            person_id=row["person_id"],
            status=row["status"],
            stage=row["stage"],
            progress=row["progress"],
            error=row["error"],
            report_id=row["report_id"],
            archive_path=row["archive_path"],
        )

    def create_job(self, person_id: str, source_id: str) -> CrawlJob:
        job = CrawlJob(person_id=person_id, source_id=source_id, id=str(uuid.uuid4()))
        now = _now()
        self.connection.execute(
            "INSERT INTO crawl_jobs(id,person_id,source_id,status,progress,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (job.id, person_id, source_id, job.status, job.progress, now, now),
        )
        self.connection.commit()
        return job

    def update_job(
        self,
        job_id: str,
        status: str,
        progress: float,
        error: Optional[str] = None,
    ) -> None:
        self.connection.execute(
            "UPDATE crawl_jobs SET status=?, progress=?, error=?, updated_at=? WHERE id=?",
            (status, progress, error, _now(), job_id),
        )
        self.connection.commit()

    def get_job(self, job_id: str) -> Optional[CrawlJob]:
        row = self.connection.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return CrawlJob(
            id=row["id"],
            person_id=row["person_id"],
            source_id=row["source_id"],
            status=row["status"],
            progress=row["progress"],
            error=row["error"],
        )
