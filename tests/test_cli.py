import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitlab_migrator import cli
from gitlab_migrator.constants import USER_CANCELLED


class CliTests(unittest.TestCase):
    def test_all_documented_commands_parse(self):
        parser = cli.build_parser()
        commands = [
            "migrate", "migrate-merge-requests", "migrate-variables",
            "migrate-group-variables", "migrate-hooks",
            "migrate-protection", "export-runners",
            "deploy-runners", "resume-runners", "export-pipelines",
            "replay-pipelines", "migrate-registry",
            "set-registry-retention", "purge-registry-images",
            "cancel-pipelines",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args([command]).command, command)

    def test_help_lists_commands_on_separate_lines(self):
        help_text = cli.build_parser().format_help()

        self.assertIn("COMMAND ...", help_text)
        self.assertNotIn("{migrate,migrate-merge-requests", help_text)
        self.assertIn(
            "migrate             Migrate repositories and recent merge requests.",
            help_text,
        )
        self.assertIn(
            "export-runners      Export source runner details.",
            help_text,
        )

    def test_runtime_directories_are_exported_to_children(self):
        with tempfile.TemporaryDirectory() as directory:
            args = cli.build_parser().parse_args([
                "--output-dir", directory,
                "--workspace-dir", directory,
                "export-runners",
            ])
            with patch.dict(os.environ, {}, clear=True):
                cli.configure_runtime(args)
                expected = str(Path(directory).resolve())
                self.assertEqual(
                    os.environ["GITLAB_MIGRATOR_OUTPUT_DIR"], expected
                )
                self.assertEqual(
                    os.environ["GITLAB_MIGRATOR_WORKSPACE_DIR"], expected
                )

    @patch("gitlab_migrator.cli.run_command")
    def test_cancelled_repository_migration_stops_second_phase(self, run):
        run.return_value = USER_CANCELLED
        args = cli.build_parser().parse_args(["migrate"])

        self.assertEqual(cli.dispatch(args), 0)
        run.assert_called_once_with("migrate", None)

    @patch("gitlab_migrator.cli.run_command")
    def test_migrate_yes_is_forwarded_to_repository_phase(self, run):
        run.side_effect = [0, 0]
        args = cli.build_parser().parse_args(["migrate", "--yes"])

        self.assertEqual(cli.dispatch(args), 0)
        self.assertEqual(run.call_args_list[0].args, ("migrate", ["--yes"]))
        self.assertEqual(
            run.call_args_list[1].args,
            ("migrate-merge-requests", ["--execute", "--days", "30"]),
        )

    @patch("gitlab_migrator.cli.subprocess.run")
    def test_commands_run_as_installed_modules(self, run):
        run.return_value.returncode = 0
        self.assertEqual(cli.run_command("export-runners"), 0)
        self.assertEqual(run.call_args.args[0][1:3], [
            "-m", "gitlab_migrator.commands.export_runners"
        ])


if __name__ == "__main__":
    unittest.main()
