import unittest
from unittest.mock import patch

from app.backend.discovery.crossref import CrossrefAcademicProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CrossrefTests(unittest.TestCase):
    def test_crossref_keeps_exact_author_name_in_either_name_order(self):
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1000/wrong",
                        "title": ["Wrong namesake paper"],
                        "author": [{"given": "Shih-Han", "family": "Huang"}],
                    },
                    {
                        "DOI": "10.1000/wrong-field",
                        "title": ["Matrix multiplication on ARM processors"],
                        "author": [{"given": "Han", "family": "Huang"}],
                        "container-title": ["Computer Architecture"],
                    },
                    {
                        "DOI": "10.1000/right",
                        "title": ["Precision manufacturing research"],
                        "author": [{"given": "Han", "family": "Huang"}],
                        "published": {"date-parts": [[2024, 5, 1]]},
                        "container-title": ["Manufacturing Letters"],
                        "is-referenced-by-count": 31,
                    },
                ]
            }
        }
        with patch(
            "app.backend.discovery.crossref.httpx.get",
            return_value=FakeResponse(payload),
        ):
            hits = CrossrefAcademicProvider().search(
                "Han Huang", ["Sun Yat-sen University", "mechanical engineering"]
            )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://doi.org/10.1000/right")
        self.assertIn("被引 31 次", hits[0].snippet)


if __name__ == "__main__":
    unittest.main()
