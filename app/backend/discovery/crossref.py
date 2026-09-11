"""Crossref adapter used when richer author indexes are unavailable."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

import httpx

from .base import SearchHit, SearchProviderError


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _author_matches(author: Dict[str, Any], person_name: str) -> bool:
    given = str(author.get("given") or "")
    family = str(author.get("family") or "")
    expected = _normalize(person_name)
    return expected in {
        _normalize("%s %s" % (given, family)),
        _normalize("%s %s" % (family, given)),
    }


TERM_ALIASES = {
    "mechanical engineering": ("mechanical", "manufacturing", "machining", "grinding"),
    "advanced manufacturing": ("manufacturing", "machining", "grinding", "precision"),
    "artificial intelligence": ("artificial intelligence", "machine learning", "deep learning"),
    "computer science": ("computer science", "computing", "software", "algorithm"),
}


def _identity_relevant(item: Dict[str, Any], authors: List[Dict[str, Any]], terms: Sequence[str]) -> bool:
    if not terms:
        return True
    parts = []
    parts.extend(str(value) for value in item.get("title", []) or [])
    parts.extend(str(value) for value in item.get("container-title", []) or [])
    parts.extend(str(value) for value in item.get("subject", []) or [])
    for author in authors:
        for affiliation in author.get("affiliation", []) or []:
            if isinstance(affiliation, dict):
                parts.append(str(affiliation.get("name", "")))
    text = " ".join(parts).casefold()
    normalized_text = _normalize(text)
    field_terms = [term.casefold().strip() for term in terms if term.casefold().strip() in TERM_ALIASES]
    if field_terms:
        return any(
            _normalize(term) in normalized_text
            or any(alias in text for alias in TERM_ALIASES[term])
            for term in field_terms
        )
    for term in terms:
        lowered = term.casefold().strip()
        if lowered and _normalize(lowered) in normalized_text:
            return True
        aliases = TERM_ALIASES.get(lowered, ())
        if any(alias in text for alias in aliases):
            return True
        distinctive_words = [
            word for word in re.findall(r"[a-z]{5,}", lowered)
            if word not in {"university", "college", "institute", "engineering", "science"}
        ]
        if distinctive_words and any(word in text for word in distinctive_words):
            return True
    return False


class CrossrefAcademicProvider:
    name = "crossref"

    def __init__(self, timeout: float = 18.0) -> None:
        self.timeout = timeout

    def search(
        self, person_name: str, identity_terms: Sequence[str], count: int = 16
    ) -> List[SearchHit]:
        try:
            response = httpx.get(
                "https://api.crossref.org/works",
                params={
                    "query.author": person_name,
                    "query.affiliation": " ".join(identity_terms[:4]),
                    "query.bibliographic": " ".join(identity_terms[:4]),
                    "rows": min(max(count * 2, 10), 40),
                    "select": "DOI,title,author,published,container-title,subject,is-referenced-by-count,URL",
                },
                headers={"User-Agent": "PublicMind/0.1"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("Crossref 论文索引暂时不可用：%s" % exc) from exc

        hits: List[SearchHit] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            authors = [author for author in item.get("author", []) if isinstance(author, dict)]
            if not any(_author_matches(author, person_name) for author in authors):
                continue
            if not _identity_relevant(item, authors, identity_terms):
                continue
            titles = item.get("title") or []
            title = str(titles[0] if titles else "").strip()
            doi = str(item.get("DOI") or "").strip()
            if not title or not doi:
                continue
            date_parts = (item.get("published") or {}).get("date-parts") or []
            year = date_parts[0][0] if date_parts and date_parts[0] else None
            venues = item.get("container-title") or []
            venue = str(venues[0] if venues else "学术论文")
            cited = int(item.get("is-referenced-by-count") or 0)
            hits.append(SearchHit(
                url="https://doi.org/%s" % doi,
                title=title,
                snippet="%s · %s · %s · 被引 %d 次" % (
                    person_name, year or "年份不详", venue, cited
                ),
                published_at=str(year) if year else None,
            ))
            if len(hits) >= count:
                break
        return hits
