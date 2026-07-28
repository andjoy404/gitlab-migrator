import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.repository_progress import (
    load_repository_progress,
    save_repository_progress,
    upsert_repository_result,
)


class RepositoryProgressTests(unittest.TestCase):
    def test_upsert_replaces_existing_source_path(self):
        results = [
            {"source_path": "group/app", "completed_at": "old"},
            {"source_path": "group/other", "completed_at": "keep"},
        ]
        updated = upsert_repository_result(
            results,
            {"source_path": "group/app", "completed_at": "new"},
        )

        self.assertEqual(updated, [
            {"source_path": "group/other", "completed_at": "keep"},
            {"source_path": "group/app", "completed_at": "new"},
        ])

    def setUp(self):
        self.context = {
            "source_url": "https://source.example.com",
            "source_group": "source",
            "destination_url": "https://destination.example.com",
            "destination_root_group": "destination",
        }

    def test_round_trip_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository_migration_results.json"
            results = [{"source_path": "source/project", "status": "completed"}]

            save_repository_progress(path, self.context, results)
            self.assertEqual(
                load_repository_progress(path, self.context),
                results,
            )
            self.assertEqual(
                load_repository_progress(path, self.context, reset=True),
                [],
            )
            self.assertFalse(path.exists())

    def test_context_mismatch_requires_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository_migration_results.json"
            save_repository_progress(path, self.context, [])

            with self.assertRaisesRegex(RuntimeError, "migrate --reset"):
                load_repository_progress(path, {"source_url": "different"})


if __name__ == "__main__":
    unittest.main()
