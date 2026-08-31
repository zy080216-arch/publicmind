import tempfile
import unittest
import zipfile
from pathlib import Path

from app.backend.markdown import VaultExporter
from app.backend.models import Claim, Document, Person
from app.backend.normalization import content_hash


class ExportTests(unittest.TestCase):
    def test_vault_contains_parseable_frontmatter_and_no_broken_internal_links(self):
        with tempfile.TemporaryDirectory() as directory:
            content = "## Notes\n\nA source-backed note."
            document = Document(
                id="doc-1",
                person_id="person-1",
                source_id="source-1",
                source_url="https://example.com/note",
                source_type="article",
                title="A note / with unsafe characters",
                author="Author",
                published_at="2026-08-30",
                fetched_at="2026-08-30T00:00:00+00:00",
                content=content,
                content_hash=content_hash(content),
            )
            person = Person(id="person-1", name="Example Person", slug="example-person")
            claim = Claim(
                id="claim-1",
                person_id="person-1",
                document_id="doc-1",
                source_id="source-1",
                chunk_id="chunk-1",
                statement="Example Person argues for source-backed notes.",
                evidence_quote="A source-backed note.",
                claim_type="subject_claim_candidate",
                speaker="Example Person",
                attribution_confidence="high",
                source_role="subject_official",
                start_char=10,
                end_char=31,
                status="accepted",
            )
            vault, archive = VaultExporter(directory).export(person, [document], [claim])
            self.assertTrue((vault / "00 Home.md").exists())
            self.assertTrue(archive.exists())
            claims_text = (vault / "02 Claims.md").read_text(encoding="utf-8")
            self.assertIn("Example Person argues", claims_text)
            self.assertIn("> A source-backed note.", claims_text)
            self.assertIn("[[Sources/Web/", claims_text)

            markdown_files = {path.relative_to(vault).with_suffix("").as_posix() for path in vault.rglob("*.md")}
            for path in vault.rglob("*.md"):
                text = path.read_text(encoding="utf-8")
                if text.startswith("---"):
                    self.assertIn("content_hash:", text)
                    self.assertIn("source_platform: \"web\"", text)
                    self.assertIn("topics: []", text)
                    self.assertIn("entities: []", text)
                for target in __import__("re").findall(r"\[\[[^\]|]+(?:\|[^\]]+)?\]\]", text):
                    link = target[2:-2].split("|", 1)[0]
                    self.assertIn(link, markdown_files)

            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
                self.assertIn("example-person-vault/00 Home.md", names)
                self.assertIn("example-person-vault/01 Timeline.md", names)
                self.assertIn("example-person-vault/02 Claims.md", names)


if __name__ == "__main__":
    unittest.main()
