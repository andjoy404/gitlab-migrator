#!/usr/bin/env python3
"""Delete destination registry tags with old manifest creation timestamps."""

import argparse
import base64
import datetime
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

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


RESULTS_FILE = output_path("registry_purge_results.json")
ERROR_FILE = output_path("registry_purge_errors.log")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_timestamp(value):
    if not value:
        return None
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


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


def checkpoint_key(project_id, repository_id, tag):
    return json.dumps(
        [
            project_id,
            repository_id,
            tag.get("name"),
            tag.get("digest"),
            tag.get("raw_created_at") or tag.get("created_at"),
        ],
        separators=(",", ":"),
    )


def authfile(registry, username, token):
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
    file = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
    json.dump({"auths": {registry: {"auth": encoded}}}, file)
    file.close()
    os.chmod(file.name, 0o600)
    return Path(file.name)


def raw_image_created(location, auth_file):
    process = subprocess.run(
        [
            "skopeo",
            "inspect",
            "--authfile",
            str(auth_file),
            f"docker://{location}",
        ],
        text=True,
        capture_output=True,
    )
    if process.returncode:
        message = process.stderr.strip() or "skopeo inspect failed"
        raise RuntimeError(message)
    metadata = json.loads(process.stdout)
    return metadata.get("Created")


def select_projects(projects, project_path):
    if not project_path:
        return projects
    selected = [
        project for project in projects
        if project["path_with_namespace"] == project_path
    ]
    if not selected:
        raise RuntimeError(
            f"Destination project not found below {DEST_ROOT_GROUP}: {project_path}"
        )
    return selected


