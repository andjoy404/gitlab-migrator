#!/usr/bin/env python3
"""Configure destination projects with a registry cleanup policy."""

import argparse
import datetime
import json
import os

try:
    from .bootstrap import configure_import_path
except ImportError:
    from bootstrap import configure_import_path

configure_import_path()

from gitlab_migrator.config import (
    DEST_ROOT_GROUP,
    DEST_TOKEN,
    DEST_URL,
    validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


RESULTS_FILE = output_path("registry_retention_results.json")
ERROR_FILE = output_path("registry_retention_errors.log")

SUPPORTED_RETENTION_DAYS = (1, 3, 7, 14, 30, 60, 90, 180, 365, 730, 1095)


def retention_policy(days):
    return {
        "enabled": True,
        "cadence": "1d",
        "older_than": f"{days}d",
        "keep_n": 1,
        "name_regex_delete": ".*",
        "name_regex_keep": "",
    }


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_results():
    if not RESULTS_FILE.exists():
        return []
    value = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError(f"{RESULTS_FILE} must contain a JSON list")
    return value


def atomic_write_json(value):
    temporary = RESULTS_FILE.with_name(RESULTS_FILE.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(RESULTS_FILE)


def append_error(entry):
    record = dict(entry)
    record["recorded_at"] = utc_now()
    with ERROR_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def policy_matches(project, policy):
    current = project.get("container_expiration_policy") or {}
    delete_regex = (
        current.get("name_regex_delete")
        if current.get("name_regex_delete") is not None
        else current.get("name_regex")
    )
    return (
        current.get("enabled") is True
        and current.get("cadence") == policy["cadence"]
        and current.get("older_than") == policy["older_than"]
        and current.get("keep_n") == policy["keep_n"]
        and delete_regex == policy["name_regex_delete"]
        and (current.get("name_regex_keep") or "") == ""
    )


def select_projects(projects, project_path):
    if not project_path:
        return projects

    selected = [
        project
        for project in projects
        if project["path_with_namespace"] == project_path
    ]
    if not selected:
        raise RuntimeError(
            f"Destination project not found below {DEST_ROOT_GROUP}: {project_path}"
        )
    return selected


def configure(execute, project_path, reset, days):
    if reset:
        RESULTS_FILE.unlink(missing_ok=True)
        ERROR_FILE.unlink(missing_ok=True)

    results = load_results()
    policy = retention_policy(days)
    api = GitLabAPI(DEST_URL, DEST_TOKEN)
    updated = 0
    already_configured = 0
    planned = 0
    failed = 0

    try:
        projects = select_projects(
            api.list_projects(DEST_ROOT_GROUP),
            project_path,
        )
        mode = "EXECUTE" if execute else "DRY RUN"
        print(f"Mode: {mode}")
        print(f"Found {len(projects)} destination projects.")
        print(
            "Policy: run daily; match all tag names; remove tags older than "
            f"{days} days; keep the newest tag per image."
        )
        print(
            "GitLab always excludes latest, protected tags, and immutable tags."
        )
        print()

        for index, summary in enumerate(projects, start=1):
            path = summary["path_with_namespace"]
            prefix = f"[Project {index}/{len(projects)}] {path}"
            print(prefix, flush=True)

            try:
                project = api.get_project(summary["id"])
                if policy_matches(project, policy):
                    already_configured += 1
                    print("  Already configured.", flush=True)
                    continue

                if not execute:
                    planned += 1
                    print(
                        f"  Would enable {days}-day retention.",
                        flush=True,
                    )
                    continue

                updated_project = api.update_project(
                    project["id"],
                    container_expiration_policy_attributes=policy,
                )
                if not policy_matches(updated_project, policy):
                    raise RuntimeError(
                        "GitLab accepted the update but returned a different "
                        "container expiration policy."
                    )

                record = {
                    "project_id": project["id"],
                    "project": path,
                    "policy": policy,
                    "status": "configured",
                    "configured_at": utc_now(),
                }
                results.append(record)
                atomic_write_json(results)
                updated += 1
                print("  Configured (checkpoint saved).", flush=True)
            except Exception as error:
                failed += 1
                append_error({
                    "project_id": summary.get("id"),
                    "project": path,
                    "stage": "set_registry_retention",
                    "error": str(error),
                })
                print(f"  Failed: {error}", flush=True)

        print()
        if execute:
            print(
                f"Registry retention complete: {updated} configured, "
                f"{already_configured} already configured, {failed} failed."
            )
            print(f"Results: {RESULTS_FILE}")
        else:
            print(
                f"Dry run complete: {planned} would change, "
                f"{already_configured} already configured, {failed} failed."
            )
            print("Run again with --execute to apply the policy.")

        if failed:
            print(f"Failures: {ERROR_FILE}")
        return 1 if failed else 0
    finally:
        api.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--day",
        "--days",
        dest="days",
        type=int,
        choices=SUPPORTED_RETENTION_DAYS,
        default=7,
        help="Delete tags older than this many days (default: 7).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the policy. Without this option, only show a dry run.",
    )
    parser.add_argument(
        "--project",
        help="Limit the operation to one destination path_with_namespace.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear prior result/error files before this run.",
    )
    args = parser.parse_args()
    validate()
    return configure(args.execute, args.project, args.reset, args.days)


if __name__ == "__main__":
    raise SystemExit(main())
