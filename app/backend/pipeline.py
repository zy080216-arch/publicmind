"""End-to-end ingestion orchestration for one source URL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from .claims import ClaimExtractor
from .connectors import ConnectorRegistry, WebConnector, YoutubeConnector
from .markdown import VaultExporter
from .models import Document, Person, Source
from .normalization import build_chunks, normalize_raw_document
from .store import Repository


@dataclass
class IngestResult:
    source: Source
    document: Optional[Document]
    inserted: bool
    document_id: str
    claim_candidates: int = 0


class IngestPipeline:
    def __init__(self, repository: Repository, registry: Optional[ConnectorRegistry] = None) -> None:
        self.repository = repository
        self.registry = registry or ConnectorRegistry([YoutubeConnector(), WebConnector()])

    async def ingest(self, person_id: str, url: str) -> IngestResult:
        source = self.repository.add_source(person_id, url)
        connector = self.registry.resolve(url)
        raw = await connector.fetch(url)
        document = normalize_raw_document(raw, person_id, source.id or "")
        chunks = build_chunks(document)
        inserted, document_id = self.repository.save_document(document, chunks)
        stored = self.repository.get_document(document_id)
        claim_candidates = 0
        if inserted and stored:
            person = self.repository.get_person(person_id)
            if person:
                stored_chunks = self.repository.list_chunks(document_id)
                proposals = ClaimExtractor().propose(person, source, stored, stored_chunks)
                claim_candidates = len(self.repository.save_claims(proposals))
        return IngestResult(
            source=source,
            document=stored,
            inserted=inserted,
            document_id=document_id,
            claim_candidates=claim_candidates,
        )

    def export(self, person_id: str, output_dir: str = "data/exports"):
        person = self.repository.get_person(person_id)
        if not person:
            raise ValueError("Person not found: %s" % person_id)
        report = self.repository.get_report(person_id)
        return VaultExporter(output_dir).export(
            person,
            self.repository.list_documents(person_id),
            self.repository.list_claims(person_id, "accepted"),
            report.content if report else None,
        )


def ingest_sync(pipeline: IngestPipeline, person_id: str, url: str) -> IngestResult:
    return asyncio.run(pipeline.ingest(person_id, url))
