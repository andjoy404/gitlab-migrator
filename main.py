#!/usr/bin/env python3
"""Convenient launcher for repository and runner migration commands."""

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
OUTPUT = ROOT / "output"


def run_script(script, arguments=None):
    command = [sys.executable, str(SCRIPTS / script)]

    if arguments:
        command.extend(arguments)

    return subprocess.run(command, cwd=ROOT).returncode


def interactive_menu():
    print("GitLab Migrator")
    print()
    print("1. Migrate repositories")
    print("2. Export runners")
    print("3. Deploy paused runners")
    print("4. Resume deployed runners")
    print("5. Export pipeline history")
    print("6. Replay pipelines as new runs")
    print("7. Migrate container registry")
    print("8. Find active destination pipelines (dry run)")
    print("9. Cancel")
    print()

    choice = input("Choose an action: ").strip()

    actions = {
        "1": ("migrate.py", []),
        "2": ("export_runners.py", []),
        "3": (
            "deploy_runner_registration.py",
            ["--plan", str(OUTPUT / "runners.json"), "--keys-dir", "keys"],
        ),
        "4": ("deploy_runner_registration.py", ["--resume"]),
        "5": ("pipeline_history.py", []),
        "6": ("pipeline_history.py", ["--replay", "--execute"]),
        "7": ("migrate_container_registry.py", ["--execute"]),
        "8": ("cancel_pipelines.py", []),
    }

    if choice == "9":
        return 0

    if choice == "1":
        result = run_script("migrate.py")
        if result:
            return result
        return run_script(
            "migrate_merge_requests.py",
            ["--execute", "--days", "30"],
        )

    if choice not in actions:
        print("Invalid selection.")
        return 2

    script, arguments = actions[choice]
    return run_script(script, arguments)


def main():
    parser = argparse.ArgumentParser(
        description="GitLab migration launcher",
    )
    subcommands = parser.add_subparsers(dest="command")

    migrate = subcommands.add_parser("migrate")
    migrate.add_argument(
        "--days",
        type=float,
        default=30,
        help="Migrate merge requests updated during the last N days.",
    )
    migrate.add_argument(
        "--reset-merge-requests",
        action="store_true",
        help="Clear merge-request checkpoints and retry the selected window.",
    )
    migrate_merge_requests = subcommands.add_parser("migrate-merge-requests")
    migrate_merge_requests.add_argument("--days", type=float, default=30)
    migrate_merge_requests.add_argument("--reset", action="store_true")
    subcommands.add_parser("export-runners")

    deploy = subcommands.add_parser("deploy-runners")
    deploy.add_argument("--plan", default=str(OUTPUT / "runners.json"))
    deploy.add_argument("--keys-dir", default="keys")
    deploy.add_argument("--port", type=int, default=22)

    subcommands.add_parser("resume-runners")
    export_pipelines = subcommands.add_parser("export-pipelines")
    export_pipelines.add_argument("--days", type=float, default=30)
    export_pipelines.add_argument("--reset", action="store_true")
    replay = subcommands.add_parser("replay-pipelines")
    replay.add_argument("--file", default=str(OUTPUT / "pipeline_history.json"))
    replay.add_argument("--all-records", action="store_true")
    migrate_registry = subcommands.add_parser("migrate-registry")
    migrate_registry.add_argument("--days", type=float, default=30)
    migrate_registry.add_argument("--reset", action="store_true")
    registry_retention = subcommands.add_parser("set-registry-retention")
    registry_retention.add_argument(
        "--day",
        "--days",
        dest="days",
        type=int,
        default=7,
    )
    registry_retention.add_argument("--execute", action="store_true")
    registry_retention.add_argument("--project")
    registry_retention.add_argument("--reset", action="store_true")
    purge_registry = subcommands.add_parser("purge-registry-images")
    purge_registry.add_argument("--days", type=float, default=7)
    purge_registry.add_argument("--execute", action="store_true")
    purge_registry.add_argument("--project")
    purge_registry.add_argument("--include-latest", action="store_true")
    purge_registry.add_argument("--all", action="store_true")
    purge_registry.add_argument("--reset", action="store_true")
    cancel = subcommands.add_parser("cancel-pipelines")
    cancel.add_argument("--execute", action="store_true")
    cancel.add_argument("--project")
    cancel.add_argument("--hours", type=float, default=24)
    cancel.add_argument("--include-manual", action="store_true")

    args = parser.parse_args()

    if args.command is None:
        return interactive_menu()

    if args.command == "migrate":
        result = run_script("migrate.py")
        if result:
            return result

        arguments = ["--execute", "--days", str(args.days)]
        if args.reset_merge_requests:
            arguments.append("--reset")
        return run_script("migrate_merge_requests.py", arguments)

    if args.command == "migrate-merge-requests":
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_script("migrate_merge_requests.py", arguments)

    if args.command == "export-runners":
        return run_script("export_runners.py")

    if args.command == "deploy-runners":
        return run_script(
            "deploy_runner_registration.py",
            [
                "--plan",
                args.plan,
                "--keys-dir",
                args.keys_dir,
                "--port",
                str(args.port),
            ],
        )

    if args.command == "resume-runners":
        return run_script("deploy_runner_registration.py", ["--resume"])

    if args.command == "export-pipelines":
        arguments = ["--days", str(args.days)]

        if args.reset:
            arguments.append("--reset")

        return run_script("pipeline_history.py", arguments)

    if args.command == "replay-pipelines":
        arguments = ["--replay", "--execute", "--file", args.file]

        if args.all_records:
            arguments.append("--all-records")

        return run_script(
            "pipeline_history.py",
            arguments,
        )

    if args.command == "migrate-registry":
        arguments = ["--execute", "--days", str(args.days)]

        if args.reset:
            arguments.append("--reset")

        return run_script("migrate_container_registry.py", arguments)

    if args.command == "set-registry-retention":
        arguments = ["--day", str(args.days)]

        if args.execute:
            arguments.append("--execute")

        if args.project:
            arguments.extend(["--project", args.project])

        if args.reset:
            arguments.append("--reset")

        return run_script("set_registry_retention.py", arguments)

    if args.command == "purge-registry-images":
        arguments = ["--days", str(args.days)]

        if args.execute:
            arguments.append("--execute")

        if args.project:
            arguments.extend(["--project", args.project])

        if args.include_latest:
            arguments.append("--include-latest")

        if args.all:
            arguments.append("--all")

        if args.reset:
            arguments.append("--reset")

        return run_script("purge_registry_images.py", arguments)

    if args.command == "cancel-pipelines":
        arguments = ["--hours", str(args.hours)]

        if args.execute:
            arguments.append("--execute")

        if args.project:
            arguments.extend(["--project", args.project])

        if args.include_manual:
            arguments.append("--include-manual")

        return run_script("cancel_pipelines.py", arguments)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
