"""OpenAlex adapter for deeper academic-author and publication discovery."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

import httpx

from .base import SearchHit, SearchProviderError


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _author_text(author: Dict[str, Any]) -> str:
    parts = [str(author.get("display_name", ""))]
    parts.extend(str(item) for item in author.get("display_name_alternatives", []) or [])
    for institution in author.get("last_known_institutions", []) or []:
        if isinstance(institution, dict):
            parts.append(str(institution.get("display_name", "")))
    for affiliation in author.get("affiliations", []) or []:
        if not isinstance(affiliation, dict):
            continue
        institution = affiliation.get("institution") or {}
        if isinstance(institution, dict):
            parts.append(str(institution.get("display_name", "")))
    for topic in (author.get("topics") or author.get("x_concepts") or [])[:10]:
        if isinstance(topic, dict):
            parts.append(str(topic.get("display_name", "")))
    return " ".join(part for part in parts if part)


class OpenAlexAcademicProvider:
    name = "openalex"

    def __init__(self, timeout: float = 18.0) -> None:
        self.timeout = timeout

    def search(
        self, person_name: str, identity_terms: Sequence[str], count: int = 16
    ) -> List[SearchHit]:
        try:
            author_response = httpx.get(
                "https://api.openalex.org/authors",
                params={"search": person_name, "per-page": 8},
                headers={"User-Agent": "PublicMind/0.1"},
                timeout=self.timeout,
            )
            author_response.raise_for_status()
            authors = author_response.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("OpenAlex 学术索引暂时不可用：%s" % exc) from exc

        normalized_name = _normalize(person_name)
        scored = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            names = [str(author.get("display_name", ""))]
            names.extend(str(item) for item in author.get("display_name_alternatives", []) or [])
            if not any(_normalize(name) == normalized_name for name in names):
                continue
            text = _normalize(_author_text(author))
            anchor_matches = sum(1 for term in identity_terms if _normalize(term) in text)
            scored.append((anchor_matches, int(author.get("works_count") or 0), author))
        if not scored:
            return []
        scored.sort(key=lambda item: (-item[0], -item[1]))
        best_matches, _, author = scored[0]
        if len(scored) > 1 and best_matches == 0:
            return []

        author_id = str(author.get("id", "")).rsplit("/", 1)[-1]
        if not author_id:
            return []
        try:
            works_response = httpx.get(
                "https://api.openalex.org/works",
                params={
                    "filter": "author.id:%s" % author_id,
                    "sort": "cited_by_count:desc",
                    "per-page": min(max(count, 1), 25),
                },
                headers={"User-Agent": "PublicMind/0.1"},
                timeout=self.timeout,
            )
            works_response.raise_for_status()
            works = works_response.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("OpenAlex 论文列表暂时不可用：%s" % exc) from exc

        display_name = str(author.get("display_name") or person_name)
        identity_summary = _author_text(author)
        hits = [
            SearchHit(
                url="https://openalex.org/%s" % author_id,
                title="%s — OpenAlex" % display_name,
                snippet=identity_summary,
            )
        ]
        for work in works:
            if not isinstance(work, dict):
                continue
            title = str(work.get("display_name") or work.get("title") or "").strip()
            if not title:
                continue
            primary_location = work.get("primary_location") or {}
            landing_url = primary_location.get("landing_page_url") if isinstance(primary_location, dict) else None
            url = str(work.get("doi") or landing_url or work.get("id") or "").strip()
            if not url:
                continue
            year = work.get("publication_year") or "年份不详"
            cited = int(work.get("cited_by_count") or 0)
            source = primary_location.get("source") if isinstance(primary_location, dict) else None
            venue = str(source.get("display_name", "")) if isinstance(source, dict) else ""
            hits.append(
                SearchHit(
                    url=url,
                    title=title,
                    snippet="%s · %s · %s · 被引 %d 次" % (display_name, year, venue or "学术论文", cited),
                    published_at=str(year) if year != "年份不详" else None,
                )
            )
        return hits
