import asyncio
import unittest

from app.backend.connectors.base import ConnectorRegistry, SourceConnector
from app.backend.models import RawDocument
from app.backend.pipeline import IngestPipeline
from app.backend.store import Repository


class FakeConnector(SourceConnector):
    platform = "web"

    def __init__(self):
        self.calls = 0

    def can_handle(self, url):
        return url.startswith("https://fixture/")

    async def fetch(self, url):
        self.calls += 1
        return RawDocument(
            source_url=url,
            source_type="article",
            title="Fixture article",
            raw_text="# Fixture\n\nA source-backed paragraph.",
            metadata={"fixture": True},
        )


class PipelineTests(unittest.TestCase):
    def test_ingest_is_idempotent_for_unchanged_url(self):
        repository = Repository(":memory:")
        person = repository.create_person("Test Person")
        connector = FakeConnector()
        pipeline = IngestPipeline(repository, ConnectorRegistry([connector]))
        first = asyncio.run(pipeline.ingest(person.id, "https://fixture/article"))
        second = asyncio.run(pipeline.ingest(person.id, "https://fixture/article"))
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual(connector.calls, 2)
        self.assertEqual(len(repository.list_documents(person.id)), 1)
        self.assertEqual(repository.get_source(first.source.id).status, "completed")
        repository.close()

    def test_changed_content_hash_creates_a_new_revision(self):
        repository = Repository(":memory:")
        person = repository.create_person("Revision Person")
        connector = FakeConnector()
        pipeline = IngestPipeline(repository, ConnectorRegistry([connector]))
        asyncio.run(pipeline.ingest(person.id, "https://fixture/one"))

        async def changed_fetch(url):
            return RawDocument(source_url=url, source_type="article", title="Changed", raw_text="new content")

        connector.fetch = changed_fetch
        result = asyncio.run(pipeline.ingest(person.id, "https://fixture/one"))
        self.assertTrue(result.inserted)
        self.assertEqual(len(repository.list_documents(person.id)), 2)
        repository.close()


if __name__ == "__main__":
    unittest.main()
