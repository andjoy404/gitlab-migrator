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
    return Path(os.getenv("GITLAB_MIGRATOR_OUTPUT_DIR", "data/reports"))


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


def add_migrate_all_options(parser):
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument(
        "--reset-mr",
        "--reset-merge-requests",
        dest="reset_merge_requests",
        action="store_true",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear repository checkpoints and migrate every repository again.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the source and destination confirmation prompt.",
    )


def add_migrate_mr_options(parser):
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument("--reset", action="store_true")


def add_runner_deploy_options(parser):
    parser.add_argument("--plan")
    parser.add_argument("--keys-dir")
    parser.add_argument("--port", type=int, default=22)


def add_pipeline_export_options(parser):
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument("--reset", action="store_true")


def add_pipeline_replay_options(parser):
    parser.add_argument("--file")
    parser.add_argument("--all-records", action="store_true")


def add_pipeline_cancel_options(parser):
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--include-manual", action="store_true")


def add_registry_migrate_options(parser):
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument("--reset", action="store_true")


def add_registry_retention_options(parser):
    parser.add_argument("--day", "--days", dest="days", type=int, default=7)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--reset", action="store_true")


def add_registry_purge_options(parser):
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--include-latest", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--reset", action="store_true")


def leaf(subparsers, name, dispatch_command, help):
    parser = subparsers.add_parser(name, help=help)
    parser.set_defaults(dispatch_command=dispatch_command)
    return parser


