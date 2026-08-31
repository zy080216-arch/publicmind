import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.backend.cli import main
from app.backend.connectors.web import WebConnector


class CliTests(unittest.TestCase):
    def test_build_command_creates_vault_and_archive(self):
        html = b"<html><head><title>CLI fixture</title></head><body><main><p>Imported content.</p></main></body></html>"

        def opener(url, timeout):
            return html, {"content-type": "text/html; charset=utf-8"}, url

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with patch.object(WebConnector, "_open", staticmethod(opener)):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "build",
                            "--name",
                            "CLI Person",
                            "--url",
                            "https://example.com/fixture",
                            "--db",
                            str(root / "publicmind.db"),
                            "--output",
                            str(root / "exports"),
                        ]
                    )
            result = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(Path(result["vault"]).joinpath("00 Home.md").exists())
            self.assertTrue(Path(result["zip"]).exists())
            self.assertTrue(result["sources"][0]["inserted"])


if __name__ == "__main__":
    unittest.main()

