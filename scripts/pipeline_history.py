#!/usr/bin/env python3
"""Archive source pipeline history or explicitly replay selected pipelines."""

import argparse
import datetime
import json
import os
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
    SOURCE_GROUP,
    SOURCE_TOKEN,
    SOURCE_URL,
    validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


ERROR_FILE = output_path("pipeline_history_errors.log")
REPLAY_RESULTS_FILE = output_path("pipeline_replay_results.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def append_error(entry):
    """Append and flush one error immediately as a JSON-lines record."""

    record = dict(entry)
    record["recorded_at"] = utc_now()

    with ERROR_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_json_list(path):
    if not path.exists():
        return []

    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, list):
        raise RuntimeError(f"{path} must contain a JSON list")

    return value


def atomic_write_json(path, value):
    """Write JSON through a temporary file and atomically replace the target."""

    temporary = path.with_name(path.name + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


def progress_path(history_file):
    return history_file.with_name(history_file.stem + "_progress.json")


def export_cutoff(days):
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat()


def load_export_progress(path, history_exists, days):
    if not path.exists():
        return set(), export_cutoff(days)

    if not history_exists:
        raise RuntimeError(
            f"{path} exists but its pipeline history file is missing; "
            "restore the history file or remove the stale progress file."
        )

    value = json.loads(path.read_text(encoding="utf-8"))

    if value.get("source_group") != SOURCE_GROUP:
        raise RuntimeError(
            f"{path} belongs to source group {value.get('source_group')!r}, "
            f"not {SOURCE_GROUP!r}."
        )

    if value.get("export_days") != days or not value.get("created_after"):
        raise RuntimeError(
            f"{path} belongs to a different or legacy export window. "
            "Run export again with --reset to start the filtered snapshot."
        )

    completed = {
        str(project_id)
        for project_id in value.get("completed_project_ids", [])
    }
    return completed, value["created_after"]


def save_export_progress(path, completed_project_ids, days, created_after):
    atomic_write_json(path, {
        "source_group": SOURCE_GROUP,
        "export_days": days,
        "created_after": created_after,
        "completed_project_ids": sorted(completed_project_ids),
        "updated_at": utc_now(),
    })


def pipeline_record(project, pipeline):
    return {
        "project": project["path_with_namespace"],
        "source_project_id": project["id"],
        "id": pipeline["id"],
        "iid": pipeline.get("iid"),
        "ref": pipeline["ref"],
        "sha": pipeline.get("sha"),
        "status": pipeline.get("status"),
        "source": pipeline.get("source"),
        "created_at": pipeline.get("created_at"),
        "updated_at": pipeline.get("updated_at"),
        "web_url": pipeline.get("web_url"),
    }


def export_history(api, history_file, days, reset):
    export_progress_file = progress_path(history_file)

    if reset:
        history_file.unlink(missing_ok=True)
        export_progress_file.unlink(missing_ok=True)

    history_exists = history_file.exists()
    history = load_json_list(history_file)
    completed, created_after = load_export_progress(
        export_progress_file,
        history_exists,
        days,
    )
    exported_projects = 0
    skipped_projects = 0
    failed_projects = 0
    exported_pipelines = 0

    try:
        projects = api.list_projects(SOURCE_GROUP)
    except Exception as error:
        append_error({
            "mode": "export",
            "stage": "list_projects",
            "source_group": SOURCE_GROUP,
            "error": str(error),
        })
        raise RuntimeError(
            f"Cannot list source projects; failure saved to {ERROR_FILE}"
        ) from error

    print(f"Found {len(projects)} projects.")
    print(
        f"Exporting pipelines created during the last {days:g} days "
        f"(created at or after {created_after})."
    )

    if completed:
        print(
            f"Loaded {len(completed)} completed project checkpoints; "
            "they will be skipped."
        )

    print()

    for index, project in enumerate(projects, start=1):
        project_id = str(project["id"])
        project_path = project["path_with_namespace"]
        prefix = f"[Project {index}/{len(projects)}] {project_path}"

        if project_id in completed:
            existing_count = sum(
                1 for item in history if item.get("project") == project_path
            )
            print(
                f"{prefix} - skipped ({existing_count} archived pipelines)",
                flush=True,
            )
            skipped_projects += 1
            continue

        print(prefix, flush=True)

        try:
            pipelines = api.list_pipelines(
                project["id"],
                created_after=created_after,
            )
        except Exception as error:
            append_error({
                "mode": "export",
                "stage": "list_pipelines",
                "project_id": project["id"],
                "project_path": project_path,
                "created_after": created_after,
                "error": str(error),
            })
            failed_projects += 1
            print(f"  Failed: {error}", flush=True)
            continue

        project_history = [
            pipeline_record(project, pipeline)
            for pipeline in pipelines
        ]

        # Replace this project's records. If a prior run stopped between the
        # history and progress writes, retrying cannot create duplicates.
        history = [
            item for item in history if item.get("project") != project_path
        ]
        history.extend(project_history)
        atomic_write_json(history_file, history)
        completed.add(project_id)
        save_export_progress(
            export_progress_file,
            completed,
            days,
            created_after,
        )
        exported_projects += 1
        exported_pipelines += len(project_history)
        print(
            f"  Archived {len(project_history)} pipelines "
            "(checkpoint saved)",
            flush=True,
        )

    print()
    print(
        f"Pipeline export complete: {exported_projects} newly archived projects, "
        f"{skipped_projects} previously completed, "
        f"{failed_projects} failed."
    )
    print(
        f"Archived {len(history)} total pipeline records to {history_file} "
        f"({exported_pipelines} added or refreshed this run)."
    )

    if failed_projects:
        print(f"Failures: {ERROR_FILE}")


def destination_path(source_path):
    source_root = SOURCE_GROUP.strip("/")
    normalized = source_path.strip("/")

    if normalized != source_root and not normalized.startswith(source_root + "/"):
        raise RuntimeError(f"Pipeline project is outside SOURCE_GROUP: {source_path}")

    relative = normalized.removeprefix(source_root).strip("/")
    return "/".join(
        part for part in (DEST_ROOT_GROUP.strip("/"), relative) if part
    )


def pipeline_key(item):
    """Create a stable source-record identity for replay checkpoints."""

    identity = [
        item.get("project"),
        item.get("id"),
        item.get("ref"),
        item.get("sha"),
        item.get("created_at"),
    ]
    return json.dumps(identity, separators=(",", ":"), ensure_ascii=True)


def latest_per_project_ref(history):
    """Select the newest source pipeline for each project/ref combination."""

    selected = {}

    for item in history:
        group_key = item.get("project"), item.get("ref")
        rank = (
            item.get("created_at") or "",
            int(item["id"]) if str(item.get("id", "")).isdigit() else 0,
        )
        current = selected.get(group_key)

        if current is None or rank > current[0]:
            selected[group_key] = rank, item

    return [value[1] for value in selected.values()]


def is_replayable_ref(ref):
    """Return whether GitLab create-pipeline API accepts this ref type."""

    return bool(ref) and not ref.startswith("refs/merge-requests/")


def replay_history(api, history_file, all_records):
    history = load_json_list(history_file)
    selected_items = history if all_records else latest_per_project_ref(history)
    replay_items = [
        item for item in selected_items
        if is_replayable_ref(item.get("ref"))
    ]
    non_replayable_count = len(selected_items) - len(replay_items)
    results = load_json_list(REPLAY_RESULTS_FILE)
    successful = {
        record["source_pipeline_key"]
        for record in results
        if "source_pipeline_key" in record
    }
    project_cache = {}
    replayed_count = 0
    skipped_count = 0
    failed_count = 0

    mode = "all historical records" if all_records else "latest pipeline per project/ref"
    print(
        f"Selected {len(selected_items)} of {len(history)} archived pipelines "
        f"for replay ({mode})."
    )

    if non_replayable_count:
        print(
            f"Skipped {non_replayable_count} merge-request pipelines: "
            "GitLab create-pipeline API accepts branch or tag refs, not "
            "refs/merge-requests/*."
        )
    print(f"{len(replay_items)} branch/tag pipelines remain.")

    if successful:
        print(
            f"Loaded {len(successful)} successful replay checkpoints; "
            "they will be skipped."
        )

    print()

    for index, item in enumerate(replay_items, start=1):
        project_path = item.get("project") or "unknown"
        ref = item.get("ref") or "unknown"
        source_key = pipeline_key(item)
        prefix = (
            f"[Pipeline {index}/{len(replay_items)}] "
            f"{project_path}:{ref} (source ID {item.get('id', 'unknown')})"
        )

        if source_key in successful:
            print(f"{prefix} - skipped (already replayed)", flush=True)
            skipped_count += 1
            continue

        print(prefix, flush=True)

        try:
            destination_project_path = destination_path(project_path)
            project = project_cache.get(destination_project_path)

            if project is None:
                project = api.find_project(destination_project_path)

                if project is None:
                    raise RuntimeError(
                        f"Destination project not found: {destination_project_path}"
                    )

                project_cache[destination_project_path] = project

            created = api.create_pipeline(project["id"], item["ref"])
            record = {
                "source_pipeline_key": source_key,
                "source_pipeline_id": item.get("id"),
                "source_project": project_path,
                "ref": item["ref"],
                "sha_at_export": item.get("sha"),
                "destination_project": destination_project_path,
                "destination_project_id": project["id"],
                "destination_pipeline_id": (
                    created.get("id") if isinstance(created, dict) else None
                ),
                "replayed_at": utc_now(),
            }
            results.append(record)
            atomic_write_json(REPLAY_RESULTS_FILE, results)
            successful.add(source_key)
            replayed_count += 1
            print(
                "  Created destination pipeline (checkpoint saved)",
                flush=True,
            )
        except Exception as error:
            append_error({
                "mode": "replay",
                "stage": "create_pipeline",
                "source_pipeline_id": item.get("id"),
                "source_project": project_path,
                "ref": item.get("ref"),
                "error": str(error),
            })
            failed_count += 1
            print(f"  Failed: {error}", flush=True)

    print()
    print(
        f"Pipeline replay complete: {replayed_count} newly replayed, "
        f"{skipped_count} previously successful, "
        f"{non_replayable_count} non-replayable merge-request refs, "
        f"{failed_count} failed."
    )
    print(f"Total successful replay checkpoints: {len(successful)}")

    if failed_count:
        print(f"Failures: {ERROR_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default=str(output_path("pipeline_history.json")),
    )
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--days",
        type=float,
        default=30,
        help="Export pipelines created during the last N days (default: 30).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Replace existing export history/progress with a new snapshot.",
    )
    parser.add_argument(
        "--all-records",
        action="store_true",
        help="Replay every archived pipeline instead of only the latest per project/ref.",
    )
    args = parser.parse_args()
    validate()

    if args.days <= 0:
        raise RuntimeError("--days must be greater than zero.")

    if args.all_records and not args.replay:
        raise RuntimeError("--all-records is only valid with --replay.")

    if args.replay and not args.execute:
        raise RuntimeError("Pipeline replay creates new CI jobs; add --execute.")

    if args.replay and args.reset:
        raise RuntimeError("--reset is only valid for pipeline export.")

    history_file = Path(args.file)
    api = None

    try:
        if args.replay:
            api = GitLabAPI(DEST_URL, DEST_TOKEN)
            replay_history(api, history_file, args.all_records)
        else:
            api = GitLabAPI(SOURCE_URL, SOURCE_TOKEN)
            export_history(api, history_file, args.days, args.reset)
    finally:
        if api:
            api.close()


if __name__ == "__main__":
    main()