def build_parser():
    parser = argparse.ArgumentParser(description="GitLab migration launcher")
    add_runtime_options(parser)
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", title="commands"
    )

    migrate = commands.add_parser("migrate", help="Run migration operations.")
    migrate.set_defaults(dispatch_command="migrate")
    add_migrate_all_options(migrate)
    migrate_commands = migrate.add_subparsers(dest="migrate_command", metavar="TARGET")
    add_migrate_all_options(leaf(
        migrate_commands, "all", "migrate",
        "Migrate repositories and recent merge requests.",
    ))
    add_migrate_mr_options(leaf(
        migrate_commands, "mr", "migrate-merge-requests",
        "Migrate only recent merge requests.",
    ))
    variables = leaf(
        migrate_commands, "vars", "migrate-variables",
        "Migrate project or group CI/CD variables.",
    )
    variable_scopes = variables.add_subparsers(dest="variable_scope", metavar="SCOPE")
    leaf(
        variable_scopes, "group", "migrate-group-variables",
        "Migrate group CI/CD variables.",
    )
    leaf(migrate_commands, "hooks", "migrate-hooks", "Migrate project webhooks.")
    branch = migrate_commands.add_parser(
        "branch", help="Migrate branch-related settings."
    )
    branch_commands = branch.add_subparsers(dest="branch_command", metavar="SETTING")
    leaf(
        branch_commands, "protection", "migrate-protection",
        "Migrate branch protection rules.",
    )

    runners = commands.add_parser("runners", help="Manage runner migration.")
    runner_commands = runners.add_subparsers(dest="runner_command", metavar="ACTION")
    leaf(runner_commands, "export", "export-runners", "Export source runner details.")
    add_runner_deploy_options(leaf(
        runner_commands, "deploy", "deploy-runners",
        "Deploy paused runners on their existing hosts.",
    ))
    leaf(
        runner_commands, "resume", "resume-runners",
        "Enable successfully deployed runners.",
    )

    pipelines = commands.add_parser("pipelines", help="Manage pipeline operations.")
    pipeline_commands = pipelines.add_subparsers(
        dest="pipeline_command", metavar="ACTION"
    )
    add_pipeline_export_options(leaf(
        pipeline_commands, "export", "export-pipelines",
        "Export recent pipeline audit history.",
    ))
    add_pipeline_replay_options(leaf(
        pipeline_commands, "replay", "replay-pipelines",
        "Replay archived pipelines as new runs.",
    ))
    add_pipeline_cancel_options(leaf(
        pipeline_commands, "cancel", "cancel-pipelines",
        "Preview or cancel active pipelines and jobs.",
    ))

    registry = commands.add_parser("registry", help="Manage container registry operations.")
    registry_commands = registry.add_subparsers(dest="registry_command", metavar="ACTION")
    add_registry_migrate_options(leaf(
        registry_commands, "migrate", "migrate-registry",
        "Copy recent container-registry images.",
    ))
    add_registry_retention_options(leaf(
        registry_commands, "retention", "set-registry-retention",
        "Configure registry cleanup policies.",
    ))
    add_registry_purge_options(leaf(
        registry_commands, "purge", "purge-registry-images",
        "Preview or delete registry image tags.",
    ))

    # Pre-0.5 command names remain available for scripts and automation.
    legacy = commands.add_parser("migrate-merge-requests", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="migrate-merge-requests")
    add_migrate_mr_options(legacy)
    for name, target in (
        ("migrate-variables", "migrate-variables"),
        ("migrate-group-variables", "migrate-group-variables"),
        ("migrate-hooks", "migrate-hooks"),
        ("migrate-protection", "migrate-protection"),
        ("export-runners", "export-runners"),
        ("resume-runners", "resume-runners"),
    ):
        commands.add_parser(name, help=argparse.SUPPRESS).set_defaults(
            dispatch_command=target
        )
    legacy = commands.add_parser("deploy-runners", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="deploy-runners")
    add_runner_deploy_options(legacy)
    legacy = commands.add_parser("export-pipelines", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="export-pipelines")
    add_pipeline_export_options(legacy)
    legacy = commands.add_parser("replay-pipelines", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="replay-pipelines")
    add_pipeline_replay_options(legacy)
    legacy = commands.add_parser("cancel-pipelines", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="cancel-pipelines")
    add_pipeline_cancel_options(legacy)
    legacy = commands.add_parser("migrate-registry", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="migrate-registry")
    add_registry_migrate_options(legacy)
    legacy = commands.add_parser("set-registry-retention", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="set-registry-retention")
    add_registry_retention_options(legacy)
    legacy = commands.add_parser("purge-registry-images", help=argparse.SUPPRESS)
    legacy.set_defaults(dispatch_command="purge-registry-images")
    add_registry_purge_options(legacy)
    # argparse does not honor SUPPRESS for subparser help entries. Keep legacy
    # parsers callable without advertising them in the primary command list.
    visible_commands = {"migrate", "runners", "pipelines", "registry"}
    commands._choices_actions = [
        action for action in commands._choices_actions
        if action.dest in visible_commands
    ]
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
    command = getattr(args, "dispatch_command", None)
    if command == "migrate":
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
    if command == "migrate-merge-requests":
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(command, arguments)
    if command in {
        "export-runners", "migrate-variables", "migrate-group-variables",
        "migrate-hooks", "migrate-protection",
    }:
        return run_command(command)
    if command == "deploy-runners":
        return run_command(command, [
            "--plan", args.plan or str(output_dir() / "runners.json"),
            "--keys-dir", args.keys_dir or "data/keys",
            "--port", str(args.port),
        ])
    if command == "resume-runners":
        return run_command("deploy-runners", ["--resume"])
    if command == "export-pipelines":
        arguments = ["--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(command, arguments)
    if command == "replay-pipelines":
        arguments = [
            "--replay", "--execute", "--file",
            args.file or str(output_dir() / "pipeline_history.json"),
        ]
        if args.all_records:
            arguments.append("--all-records")
        return run_command("export-pipelines", arguments)
    if command == "migrate-registry":
        arguments = ["--execute", "--days", str(args.days)]
        if args.reset:
            arguments.append("--reset")
        return run_command(command, arguments)
    if command == "set-registry-retention":
        arguments = ["--day", str(args.days)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("reset", "--reset")
        ])
    elif command == "purge-registry-images":
        arguments = ["--days", str(args.days)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("include_latest", "--include-latest"),
            ("all", "--all"), ("reset", "--reset"),
        ])
    elif command == "cancel-pipelines":
        arguments = ["--hours", str(args.hours)]
        arguments += optional_flags(args, [
            ("execute", "--execute"), ("include_manual", "--include-manual")
        ])
    else:
        return 2
    if getattr(args, "project", None):
        arguments.extend(["--project", args.project])
    return run_command(command, arguments)


def main():
    args = build_parser().parse_args()
    configure_runtime(args)
    if args.command is None:
        build_parser().print_help()
        return 0
    if not getattr(args, "dispatch_command", None):
        build_parser().parse_args([args.command, "--help"])
    return dispatch(args)
