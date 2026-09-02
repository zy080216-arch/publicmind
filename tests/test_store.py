import unittest

from app.backend.store import Repository


class StoreTests(unittest.TestCase):
    def test_person_listing_and_source_status(self):
        repository = Repository(":memory:")
        first = repository.create_person("First Person")
        second = repository.create_person("Second Person")
        people = repository.list_persons()
        self.assertEqual([person.id for person in people], [second.id, first.id])

        corrected = repository.update_person_name(first.id, "First Person Corrected")
        self.assertEqual(corrected.name, "First Person Corrected")
        self.assertEqual(corrected.slug, "first-person-corrected")

        source = repository.add_source(first.id, "https://example.com/article")
        repository.update_source_status(source.id, "fetching")
        stored = repository.get_source(source.id)
        self.assertEqual(stored.status, "fetching")
        repository.close()


if __name__ == "__main__":
    unittest.main()
