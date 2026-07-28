import os
import unittest
from unittest.mock import patch

from gitlab_migrator.project_filters import (
    apply_project_exclusions,
    normalize_filter_path,
)


def project(path):
    return {"path_with_namespace": path}


class ProjectFilterTests(unittest.TestCase):
    def test_filter_paths_accept_source_destination_and_relative_forms(self):
        cases = {
            "appfuxion-my/erp/afx_erp": "appfuxion-my/erp/afx_erp",
            "appfuxion/erp/afx_erp": "appfuxion-my/erp/afx_erp",
            "erp/afx_erp": "appfuxion-my/erp/afx_erp",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_filter_path(
                        value, "appfuxion-my", "appfuxion"
                    ),
                    expected,
                )

    def test_exact_projects_and_group_subtrees_are_excluded(self):
        projects = [
            project("source-group/legacy/app"),
            project("source-group/archive/test"),
            project("source-group/archive/team/api"),
            project("source-group/deprecated/old"),
            project("source-group/archive-new/keep"),
            project("source-group/current/keep"),
        ]
        environment = {
            "EXCLUDE_PROJECTS": (
                "source-group/legacy/app, source-group/archive/test"
            ),
            "EXCLUDE_GROUPS": (
                "source-group/archive,source-group/deprecated/"
            ),
        }

        with patch.dict(os.environ, environment, clear=True):
            included, excluded = apply_project_exclusions(
                projects, "source-group"
            )

        self.assertEqual(
            [item["path_with_namespace"] for item in included],
            ["source-group/archive-new/keep", "source-group/current/keep"],
        )
        self.assertEqual(
            [item["path_with_namespace"] for item in excluded],
            [
                "source-group/legacy/app",
                "source-group/archive/test",
                "source-group/archive/team/api",
                "source-group/deprecated/old",
            ],
        )

    def test_exclusions_outside_source_group_are_rejected(self):
        with patch.dict(
            os.environ,
            {"EXCLUDE_GROUPS": "another-group/archive"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "must be SOURCE_GROUP"
            ):
                apply_project_exclusions([], "source-group")


if __name__ == "__main__":
    unittest.main()
