import unittest
from unittest.mock import patch

from app.backend.media import WikimediaImageProvider


class MediaTests(unittest.TestCase):
    def test_wikimedia_images_include_lead_photo_credit_and_deduplication(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        lead = FakeResponse({
            "query": {"pages": [{
                "title": "Alice Chen",
                "thumbnail": {"source": "https://upload.wikimedia.org/lead-1400.jpg"},
                "original": {"source": "https://upload.wikimedia.org/lead.jpg"},
            }]}
        })
        commons = FakeResponse({
            "query": {"pages": [
                {
                    "title": "File:Alice Chen lead.jpg",
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/lead-commons-1400.jpg",
                        "url": "https://upload.wikimedia.org/lead.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Alice_Chen_lead.jpg",
                        "extmetadata": {},
                    }],
                },
                {
                    "title": "File:Alice Chen speaking.jpg",
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/speaking-1400.jpg",
                        "url": "https://upload.wikimedia.org/speaking.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Alice_Chen_speaking.jpg",
                        "extmetadata": {
                            "ImageDescription": {"value": "Alice Chen speaking"},
                            "Artist": {"value": "Example Photographer"},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        },
                    }],
                },
            ]}
        })
        with patch("app.backend.media.httpx.get", side_effect=[lead, commons]):
            images = WikimediaImageProvider().discover(
                "Alice Chen",
                ["https://en.wikipedia.org/wiki/Alice_Chen"],
                limit=4,
            )
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["source_label"], "Wikipedia")
        self.assertEqual(images[1]["author"], "Example Photographer")
        self.assertEqual(images[1]["license"], "CC BY-SA 4.0")


if __name__ == "__main__":
    unittest.main()
