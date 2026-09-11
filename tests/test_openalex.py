import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.backend.discovery.base import SearchHit
from app.backend.discovery.base import SearchProviderError
from app.backend.discovery.academic import AcademicIndexProvider
from app.backend.discovery.openalex import OpenAlexAcademicProvider
from app.backend.discovery.service import DiscoveryService
from app.backend.store import Repository


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class OpenAlexTests(unittest.TestCase):
    def test_academic_index_falls_back_when_openalex_is_rate_limited(self):
        class RateLimited:
            def search(self, person_name, identity_terms, count=16):
                raise SearchProviderError("429")

        class CrossrefFallback:
            def search(self, person_name, identity_terms, count=16):
                return [SearchHit(
                    "https://doi.org/10.1000/fallback",
                    "Fallback paper",
                    "mechanical engineering",
                )]

        provider = AcademicIndexProvider()
        provider.providers = [RateLimited(), CrossrefFallback()]
        hits = provider.search("Han Huang", ["mechanical engineering"])
        self.assertEqual(hits[0].url, "https://doi.org/10.1000/fallback")

    def test_author_identity_terms_select_the_matching_author_and_return_works(self):
        authors = {
            "results": [
                {
                    "id": "https://openalex.org/A_WRONG",
                    "display_name": "Han Huang",
                    "works_count": 400,
                    "last_known_institutions": [{"display_name": "University of Missouri"}],
                    "topics": [{"display_name": "Mathematics"}],
                },
                {
                    "id": "https://openalex.org/A_RIGHT",
                    "display_name": "Han Huang",
                    "works_count": 180,
                    "last_known_institutions": [{"display_name": "Sun Yat-sen University"}],
                    "topics": [{"display_name": "Advanced Manufacturing"}],
                },
            ]
        }
        works = {
            "results": [{
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1000/manufacturing",
                "display_name": "Precision manufacturing research",
                "publication_year": 2024,
                "cited_by_count": 42,
                "primary_location": {"source": {"display_name": "Manufacturing Letters"}},
            }]
        }
        with patch(
            "app.backend.discovery.openalex.httpx.get",
            side_effect=[FakeResponse(authors), FakeResponse(works)],
        ):
            hits = OpenAlexAcademicProvider().search(
                "Han Huang", ["Sun Yat-sen University", "Advanced Manufacturing"]
            )

        self.assertEqual(hits[0].url, "https://openalex.org/A_RIGHT")
        self.assertEqual(hits[1].url, "https://doi.org/10.1000/manufacturing")
        self.assertIn("被引 42 次", hits[1].snippet)

    def test_discovery_merges_openalex_results_for_academic_people(self):
        class EmptySearch:
            name = "empty"

            def search(self, query, count=10):
                return []

        class AcademicSearch:
            name = "openalex"

            def search(self, person_name, identity_terms, count=16):
                self.person_name = person_name
                self.identity_terms = identity_terms
                return [SearchHit(
                    "https://doi.org/10.1000/example",
                    "Precision manufacturing research",
                    "Han Huang · Sun Yat-sen University · mechanical engineering",
                )]

        academic = AcademicSearch()
        with tempfile.TemporaryDirectory() as directory:
            with Repository(str(Path(directory) / "publicmind.db")) as repository:
                person = repository.create_person("黄含", "中山大学机械工程教授")
                candidates = DiscoveryService(
                    repository,
                    EmptySearch(),
                    academic_provider=academic,
                ).discover(person, ["中山大学", "机械工程"])

        self.assertEqual(academic.person_name, "Han Huang")
        self.assertIn("Sun Yat-sen University", academic.identity_terms)
        self.assertEqual(candidates[0].provider, "openalex")
        self.assertEqual(candidates[0].url, "https://doi.org/10.1000/example")


if __name__ == "__main__":
    unittest.main()
