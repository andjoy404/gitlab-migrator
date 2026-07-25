#!/usr/bin/env python3
"""Copy GitLab Container Registry images with Skopeo, preserving tags/manifests."""

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
    DEST_ROOT_GROUP, DEST_TOKEN, DEST_URL, SOURCE_GROUP, SOURCE_TOKEN,
    SOURCE_URL, validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


RESULTS_FILE = output_path("container_registry_results.json")
ERROR_FILE = output_path("container_registry_errors.log")
PROGRESS_FILE = output_path("container_registry_progress.json")


def append_error(entry):
    """Persist one failure immediately as a JSON-lines record."""

    record = dict(entry)
    record["recorded_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()

    with ERROR_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_results():
    if not RESULTS_FILE.exists():
        return []

    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    if not isinstance(results, list):
        raise RuntimeError(f"{RESULTS_FILE} must contain a JSON list")

    return results


def checkpoint_results(results):
    """Atomically persist successful image-tag copies."""

    temporary = RESULTS_FILE.with_name(RESULTS_FILE.name + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(results, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(RESULTS_FILE)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def registry_cutoff(days):
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat()


def atomic_write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


def load_registry_window(days, reset):
    if reset:
        RESULTS_FILE.unlink(missing_ok=True)
        PROGRESS_FILE.unlink(missing_ok=True)

    if PROGRESS_FILE.exists():
        progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))

        if progress.get("migration_days") != days or not progress.get("created_after"):
            raise RuntimeError(
                f"{PROGRESS_FILE} belongs to a different or legacy window. "
                "Run registry migration again with --reset."
            )

        return progress["created_after"]

    if RESULTS_FILE.exists():
        raise RuntimeError(
            f"{RESULTS_FILE} exists without window metadata. "
            "Run registry migration again with --reset."
        )

    created_after = registry_cutoff(days)
    atomic_write_json(PROGRESS_FILE, {
        "migration_days": days,
        "created_after": created_after,
        "started_at": utc_now(),
    })
    return created_after


def parse_timestamp(value):
    if not value:
        raise RuntimeError("Registry tag details have no created_at timestamp")

    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)

    return parsed


def result_key(source_image, destination_image):
    return source_image, destination_image


def authfile(registry, username, token):
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
    file = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
    json.dump({"auths": {registry: {"auth": encoded}}}, file)
    file.close()
    os.chmod(file.name, 0o600)
    return Path(file.name)