def purge(days, execute, project_path, include_latest, reset, purge_all):
    if reset:
        RESULTS_FILE.unlink(missing_ok=True)
        ERROR_FILE.unlink(missing_ok=True)

    results = load_results()
    completed = {
        item["checkpoint_key"] for item in results
        if item.get("status") == "deleted" and item.get("checkpoint_key")
    }
    cutoff = None if purge_all else (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    )
    if not purge_all and not shutil.which("skopeo"):
        raise RuntimeError("skopeo is required. Install it before running this script.")
    required = [] if purge_all else [
        "DEST_REGISTRY",
        "DEST_REGISTRY_USER",
        "DEST_REGISTRY_TOKEN",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing registry variables: " + ", ".join(missing))

    api = GitLabAPI(DEST_URL, DEST_TOKEN)
    registry_auth = None
    if not purge_all:
        registry_auth = authfile(
            os.environ["DEST_REGISTRY"],
            os.environ["DEST_REGISTRY_USER"],
            os.environ["DEST_REGISTRY_TOKEN"],
        )
    repositories_seen = 0
    tags_seen = 0
    eligible = 0
    deleted = 0
    checkpointed = 0
    skipped_latest = 0
    skipped_protected = 0
    skipped_missing_timestamp = 0
    failures = 0

    try:
        projects = select_projects(
            api.list_projects(DEST_ROOT_GROUP),
            project_path,
        )
        print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}")
        print(f"Found {len(projects)} destination projects.")
        if purge_all:
            print(
                "PURGE ALL: every deletable tag, including latest, is selected."
            )
        else:
            print(
                f"Deleting tags with raw image Created before "
                f"{cutoff.isoformat()} (older than {days:g} days)."
            )
        if not purge_all and not include_latest:
            print(
                "The latest tag is protected by default; "
                "use --include-latest to include it."
            )
        print()

        for project_index, project in enumerate(projects, start=1):
            project_id = project["id"]
            path = project["path_with_namespace"]
            print(
                f"[Project {project_index}/{len(projects)}] {path}",
                flush=True,
            )
            try:
                repositories = api.list_registry_repositories(project_id)
            except Exception as error:
                failures += 1
                append_error({
                    "stage": "list_repositories",
                    "project_id": project_id,
                    "project": path,
                    "error": str(error),
                })
                print(f"  Repository listing failed: {error}", flush=True)
                continue

            if not repositories:
                print("  No container repositories.", flush=True)
                continue

            for repository_index, repository in enumerate(repositories, start=1):
                repositories_seen += 1
                repository_id = repository["id"]
                repository_path = repository.get("path") or str(repository_id)
                print(
                    f"  [Repository {repository_index}/{len(repositories)}] "
                    f"{repository_path}",
                    flush=True,
                )
                try:
                    tags = api.list_registry_tags(project_id, repository_id)
                except Exception as error:
                    failures += 1
                    append_error({
                        "stage": "list_tags",
                        "project_id": project_id,
                        "project": path,
                        "repository_id": repository_id,
                        "repository": repository_path,
                        "error": str(error),
                    })
                    print(f"    Tag listing failed: {error}", flush=True)
                    continue

                for tag_index, tag_summary in enumerate(tags, start=1):
                    tags_seen += 1
                    tag_name = tag_summary["name"]
                    prefix = f"    [Tag {tag_index}/{len(tags)}] {tag_name}"
                    try:
                        tag = api.get_registry_tag(
                            project_id, repository_id, tag_name
                        )
                        if tag.get("protected"):
                            skipped_protected += 1
                            print(f"{prefix} - skipped (protected)", flush=True)
                            continue
                        if (
                            tag_name == "latest"
                            and not include_latest
                            and not purge_all
                        ):
                            skipped_latest += 1
                            print(f"{prefix} - skipped (latest)", flush=True)
                            continue

                        raw_created_at = None
                        if not purge_all:
                            raw_created_at = raw_image_created(
                                tag["location"],
                                registry_auth,
                            )
                            tag["raw_created_at"] = raw_created_at
                            created_at = parse_timestamp(raw_created_at)
                            if created_at is None:
                                skipped_missing_timestamp += 1
                                print(
                                    f"{prefix} - skipped (no raw Created)",
                                    flush=True,
                                )
                                continue
                            if created_at >= cutoff:
                                print(
                                    f"{prefix} - kept ({raw_created_at})",
                                    flush=True,
                                )
                                continue

                        eligible += 1
                        key = checkpoint_key(project_id, repository_id, tag)
                        if key in completed:
                            checkpointed += 1
                            print(
                                f"{prefix} - skipped (deletion checkpoint)",
                                flush=True,
                            )
                            continue
                        if not execute:
                            detail = "all-tags mode" if purge_all else raw_created_at
                            print(
                                f"{prefix} - would delete ({detail})",
                                flush=True,
                            )
                            continue

                        api.delete_registry_tag(
                            project_id, repository_id, tag_name
                        )
                        results.append({
                            "checkpoint_key": key,
                            "project_id": project_id,
                            "project": path,
                            "repository_id": repository_id,
                            "repository": repository_path,
                            "tag": tag_name,
                            "digest": tag.get("digest"),
                            "gitlab_published_at": tag.get("created_at"),
                            "raw_image_created_at": raw_created_at,
                            "status": "deleted",
                            "deleted_at": utc_now(),
                        })
                        atomic_write_json(results)
                        completed.add(key)
                        deleted += 1
                        print(f"{prefix} - deleted (checkpoint saved)", flush=True)
                    except Exception as error:
                        failures += 1
                        append_error({
                            "stage": "inspect_or_delete_tag",
                            "project_id": project_id,
                            "project": path,
                            "repository_id": repository_id,
                            "repository": repository_path,
                            "tag": tag_name,
                            "error": str(error),
                        })
                        print(f"{prefix} - failed: {error}", flush=True)

        print()
        print(
            f"Registry purge complete: {len(projects)} projects, "
            f"{repositories_seen} repositories, {tags_seen} tags inspected, "
            f"{eligible} eligible, {deleted} deleted, "
            f"{checkpointed} checkpointed, {failures} failures."
        )
        print(
            f"Skipped: {skipped_latest} latest, {skipped_protected} protected, "
            f"{skipped_missing_timestamp} without raw image Created."
        )
        if execute:
            print(f"Results: {RESULTS_FILE}")
        else:
            print("Dry run only. Add --execute to delete eligible tags.")
        if failures:
            print(f"Failures: {ERROR_FILE}")
        return 1 if failures else 0
    finally:
        api.close()
        if registry_auth:
            registry_auth.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--include-latest", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Select every deletable tag and include latest; ignores --days.",
    )
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    validate()
    if args.days <= 0:
        raise RuntimeError("--days must be greater than zero.")
    return purge(
        args.days,
        args.execute,
        args.project,
        args.include_latest,
        args.reset,
        args.all,
    )


if __name__ == "__main__":
    raise SystemExit(main())
