"""Thin FastAPI adapter over the dependency-free repository and pipeline."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .claims import ClaimExtractor
from .connectors import ConnectorRegistry
from .discovery import (
    BraveSearchProvider,
    DiscoveryService,
    SearchProvider,
    SearchProviderError,
    WikipediaSearchProvider,
)
from .intelligence import (
    KnowledgeAnswerer,
    LLMProvider,
    LLMProviderError,
    OpenAICompatibleProvider,
    ProfileBuilder,
    fallback_research_queries,
)
from .markdown import VaultExporter
from .media import ImageProvider, WikimediaImageProvider
from .models import Claim, SourceCandidate
from .pipeline import IngestPipeline
from .settings import configuration_status, load_local_settings, save_local_settings, settings_path
from .store import Repository

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:  # pragma: no cover - exercised only when the optional API deps are absent
    BackgroundTasks = Any  # type: ignore
    FastAPI = None  # type: ignore
    HTTPException = RuntimeError  # type: ignore
    FileResponse = None  # type: ignore
    StaticFiles = None  # type: ignore


SOURCE_ROLES = {
    "subject_official",
    "subject_interview",
    "media_report",
    "third_party_commentary",
    "aggregator_repost",
    "unclassified",
}

CLAIM_TYPES = {
    "subject_claim_candidate",
    "external_evaluation",
    "media_description",
    "cross_source_synthesis",
    "contradiction_or_evolution",
    "insufficient_evidence",
    "unverified_attribution",
}


def _public_platform(url: str, source_role: str = "unclassified") -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host.endswith(".wikipedia.org"):
        return "Wikipedia"
    if host in {"x.com", "twitter.com"}:
        return "X"
    if host == "github.com":
        return "GitHub"
    if host in {"youtube.com", "youtu.be"}:
        return "YouTube"
    if host == "bilibili.com":
        return "Bilibili"
    if host == "zhihu.com":
        return "知乎"
    if host == "weibo.com":
        return "微博"
    if host == "xiaohongshu.com":
        return "小红书"
    if host == "mp.weixin.qq.com":
        return "微信公众号"
    if host == "channels.weixin.qq.com":
        return "视频号"
    if host == "baike.baidu.com":
        return "百度百科"
    if host == "baidu.com" or host.endswith(".baidu.com"):
        return "百度"
    if host == "douyin.com" or host.endswith(".douyin.com"):
        return "抖音"
    if host == "linkedin.com":
        return "LinkedIn"
    if source_role == "subject_official":
        return "官网 / 博客"
    return "公开资料"


def _is_reference_source(candidate: SourceCandidate) -> bool:
    host = (urlparse(candidate.url).hostname or "").lower().removeprefix("www.")
    return candidate.provider == "wikipedia" or host.endswith(".wikipedia.org")


def _platform_links(candidates: List[SourceCandidate]) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen = set()
    preferred = sorted(
        candidates,
        key=lambda item: (
            0 if item.source_role == "subject_official" else 1,
            -item.score,
        ),
    )
    for candidate in preferred:
        platform = _public_platform(candidate.url, candidate.source_role)
        if platform == "公开资料" or platform in seen:
            continue
        seen.add(platform)
        links.append({"platform": platform, "title": candidate.title, "url": candidate.url})
    return links


def _primary_identity_source(candidates: List[SourceCandidate]) -> Optional[SourceCandidate]:
    if not candidates:
        return None
    platform_priority = {
        "X": 0,
        "官网 / 博客": 1,
        "GitHub": 2,
        "YouTube": 3,
        "LinkedIn": 4,
        "知乎": 5,
        "微博": 6,
        "Bilibili": 7,
        "公开资料": 8,
    }
    return min(
        candidates,
        key=lambda item: (
            0 if item.source_role == "subject_official" else 1,
            0 if _is_reference_source(item) else 1,
            platform_priority.get(_public_platform(item.url, item.source_role), 9),
            -item.score,
        ),
    )


def _candidate_payload(candidate: SourceCandidate) -> Dict[str, Any]:
    return {
        "id": candidate.id,
        "person_id": candidate.person_id,
        "url": candidate.url,
        "title": candidate.title,
        "snippet": candidate.snippet,
        "provider": candidate.provider,
        "query": candidate.query,
        "score": candidate.score,
        "source_role": candidate.source_role,
        "reasons": candidate.reasons,
        "risks": candidate.risks,
        "status": candidate.status,
        "source_id": candidate.source_id,
        "review_band": "preselected"
        if candidate.score >= 85
        else "review"
        if candidate.score >= 65
        else "low_confidence",
    }


def _claim_payload(claim: Claim, repository: Repository) -> Dict[str, Any]:
    document = repository.get_document(claim.document_id)
    return {
        "id": claim.id,
        "person_id": claim.person_id,
        "document_id": claim.document_id,
        "source_id": claim.source_id,
        "chunk_id": claim.chunk_id,
        "statement": claim.statement,
        "evidence_quote": claim.evidence_quote,
        "claim_type": claim.claim_type,
        "speaker": claim.speaker,
        "attribution_confidence": claim.attribution_confidence,
        "source_role": claim.source_role,
        "start_char": claim.start_char,
        "end_char": claim.end_char,
        "start_time": claim.start_time,
        "end_time": claim.end_time,
        "rationale": claim.rationale,
        "review_note": claim.review_note,
        "status": claim.status,
        "document_title": document.title if document else "来源文档",
        "source_url": document.source_url if document else None,
        "published_at": document.published_at if document else None,
    }


def create_app(
    database: Optional[str] = None,
    export_dir: Optional[str] = None,
    search_provider: Optional[SearchProvider] = None,
    reference_provider: Optional[SearchProvider] = None,
    llm_provider: Optional[LLMProvider] = None,
    image_provider: Optional[ImageProvider] = None,
    connector_registry: Optional[ConnectorRegistry] = None,
):
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI is not installed. Install the runtime dependencies with "
            "python3 -m pip install -e ."
        )
    db = database or os.getenv("PUBLICMIND_DATABASE_URL", "data/publicmind.db")
    exports = export_dir or os.getenv("PUBLICMIND_EXPORT_DIR", "data/exports")
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    app = FastAPI(title="PublicMind", version="0.1.0")
    local_settings_file = settings_path(db)
    identity_reference_provider = (
        reference_provider
        if reference_provider is not None
        else None
        if search_provider is not None
        else WikipediaSearchProvider()
    )
    active_image_provider = (
        image_provider
        if image_provider is not None
        else None
        if search_provider is not None
        else WikimediaImageProvider()
    )

    def current_search_provider() -> SearchProvider:
        if search_provider is not None:
            return search_provider
        settings = load_local_settings(local_settings_file)
        return BraveSearchProvider(api_key=settings.get("brave_api_key"))

    def current_llm_provider() -> LLMProvider:
        if llm_provider is not None:
            return llm_provider
        settings = load_local_settings(local_settings_file)
        return OpenAICompatibleProvider(api_key=settings.get("deepseek_api_key"))

    def enrich_report_content(
        repository: Repository, person_id: str, content: Dict[str, Any]
    ) -> Dict[str, Any]:
        enriched = dict(content)
        enriched.setdefault("language_mode", "zh")
        enriched.setdefault("translation_scope", "structured_report_only")
        enriched.setdefault("images", [])
        if not enriched.get("public_profiles"):
            enriched["public_profiles"] = _platform_links(
                repository.list_candidates(person_id)
            )
        if not enriched.get("public_sources"):
            enriched["public_sources"] = [
                {
                    "title": document.title,
                    "url": document.source_url,
                    "platform": _public_platform(document.source_url),
                    "author": document.author or "",
                    "published_at": document.published_at or "",
                }
                for document in repository.list_documents(person_id)
            ]
        return enriched

    def discover_person_images(repository: Repository, person_id: str) -> List[Dict[str, str]]:
        if active_image_provider is None:
            return []
        person = repository.get_person(person_id)
        if not person:
            return []
        reference_urls = [
            candidate.url
            for candidate in repository.list_candidates(person_id)
            if _is_reference_source(candidate)
        ]
        try:
            return active_image_provider.discover(person.name, reference_urls, limit=4)
        except Exception:
            return []

    def research_question(
        repository: Repository,
        person_id: str,
        queries: List[str],
        max_sources: int = 6,
    ) -> int:
        """Search, ingest and persist sources for one question-specific knowledge gap."""

        person = repository.get_person(person_id)
        if not person:
            return 0
        candidates = DiscoveryService(
            repository, current_search_provider()
        ).discover_targeted(person, queries)
        existing_urls = {document.source_url for document in repository.list_documents(person_id)}
        inserted = 0
        attempted = 0
        for candidate in candidates:
            if candidate.url in existing_urls or attempted >= max_sources:
                continue
            attempted += 1
            if candidate.id and candidate.status != "accepted":
                candidate = repository.decide_candidate(candidate.id, "accepted")
            source = repository.add_source(
                person_id, candidate.url, candidate.source_role
            )
            repository.update_source_status(source.id or "", "fetching")
            try:
                result = asyncio.run(
                    IngestPipeline(repository, connector_registry).ingest(
                        person_id, candidate.url
                    )
                )
                if result.document:
                    existing_urls.add(candidate.url)
                if result.inserted:
                    inserted += 1
            except Exception:
                repository.update_source_status(source.id or "", "failed")

        if inserted:
            report = repository.get_report(person_id)
            if report:
                content = enrich_report_content(repository, person_id, report.content)
                content["public_sources"] = [
                    {
                        "title": document.title,
                        "url": document.source_url,
                        "platform": _public_platform(document.source_url),
                        "author": document.author or "",
                        "published_at": document.published_at or "",
                    }
                    for document in repository.list_documents(person_id)
                ]
                repository.save_report(person_id, content)
        return inserted

    app.mount("/assets", StaticFiles(directory=str(frontend_dir)), name="assets")

    @app.middleware("http")
    async def disable_frontend_asset_cache(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(frontend_dir / "index.html"), media_type="text/html")

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config() -> Dict[str, Any]:
        return configuration_status(local_settings_file)

    @app.post("/api/config")
    def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
        brave = payload.get("brave_api_key")
        deepseek = payload.get("deepseek_api_key")
        if brave is not None and not isinstance(brave, str):
            raise HTTPException(status_code=422, detail="Brave API Key 格式不正确")
        if deepseek is not None and not isinstance(deepseek, str):
            raise HTTPException(status_code=422, detail="DeepSeek API Key 格式不正确")
        if not str(brave or "").strip() and not str(deepseek or "").strip():
            raise HTTPException(status_code=422, detail="请至少填写一个 API Key")
        save_local_settings(local_settings_file, brave, deepseek)
        return configuration_status(local_settings_file)

    @app.get("/api/persons")
    def list_persons():
        with Repository(db) as repository:
            result = []
            for person in repository.list_persons():
                sources = repository.list_sources(person.id or "")
                documents = repository.list_documents(person.id or "")
                report = repository.get_report(person.id or "")
                result.append(
                    {
                        "id": person.id,
                        "name": person.name,
                        "slug": person.slug,
                        "description": person.description,
                        "source_count": len(sources),
                        "document_count": len(documents),
                        "has_report": report is not None,
                        "overview": report.content.get("overview", "") if report else "",
                    }
                )
            return result

    @app.get("/api/persons/{person_id}")
    def get_person(person_id: str):
        with Repository(db) as repository:
            person = repository.get_person(person_id)
            if not person:
                raise HTTPException(status_code=404, detail="person not found")
            return {
                "id": person.id,
                "name": person.name,
                "slug": person.slug,
                "description": person.description,
            }

    @app.post("/api/persons")
    def create_person(payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        with Repository(db) as repository:
            person = repository.create_person(name, payload.get("description"))
            return {
                "id": person.id,
                "name": person.name,
                "slug": person.slug,
                "description": person.description,
            }

    @app.post("/api/persons/{person_id}/sources")
    def add_source(person_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        parsed = urlparse(url)
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise HTTPException(status_code=422, detail="a public http(s) URL is required")
            source_role = str(payload.get("source_role", "unclassified"))
            if source_role not in SOURCE_ROLES:
                raise HTTPException(status_code=422, detail="unknown source role")
            source = repository.add_source(person_id, url, source_role)
            return {
                "id": source.id,
                "platform": source.platform,
                "url": source.url,
                "status": source.status,
                "source_role": source.source_role,
            }

    @app.get("/api/persons/{person_id}/sources")
    def list_sources(person_id: str):
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            return [
                {
                    "id": source.id,
                    "person_id": source.person_id,
                    "platform": source.platform,
                    "url": source.url,
                    "status": source.status,
                    "source_role": source.source_role,
                }
                for source in repository.list_sources(person_id)
            ]

    @app.post("/api/persons/{person_id}/discover")
    def discover_sources(person_id: str, payload: Dict[str, Any]):
        raw_anchors = payload.get("anchors", [])
        if not isinstance(raw_anchors, list):
            raise HTTPException(status_code=422, detail="anchors must be a list")
        anchors = [str(anchor).strip() for anchor in raw_anchors if str(anchor).strip()][:8]
        with Repository(db) as repository:
            person = repository.get_person(person_id)
            if not person:
                raise HTTPException(status_code=404, detail="person not found")
            try:
                candidates = DiscoveryService(
                    repository,
                    current_search_provider(),
                    identity_reference_provider,
                ).discover(person, anchors)
            except SearchProviderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return [_candidate_payload(candidate) for candidate in candidates]

    @app.post("/api/persons/{person_id}/prepare")
    def prepare_identity(person_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_anchors = payload.get("anchors", [])
        if not isinstance(raw_anchors, list):
            raise HTTPException(status_code=422, detail="身份线索格式不正确")
        anchors = [str(anchor).strip() for anchor in raw_anchors if str(anchor).strip()][:8]
        with Repository(db) as repository:
            person = repository.get_person(person_id)
            if not person:
                raise HTTPException(status_code=404, detail="人物不存在")
            try:
                candidates = DiscoveryService(
                    repository,
                    current_search_provider(),
                    identity_reference_provider,
                ).discover(person, anchors)
            except SearchProviderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            primary = _primary_identity_source(candidates)
            if not primary:
                raise HTTPException(
                    status_code=404,
                    detail="没有找到可以确认身份的公开主页，请补充机构、领域或用户名",
                )
            return {
                "person_id": person_id,
                "name": person.name,
                "primary_source": {
                    "candidate_id": primary.id,
                    "title": primary.title,
                    "url": primary.url,
                    "snippet": primary.snippet,
                    "platform": _public_platform(primary.url, primary.source_role),
                },
                "platform_links": _platform_links(candidates),
            }

    @app.get("/api/persons/{person_id}/candidates")
    def list_candidates(person_id: str):
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            return [_candidate_payload(item) for item in repository.list_candidates(person_id)]

    @app.post("/api/candidates/{candidate_id}/accept")
    def accept_candidate(candidate_id: str):
        with Repository(db) as repository:
            candidate = repository.get_candidate(candidate_id)
            if not candidate:
                raise HTTPException(status_code=404, detail="candidate not found")
            return _candidate_payload(repository.decide_candidate(candidate_id, "accepted"))

    @app.post("/api/candidates/{candidate_id}/reject")
    def reject_candidate(candidate_id: str):
        with Repository(db) as repository:
            candidate = repository.get_candidate(candidate_id)
            if not candidate:
                raise HTTPException(status_code=404, detail="candidate not found")
            return _candidate_payload(repository.decide_candidate(candidate_id, "rejected"))

    def crawl_source(job_id: str, person_id: str, source_id: str, source_url: str) -> None:
        with Repository(db) as repository:
            repository.update_job(job_id, "fetching", 0.1)
            repository.update_source_status(source_id, "fetching")
            try:
                asyncio.run(IngestPipeline(repository, connector_registry).ingest(person_id, source_url))
                repository.update_job(job_id, "completed", 1.0)
            except Exception as exc:
                repository.update_source_status(source_id, "failed")
                repository.update_job(job_id, "failed", 1.0, str(exc))

    @app.post("/api/sources/{source_id}/crawl")
    def start_crawl(source_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        with Repository(db) as repository:
            source = repository.get_source(source_id)
            if not source:
                raise HTTPException(status_code=404, detail="source not found")
            job = repository.create_job(source.person_id, source.id or source_id)
            repository.update_source_status(source.id or source_id, "queued")
            background_tasks.add_task(crawl_source, job.id, source.person_id, source.id or source_id, source.url)
            return {"id": job.id, "status": job.status, "progress": job.progress}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> Dict[str, Any]:
        with Repository(db) as repository:
            job = repository.get_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            return {
                "id": job.id,
                "person_id": job.person_id,
                "source_id": job.source_id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
            }

    @app.get("/api/persons/{person_id}/documents")
    def list_documents(person_id: str):
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            return [
                {
                    "id": document.id,
                    "title": document.title,
                    "source_type": document.source_type,
                    "source_url": document.source_url,
                    "author": document.author,
                    "published_at": document.published_at,
                    "fetched_at": document.fetched_at,
                    "content_hash": document.content_hash,
                    "summary": document.summary,
                    "topics": document.topics,
                }
                for document in repository.list_documents(person_id)
            ]

    @app.get("/api/documents/{document_id}")
    def get_document(document_id: str):
        with Repository(db) as repository:
            document = repository.get_document(document_id)
            if not document:
                raise HTTPException(status_code=404, detail="document not found")
            return {
                "id": document.id,
                "title": document.title,
                "author": document.author,
                "source_type": document.source_type,
                "source_url": document.source_url,
                "published_at": document.published_at,
                "fetched_at": document.fetched_at,
                "content": document.content,
                "content_hash": document.content_hash,
                "summary": document.summary,
                "topics": document.topics,
                "entities": document.entities,
            }

    @app.post("/api/documents/{document_id}/claims/propose")
    def propose_claims(document_id: str):
        with Repository(db) as repository:
            document = repository.get_document(document_id)
            if not document:
                raise HTTPException(status_code=404, detail="document not found")
            person = repository.get_person(document.person_id)
            source = repository.get_source(document.source_id)
            if not person or not source:
                raise HTTPException(status_code=409, detail="document evidence context is incomplete")
            proposals = ClaimExtractor().propose(
                person, source, document, repository.list_chunks(document_id)
            )
            saved = repository.save_claims(proposals)
            return [_claim_payload(claim, repository) for claim in saved]

    @app.get("/api/persons/{person_id}/claims")
    def list_claims(person_id: str, status: Optional[str] = None):
        if status and status not in {"pending", "accepted", "rejected"}:
            raise HTTPException(status_code=422, detail="unknown claim status")
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            return [
                _claim_payload(claim, repository)
                for claim in repository.list_claims(person_id, status)
            ]

    @app.post("/api/claims/{claim_id}/accept")
    def accept_claim(claim_id: str, payload: Dict[str, Any]):
        claim_type = str(payload.get("claim_type", "")).strip() or None
        if claim_type and claim_type not in CLAIM_TYPES:
            raise HTTPException(status_code=422, detail="unknown claim type")
        with Repository(db) as repository:
            if not repository.get_claim(claim_id):
                raise HTTPException(status_code=404, detail="claim not found")
            reviewed = repository.review_claim(
                claim_id,
                "accepted",
                statement=str(payload.get("statement", "")).strip() or None,
                claim_type=claim_type,
                speaker=str(payload.get("speaker", "")).strip() or None,
                review_note=str(payload.get("review_note", "")).strip() or None,
            )
            return _claim_payload(reviewed, repository)

    @app.post("/api/claims/{claim_id}/reject")
    def reject_claim(claim_id: str, payload: Dict[str, Any]):
        with Repository(db) as repository:
            if not repository.get_claim(claim_id):
                raise HTTPException(status_code=404, detail="claim not found")
            reviewed = repository.review_claim(
                claim_id,
                "rejected",
                review_note=str(payload.get("review_note", "")).strip() or None,
            )
            return _claim_payload(reviewed, repository)

    @app.post("/api/persons/{person_id}/export")
    def export_person(person_id: str):
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="person not found")
            report = repository.get_report(person_id)
            if report:
                enriched = enrich_report_content(repository, person_id, report.content)
                if enriched != report.content:
                    repository.save_report(person_id, enriched)
            _, zip_path = IngestPipeline(repository).export(person_id, exports)
        return FileResponse(str(Path(zip_path)), filename=Path(zip_path).name, media_type="application/zip")

    def select_candidates(candidates: List[SourceCandidate], limit: int = 12) -> List[SourceCandidate]:
        eligible = [
            item
            for item in candidates
            if item.score >= 45 and item.source_role != "aggregator_repost"
        ]
        selected: List[SourceCandidate] = []
        selected_ids = set()
        reference = next((item for item in candidates if _is_reference_source(item)), None)
        if reference:
            selected.append(reference)
            selected_ids.add(reference.id)
        for role in (
            "subject_official",
            "subject_interview",
            "media_report",
            "third_party_commentary",
        ):
            match = next((item for item in eligible if item.source_role == role), None)
            if match and match.id not in selected_ids:
                selected.append(match)
                selected_ids.add(match.id)
        host_counts: Dict[str, int] = {}
        for item in selected:
            host = (urlparse(item.url).hostname or "").lower()
            host_counts[host] = host_counts.get(host, 0) + 1
        for item in eligible:
            if len(selected) >= limit:
                break
            if item.id in selected_ids:
                continue
            host = (urlparse(item.url).hostname or "").lower()
            if host_counts.get(host, 0) >= 2:
                continue
            selected.append(item)
            selected_ids.add(item.id)
            host_counts[host] = host_counts.get(host, 0) + 1
        return selected

    def build_person(
        job_id: str,
        person_id: str,
        anchors: List[str],
        confirmed_source_url: Optional[str],
        use_existing_candidates: bool,
        language_mode: str,
        refresh_source_urls: Optional[List[str]] = None,
    ) -> None:
        with Repository(db) as repository:
            try:
                person = repository.get_person(person_id)
                if not person:
                    raise ValueError("人物不存在")
                repository.update_build_job(job_id, "running", "正在检索公开资料", 0.08)
                candidates = repository.list_candidates(person_id) if use_existing_candidates else []
                if not candidates and not refresh_source_urls:
                    candidates = DiscoveryService(
                        repository,
                        current_search_provider(),
                        identity_reference_provider,
                    ).discover(person, anchors)
                selected = select_candidates(candidates)
                if confirmed_source_url:
                    confirmed = next(
                        (item for item in candidates if item.url == confirmed_source_url), None
                    )
                    if confirmed and confirmed.id:
                        repository.decide_candidate(confirmed.id, "accepted")
                for candidate in selected:
                    if candidate.id:
                        repository.decide_candidate(candidate.id, "accepted")

                all_sources = repository.list_sources(person_id)
                if refresh_source_urls:
                    refresh_urls = set(refresh_source_urls)
                    sources = [source for source in all_sources if source.url in refresh_urls]
                else:
                    sources = all_sources[:12]
                if not sources:
                    raise SearchProviderError("没有找到可用于建库的公开资料，请补充身份线索后重试")
                succeeded = 0
                for index, source in enumerate(sources, 1):
                    progress = 0.18 + (index - 1) / max(len(sources), 1) * 0.50
                    repository.update_build_job(
                        job_id,
                        "running",
                        "正在读取公开资料（%d/%d）" % (index, len(sources)),
                        progress,
                    )
                    repository.update_source_status(source.id or "", "fetching")
                    try:
                        asyncio.run(
                            IngestPipeline(repository, connector_registry).ingest(person_id, source.url)
                        )
                        succeeded += 1
                    except Exception:
                        repository.update_source_status(source.id or "", "failed")

                documents = repository.list_documents(person_id)
                if not documents:
                    raise RuntimeError("找到了一些网址，但都未能读取正文；请稍后重试或补充公开网址")
                repository.update_build_job(job_id, "running", "正在整理人物经历与观点", 0.74)
                previous_report = repository.get_report(person_id)
                report_content = ProfileBuilder(current_llm_provider()).build(
                    person,
                    repository.list_sources(person_id),
                    documents,
                    language_mode=language_mode,
                )
                report_content["public_profiles"] = _platform_links(candidates)
                report_content["public_sources"] = [
                    {
                        "title": document.title,
                        "url": document.source_url,
                        "platform": _public_platform(document.source_url),
                        "author": document.author or "",
                        "published_at": document.published_at or "",
                    }
                    for document in documents
                ]
                previous_images = (
                    previous_report.content.get("images", []) if previous_report else []
                )
                report_content["images"] = (
                    previous_images
                    if refresh_source_urls and previous_images
                    else discover_person_images(repository, person_id)
                )
                report = repository.save_report(person_id, report_content)
                repository.update_build_job(job_id, "running", "正在生成 Obsidian 知识库", 0.92)
                _, archive_path = VaultExporter(exports).export(
                    person, documents, report=report_content
                )
                repository.update_build_job(
                    job_id,
                    "completed",
                    "人物知识库已完成",
                    1.0,
                    report_id=report.id,
                    archive_path=str(archive_path),
                )
            except (SearchProviderError, LLMProviderError, RuntimeError, ValueError) as exc:
                repository.update_build_job(job_id, "failed", "生成未完成", 1.0, str(exc))
            except Exception as exc:  # pragma: no cover - last-resort job boundary
                repository.update_build_job(job_id, "failed", "生成未完成", 1.0, str(exc))

    @app.post("/api/persons/{person_id}/build")
    def start_build(
        person_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks
    ) -> Dict[str, Any]:
        raw_anchors = payload.get("anchors", [])
        if not isinstance(raw_anchors, list):
            raise HTTPException(status_code=422, detail="身份线索格式不正确")
        anchors = [str(item).strip() for item in raw_anchors if str(item).strip()][:8]
        language_mode = str(payload.get("language_mode", "zh")).strip()
        if language_mode not in {"zh", "en", "bilingual"}:
            raise HTTPException(status_code=422, detail="未知的输出语言")
        confirmed_source_url = str(payload.get("confirmed_source_url", "")).strip() or None
        use_existing_candidates = bool(payload.get("use_existing_candidates", False))
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="人物不存在")
            job = repository.create_build_job(person_id)
        background_tasks.add_task(
            build_person,
            job.id or "",
            person_id,
            anchors,
            confirmed_source_url,
            use_existing_candidates,
            language_mode,
        )
        return {
            "id": job.id,
            "person_id": job.person_id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
        }

    @app.post("/api/persons/{person_id}/refresh")
    def refresh_person(
        person_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks
    ) -> Dict[str, Any]:
        raw_urls = payload.get("urls", [])
        if not isinstance(raw_urls, list):
            raise HTTPException(status_code=422, detail="信息源网址格式不正确")
        urls: List[str] = []
        for raw_url in raw_urls[:8]:
            url = str(raw_url).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise HTTPException(status_code=422, detail="需要公开的 http(s) 网址")
            if url not in urls:
                urls.append(url)
        if not urls:
            raise HTTPException(status_code=422, detail="请至少添加一个信息源网址")
        with Repository(db) as repository:
            person = repository.get_person(person_id)
            if not person:
                raise HTTPException(status_code=404, detail="人物不存在")
            previous_report = repository.get_report(person_id)
            requested_language = str(payload.get("language_mode", "")).strip()
            language_mode = requested_language or (
                str(previous_report.content.get("language_mode", "zh"))
                if previous_report
                else "zh"
            )
            if language_mode not in {"zh", "en", "bilingual"}:
                raise HTTPException(status_code=422, detail="未知的输出语言")
            for url in urls:
                repository.add_source(person_id, url)
            job = repository.create_build_job(person_id)
        background_tasks.add_task(
            build_person,
            job.id or "",
            person_id,
            [],
            None,
            True,
            language_mode,
            urls,
        )
        return {
            "id": job.id,
            "person_id": job.person_id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
        }

    @app.get("/api/build-jobs/{job_id}")
    def get_build_job(job_id: str) -> Dict[str, Any]:
        with Repository(db) as repository:
            job = repository.get_build_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            return {
                "id": job.id,
                "person_id": job.person_id,
                "status": job.status,
                "stage": job.stage,
                "progress": job.progress,
                "error": job.error,
                "report_id": job.report_id,
                "download_url": "/api/build-jobs/%s/download" % job_id
                if job.status == "completed" and job.archive_path
                else None,
            }

    @app.get("/api/persons/{person_id}/report")
    def get_person_report(person_id: str) -> Dict[str, Any]:
        with Repository(db) as repository:
            report = repository.get_report(person_id)
            if not report:
                raise HTTPException(status_code=404, detail="人物报告尚未生成")
            enriched = enrich_report_content(repository, person_id, report.content)
            if enriched != report.content:
                report = repository.save_report(person_id, enriched)
            return {"id": report.id, "person_id": report.person_id, "content": enriched}

    @app.post("/api/persons/{person_id}/images/refresh")
    def refresh_person_images(person_id: str) -> Dict[str, Any]:
        with Repository(db) as repository:
            if not repository.get_person(person_id):
                raise HTTPException(status_code=404, detail="人物不存在")
            report = repository.get_report(person_id)
            if not report:
                raise HTTPException(status_code=404, detail="人物报告尚未生成")
            images = discover_person_images(repository, person_id)
            if images:
                content = enrich_report_content(repository, person_id, report.content)
                content["images"] = images
                repository.save_report(person_id, content)
            return {"person_id": person_id, "images": images}

    @app.post("/api/persons/{person_id}/ask")
    def ask_person_knowledge_base(person_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise HTTPException(status_code=422, detail="请输入想问的问题")
        if len(question) > 600:
            raise HTTPException(status_code=422, detail="问题请控制在 600 字以内")
        with Repository(db) as repository:
            person = repository.get_person(person_id)
            if not person:
                raise HTTPException(status_code=404, detail="人物不存在")
            report = repository.get_report(person_id)
            if not report:
                raise HTTPException(status_code=404, detail="请先生成人物知识档案")
            documents = repository.list_documents(person_id)
            try:
                answerer = KnowledgeAnswerer(current_llm_provider())
                report_content = enrich_report_content(
                    repository, person_id, report.content
                )
                answer = answerer.answer(
                    person,
                    report_content,
                    documents,
                    question,
                )
            except LLMProviderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            research_triggered = bool(answer.get("insufficient_knowledge"))
            new_documents = 0
            research_status = "not_needed"
            if research_triggered:
                queries = answer.get("search_queries") or fallback_research_queries(
                    person, report_content, question
                )
                research_status = "no_new_material"
                try:
                    new_documents = research_question(
                        repository, person_id, list(queries)
                    )
                except SearchProviderError:
                    research_status = "search_unavailable"
                if new_documents:
                    research_status = "expanded"
                    documents = repository.list_documents(person_id)
                    refreshed_report = repository.get_report(person_id)
                    try:
                        answer = answerer.answer(
                            person,
                            enrich_report_content(
                                repository,
                                person_id,
                                refreshed_report.content if refreshed_report else report_content,
                            ),
                            documents,
                            question,
                        )
                    except LLMProviderError:
                        pass

            answer.pop("search_queries", None)
            titles = {document.source_url: document.title for document in documents}
            answer["sources"] = [
                {"url": url, "title": titles.get(url, url)}
                for url in answer.pop("source_urls", [])
            ]
            answer["research"] = {
                "triggered": research_triggered,
                "status": research_status,
                "new_documents": new_documents,
            }
            return answer

    @app.get("/api/build-jobs/{job_id}/download")
    def download_build(job_id: str):
        with Repository(db) as repository:
            job = repository.get_build_job(job_id)
            if not job or job.status != "completed" or not job.archive_path:
                raise HTTPException(status_code=404, detail="知识库文件尚未生成")
            archive = Path(job.archive_path).resolve()
        export_root = Path(exports).resolve()
        try:
            inside_export_root = os.path.commonpath([str(archive), str(export_root)]) == str(export_root)
        except ValueError:
            inside_export_root = False
        if not inside_export_root or not archive.is_file():
            raise HTTPException(status_code=404, detail="知识库文件不存在")
        return FileResponse(str(archive), filename=archive.name, media_type="application/zip")

    return app
