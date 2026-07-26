"""Public command-line interface for GitLab Migrator."""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from . import __version__
from .constants import USER_CANCELLED


MODULES = {
    "migrate": "gitlab_migrator.commands.migrate",
    "migrate-merge-requests": "gitlab_migrator.commands.migrate_merge_requests",
    "migrate-variables": "gitlab_migrator.commands.migrate_variables",
    "migrate-group-variables": "gitlab_migrator.commands.migrate_group_variables",
    "migrate-hooks": "gitlab_migrator.commands.migrate_hooks",
    "migrate-protection": "gitlab_migrator.commands.migrate_protection",
    "export-runners": "gitlab_migrator.commands.export_runners",
    "deploy-runners": "gitlab_migrator.commands.deploy_runner_registration",
    "export-pipelines": "gitlab_migrator.commands.pipeline_history",
    "migrate-registry": "gitlab_migrator.commands.migrate_container_registry",
    "set-registry-retention": "gitlab_migrator.commands.set_registry_retention",
    "purge-registry-images": "gitlab_migrator.commands.purge_registry_images",
    "cancel-pipelines": "gitlab_migrator.commands.cancel_pipelines",
}


def output_dir():
    return Path(os.getenv("GITLAB_MIGRATOR_OUTPUT_DIR", "output"))


def run_command(name, arguments=None):
    command = [sys.executable, "-m", MODULES[name]]
    command.extend(arguments or [])
    process = subprocess.Popen(
        command,
        start_new_session=os.name == "posix",
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 130


def add_runtime_options(parser):
    parser.add_argument("--env-file")
    parser.add_argument("--output-dir")
    parser.add_argument("--workspace-dir")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="GitLab migration launcher")
    add_runtime_options(parser)
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", title="commands"
    )

    migrate = commands.add_parser("migrate", help="Migrate repositories and recent merge requests.")
    migrate.add_argument("--days", type=float, default=30)
    migrate.add_argument("--reset-merge-requests", action="store_true")
    migrate.add_argument(
        "--reset",
        action="store_true",
        help="Clear repository checkpoints and migrate every repository again.",
    )
    migrate.add_argument(
        "--yes",
        action="store_true",
        help="Skip the source and destination confirmation prompt.",
    )
    merge_requests = commands.add_parser("migrate-merge-requests", help="Migrate only recent merge requests.")
    merge_requests.add_argument("--days", type=float, default=30)
    merge_requests.add_argument("--reset", action="store_true")
    commands.add_parser("migrate-variables", help="Migrate project CI/CD variables.")
    commands.add_parser("migrate-group-variables", help="Migrate group CI/CD variables.")
    commands.add_parser("migrate-hooks", help="Migrate project webhooks.")
    commands.add_parser("migrate-protection", help="Migrate branch protection rules.")
    commands.add_parser("export-runners", help="Export source runner details.")

    deploy = commands.add_parser("deploy-runners", help="Deploy paused runners on their existing hosts.")
    deploy.add_argument("--plan")
    deploy.add_argument("--keys-dir")
    deploy.add_argument("--port", type=int, default=22)
    commands.add_parser("resume-runners", help="Enable successfully deployed runners.")

    export = commands.add_parser("export-pipelines", help="Export recent pipeline audit history.")
    export.add_argument("--days", type=float, default=30)
    export.add_argument("--reset", action="store_true")
    replay = commands.add_parser("replay-pipelines", help="Replay archived pipelines as new runs.")
    replay.add_argument("--file")
    replay.add_argument("--all-records", action="store_true")

    registry = commands.add_parser("migrate-registry", help="Copy recent container-registry images.")
    registry.add_argument("--days", type=float, default=30)
    registry.add_argument("--reset", action="store_true")
    retention = commands.add_parser("set-registry-retention", help="Configure registry cleanup policies.")
    retention.add_argument("--day", "--days", dest="days", type=int, default=7)
    retention.add_argument("--execute", action="store_true")
    retention.add_argument("--project")
    retention.add_argument("--reset", action="store_true")
    purge = commands.add_parser("purge-registry-images", help="Preview or delete registry image tags.")
    purge.add_argument("--days", type=float, default=7)
    purge.add_argument("--execute", action="store_true")
    purge.add_argument("--project")
    purge.add_argument("--include-latest", action="store_true")
    purge.add_argument("--all", action="store_true")
    purge.add_argument("--reset", action="store_true")

    cancel = commands.add_parser("cancel-pipelines", help="Preview or cancel active pipelines and jobs.")
    cancel.add_argument("--execute", action="store_true")
    cancel.add_argument("--project")
    cancel.add_argument("--hours", type=float, default=24)
    cancel.add_argument("--include-manual", action="store_true")
    return parser


def configure_runtime(args):
    values = {
        "GITLAB_MIGRATOR_ENV_FILE": args.env_file,
        "GITLAB_MIGRATOR_OUTPUT_DIR": args.output_dir,
        "GITLAB_MIGRATOR_WORKSPACE_DIR": args.workspace_dir,
    }
    for name, value in values.items():
        if value:
            os.environ[name] = str(Path(value).expanduser().resolve())


def optional_flags(args, pairs):
    return [flag for attribute, flag in pairs if getattr(args, attribute)]


def dispatch(args):
    if args.command == "migrate":
        repository_arguments = []
        if args.yes:
            repository_arguments.append("--yes")
        if args.reset:
            repository_arguments.append("--reset")
        result = run_command("migrate", repository_arguments or None)
        if result == USER_CANCELLED:
            return 0
        if result:
            return result
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset_merge_requests:
            arguments.append("--reset")
        return run_command("migrate-merge-requests", arguments)
    if args.command == "migrate-merge-requests":
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(args.command, arguments)
    if args.command in {
        "export-runners", "migrate-variables", "migrate-group-variables",
        "migrate-hooks", "migrate-protection",
    }:
        return run_command(args.command)
    if args.command == "deploy-runners":
        return run_command(args.command, [
            "--plan", args.plan or str(output_dir() / "runners.json"),
            "--keys-dir", args.keys_dir or "keys",
            "--port", str(args.port),
        ])
    if args.command == "resume-runners":
        return run_command("deploy-runners", ["--resume"])
    if args.command == "export-pipelines":
        arguments = ["--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(args.command, arguments)
    if args.command == "replay-pipelines":
        arguments = [
            "--replay", "--execute", "--file",
            args.file or str(output_dir() / "pipeline_history.json"),
        ]
        if args.all_records:
            arguments.append("--all-records")
        return run_command("export-pipelines", arguments)
    if args.command == "migrate-registry":
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(args.command, arguments)
    if args.command == "set-registry-retention":
        arguments = ["--day", str(args.days)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("reset", "--reset")
        ])
    elif args.command == "purge-registry-images":
        arguments = ["--days", str(args.days)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("include_latest", "--include-latest"),
            ("all", "--all"), ("reset", "--reset"),
        ])
    elif args.command == "cancel-pipelines":
        arguments = ["--hours", str(args.hours)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("include_manual", "--include-manual")
        ])
    else:
        return 2
    if getattr(args, "project", None):
        arguments.extend(["--project", args.project])
    return run_command(args.command, arguments)


def main():
    args = build_parser().parse_args()
    configure_runtime(args)
    if args.command is None:
        build_parser().print_help()
        return 0
    return dispatch(args)
