import unittest
from unittest.mock import patch

from app.backend.media import WikimediaImageProvider


class MediaTests(unittest.TestCase):
    def test_nickname_does_not_turn_time_pages_into_person_photos(self):
        provider = WikimediaImageProvider()
        urls = [
            "https://zh.wikipedia.org/wiki/Time",
            "https://github.com/tibo-openai",
            "https://youtube.com/watch?v=4qjEgPojjzM",
            "https://example.com/Tibo-interview",
        ]
        self.assertIsNone(provider._reference_page("Tibo", urls))
        with patch("app.backend.media.httpx.get") as get:
            images = provider.discover("Tibo", urls, limit=4)
        get.assert_not_called()
        self.assertEqual([item["source_label"] for item in images], ["GitHub", "YouTube"])
        self.assertFalse(any("Time" in str(item) for item in images))

    def test_commons_rejects_objects_without_the_person_name(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "query": {
                        "pages": [
                            {
                                "title": "File:Pocket watch.jpg",
                                "imageinfo": [{
                                    "mime": "image/jpeg",
                                    "thumburl": "https://upload.wikimedia.org/watch.jpg",
                                    "url": "https://upload.wikimedia.org/watch-original.jpg",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Pocket_watch.jpg",
                                    "extmetadata": {},
                                }],
                            },
                            {
                                "title": "File:Geological time scale.jpg",
                                "imageinfo": [{
                                    "mime": "image/jpeg",
                                    "thumburl": "https://upload.wikimedia.org/geological.jpg",
                                    "url": "https://upload.wikimedia.org/geological-original.jpg",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Geological_time_scale.jpg",
                                    "extmetadata": {},
                                }],
                            },
                        ]
                    }
                }

        with patch("app.backend.media.httpx.get", return_value=FakeResponse()):
            images = WikimediaImageProvider()._commons_images("Tibo", "Tibo", 4)
        self.assertEqual(images, [])

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
