"""Resilient academic discovery across public indexes."""

from __future__ import annotations

from typing import List, Sequence

from .base import SearchHit, SearchProviderError
from .crossref import CrossrefAcademicProvider
from .openalex import OpenAlexAcademicProvider


class AcademicIndexProvider:
    name = "academic-index"

    def __init__(self) -> None:
        self.providers = [OpenAlexAcademicProvider(), CrossrefAcademicProvider()]

    def search(
        self, person_name: str, identity_terms: Sequence[str], count: int = 16
    ) -> List[SearchHit]:
        hits: List[SearchHit] = []
        seen = set()
        failures = []
        for provider in self.providers:
            try:
                provider_hits = provider.search(person_name, identity_terms, count=count)
            except SearchProviderError as exc:
                failures.append(exc)
                continue
            for hit in provider_hits:
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                hits.append(hit)
                if len(hits) >= count:
                    return hits
        if not hits and len(failures) == len(self.providers):
            raise SearchProviderError(str(failures[-1]))
        return hits
