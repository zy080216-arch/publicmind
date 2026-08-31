import asyncio
import unittest
from unittest.mock import patch

from app.backend.connectors.web import WebConnector, html_to_markdown
from app.backend.connectors.youtube import YoutubeConnector, parse_subtitle


class ConnectorTests(unittest.TestCase):
    def test_connector_url_contract(self):
        web = WebConnector()
        youtube = YoutubeConnector()
        self.assertTrue(web.can_handle("https://example.com/post"))
        self.assertFalse(web.can_handle("not-a-url"))
        self.assertTrue(youtube.can_handle("https://youtu.be/abc123"))
        self.assertTrue(youtube.can_handle("https://www.youtube.com/watch?v=abc123"))
        self.assertFalse(youtube.can_handle("https://example.com/video"))

    def test_web_fallback_extracts_article_and_metadata(self):
        html = """
        <html><head><title>Ignored? Article</title>
        <meta name="author" content="Ada" />
        <meta property="article:published_time" content="2026-08-30" />
        </head><body><nav>Menu</nav><article><h1>Article title</h1>
        <p>First paragraph.</p><p>Second paragraph with <strong>detail</strong>.</p>
        </article><footer>Cookie</footer></body></html>
        """
        with patch("app.backend.connectors.web._extract_with_trafilatura", return_value=None):
            title, markdown, metadata = html_to_markdown(html, "https://example.com/article")
        self.assertEqual(title, "Ignored? Article")
        self.assertIn("# Article title", markdown)
        self.assertIn("First paragraph.", markdown)
        self.assertIn("Second paragraph with detail.", markdown)
        self.assertNotIn("Cookie", markdown)
        self.assertEqual(metadata["author"], "Ada")

    def test_web_fetch_can_run_with_injected_opener(self):
        html = b"<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"

        def opener(url, timeout):
            return html, {"content-type": "text/html; charset=utf-8"}, url

        raw = asyncio.run(WebConnector(opener=opener).fetch("https://example.com/test"))
        self.assertEqual(raw.title, "Test")
        self.assertEqual(raw.source_type, "article")
        self.assertIn("Hello world", raw.raw_text)

    def test_vtt_parser_preserves_timestamps(self):
        vtt = """WEBVTT

00:00.000 --> 00:02.500
Hello <b>world</b>

00:02.500 --> 00:05.000
Second line
"""
        segments = parse_subtitle(vtt)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start, 0.0)
        self.assertEqual(segments[0].end, 2.5)
        self.assertEqual(segments[0].text, "Hello world")


if __name__ == "__main__":
    unittest.main()