def image_destination(location, destination_registry):
    source_path = location.split("/", 1)[1]
    source_root = SOURCE_GROUP.strip("/")
    if not source_path.startswith(source_root + "/"):
        raise RuntimeError(f"Image is outside SOURCE_GROUP: {location}")
    relative = source_path.removeprefix(source_root + "/")
    return destination_registry.rstrip("/") + "/" + DEST_ROOT_GROUP.strip("/") + "/" + relative


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--days",
        type=float,
        default=30,
        help="Copy tags created during the last N days (default: 30).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Replace existing registry copy checkpoints for a new window.",
    )
    args = parser.parse_args()
    validate()
    if args.days <= 0:
        raise RuntimeError("--days must be greater than zero.")
    if not args.execute:
        raise RuntimeError("Registry copy changes the destination; add --execute.")
    if not shutil.which("skopeo"):
        raise RuntimeError("skopeo is required. Install it before running this script.")

    required = ["SOURCE_REGISTRY", "SOURCE_REGISTRY_USER", "SOURCE_REGISTRY_TOKEN", "DEST_REGISTRY", "DEST_REGISTRY_USER", "DEST_REGISTRY_TOKEN"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing registry variables: " + ", ".join(missing))

    src = GitLabAPI(SOURCE_URL, SOURCE_TOKEN)
    src_auth = None
    dst_auth = None

    try:
        src_auth = authfile(
            os.environ["SOURCE_REGISTRY"],
            os.environ["SOURCE_REGISTRY_USER"],
            os.environ["SOURCE_REGISTRY_TOKEN"],
        )
        dst_auth = authfile(
            os.environ["DEST_REGISTRY"],
            os.environ["DEST_REGISTRY_USER"],
            os.environ["DEST_REGISTRY_TOKEN"],
        )
        created_after = load_registry_window(args.days, args.reset)
        cutoff = parse_timestamp(created_after)
        results = load_results()
        successful = {
            result_key(
                record["source_image"],
                record["destination_image"],
            )
            for record in results
            if "source_image" in record and "destination_image" in record
            and record.get("status", "copied") == "copied"
        }
        outside_window = {
            result_key(
                record["source_image"],
                record["destination_image"],
            )
            for record in results
            if "source_image" in record and "destination_image" in record
            and record.get("status") == "outside_window"
        }
        copied_count = 0
        skipped_count = 0
        old_tag_count = 0
        failed_count = 0
        api_failure_count = 0

        try:
            projects = src.list_projects(SOURCE_GROUP)
        except Exception as error:
            append_error({
                "stage": "list_projects",
                "source_group": SOURCE_GROUP,
                "error": str(error),
            })
            raise RuntimeError(
                f"Cannot list source projects; failure saved to {ERROR_FILE}"
            ) from error

        print(f"Found {len(projects)} projects.")
        print(
            f"Copying registry tags created during the last {args.days:g} days "
            f"(manifest created at or after {created_after})."
        )

        if successful:
            print(
                f"Loaded {len(successful)} successful image checkpoints; "
                "they will be skipped."
            )

        print()

        for project_index, project in enumerate(projects, start=1):
            project_path = project["path_with_namespace"]
            print(
                f"[Project {project_index}/{len(projects)}] {project_path}",
                flush=True,
            )

            try:
                repositories = src.list_registry_repositories(project["id"])
            except Exception as error:
                append_error({
                    "stage": "list_repositories",
                    "project_id": project["id"],
                    "project_path": project_path,
                    "error": str(error),
                })
                api_failure_count += 1
                print(f"  Repository listing failed: {error}", flush=True)
                continue

            if not repositories:
                print("  No container repositories.", flush=True)
                continue

            for repository_index, repository in enumerate(
                repositories,
                start=1,
            ):
                location = repository.get("location") or "unknown"
                print(
                    f"  [Repository {repository_index}/{len(repositories)}] "
                    f"{location}",
                    flush=True,
                )

                try:
                    destination = image_destination(
                        repository["location"],
                        os.environ["DEST_REGISTRY"],
                    )
                    tags = src.list_registry_tags(
                        project["id"],
                        repository["id"],
                    )
                except Exception as error:
                    append_error({
                        "stage": "list_tags",
                        "project_id": project["id"],
                        "project_path": project_path,
                        "repository_id": repository.get("id"),
                        "repository_location": location,
                        "error": str(error),
                    })
                    api_failure_count += 1
                    print(f"    Tag listing failed: {error}", flush=True)
                    continue

                if not tags:
                    print("    No tags.", flush=True)
                    continue

                for tag_index, tag in enumerate(tags, start=1):
                    tag_name = tag["name"]
                    source_image = f"{repository['location']}:{tag_name}"
                    destination_image = f"{destination}:{tag_name}"
                    key = result_key(source_image, destination_image)
                    prefix = f"    [Tag {tag_index}/{len(tags)}]"

                    if key in successful:
                        print(
                            f"{prefix} {tag_name} - skipped (already copied)",
                            flush=True,
                        )
                        skipped_count += 1
                        continue

                    if key in outside_window:
                        print(
                            f"{prefix} {tag_name} - skipped "
                            "(previously filtered outside window)",
                            flush=True,
                        )
                        old_tag_count += 1
                        continue

                    try:
                        tag_detail = (
                            tag
                            if tag.get("created_at")
                            else src.get_registry_tag(
                                project["id"],
                                repository["id"],
                                tag_name,
                            )
                        )
                        tag_created_at = tag_detail.get("created_at")
                        tag_created = parse_timestamp(tag_created_at)
                    except Exception as error:
                        append_error({
                            "stage": "tag_details",
                            "project_id": project["id"],
                            "project_path": project_path,
                            "repository_id": repository.get("id"),
                            "repository_location": location,
                            "tag": tag_name,
                            "source_image": source_image,
                            "error": str(error),
                        })
                        api_failure_count += 1
                        print(
                            f"{prefix} {tag_name} - tag detail failed: {error}",
                            flush=True,
                        )
                        continue

                    if tag_created < cutoff:
                        results.append({
                            "status": "outside_window",
                            "project_id": project["id"],
                            "project_path": project_path,
                            "repository_id": repository.get("id"),
                            "tag": tag_name,
                            "source_image": source_image,
                            "destination_image": destination_image,
                            "source_created_at": tag_created_at,
                            "filtered_at": utc_now(),
                        })
                        checkpoint_results(results)
                        outside_window.add(key)
                        print(
                            f"{prefix} {tag_name} - skipped "
                            f"(created {tag_created_at})",
                            flush=True,
                        )
                        old_tag_count += 1
                        continue

                    print(
                        f"{prefix} Copying {source_image} -> "
                        f"{destination_image}",
                        flush=True,
                    )
                    copy_result = subprocess.run([
                        "skopeo",
                        "copy",
                        "--all",
                        "--src-authfile",
                        str(src_auth),
                        "--dest-authfile",
                        str(dst_auth),
                        f"docker://{source_image}",
                        f"docker://{destination_image}",
                    ], text=True, capture_output=True)

                    if copy_result.returncode:
                        message = (
                            copy_result.stderr.strip()
                            or "skopeo copy failed"
                        )
                        append_error({
                            "stage": "copy_tag",
                            "project_id": project["id"],
                            "project_path": project_path,
                            "repository_id": repository.get("id"),
                            "repository_location": location,
                            "tag": tag_name,
                            "source_image": source_image,
                            "destination_image": destination_image,
                            "error": message,
                        })
                        failed_count += 1
                        print(f"      Failed: {message}", flush=True)
                        continue

                    record = {
                        "status": "copied",
                        "project_id": project["id"],
                        "project_path": project_path,
                        "repository_id": repository.get("id"),
                        "tag": tag_name,
                        "source_image": source_image,
                        "destination_image": destination_image,
                        "source_created_at": tag_created_at,
                        "copied_at": utc_now(),
                    }
                    results.append(record)
                    checkpoint_results(results)
                    successful.add(key)
                    copied_count += 1
                    print("      Copied (checkpoint saved)", flush=True)

        total_failures = failed_count + api_failure_count
        print()
        print(
            f"Registry migration complete: {copied_count} newly copied, "
            f"{skipped_count} previously successful, "
            f"{old_tag_count} older than the window, "
            f"{total_failures} failed."
        )
        print(f"Total successful checkpoints: {len(successful)}")

        if total_failures:
            print(f"Failures: {ERROR_FILE}")
    finally:
        src.close()

        if src_auth:
            src_auth.unlink(missing_ok=True)

        if dst_auth:
            dst_auth.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
