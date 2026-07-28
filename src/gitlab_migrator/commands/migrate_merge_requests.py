#!/usr/bin/env python3
"""Migrate recently updated merge requests into existing destination projects.

Open merge requests are recreated as open. Closed and merged source records
are recreated as closed historical records so this tool never performs a new
merge or alters the destination target branch.
"""

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
    DEST_ROOT_GROUP, DEST_TOKEN, DEST_URL, SOURCE_GROUP, SOURCE_TOKEN,
    SOURCE_URL, validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path
from gitlab_migrator.project_filters import (
    apply_project_exclusions,
    normalize_filter_path,
    normalize_filter_paths,
    select_group_projects,
)


RESULTS_FILE = output_path("merge_request_migration_results.json")
ERROR_FILE = output_path("merge_request_migration_errors.log")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def cutoff_for_days(days):
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat()


def load_json_list(path):
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError(f"{path} must contain a JSON list")
    return value


def atomic_write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def append_error(entry):
    record = dict(entry)
    record["recorded_at"] = utc_now()
    with ERROR_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def destination_path(source_path):
    source_root = SOURCE_GROUP.strip("/")
    normalized = source_path.strip("/")
    if normalized != source_root and not normalized.startswith(source_root + "/"):
        raise RuntimeError(f"Project is outside SOURCE_GROUP: {source_path}")
    relative = normalized.removeprefix(source_root).strip("/")
    return "/".join(
        part for part in (DEST_ROOT_GROUP.strip("/"), relative) if part
    )


def filter_projects(projects):
    project_filter = os.getenv("MIGRATE_PROJECT")
    group_filter = os.getenv("MIGRATE_GROUP")
    group_filters = os.getenv("MIGRATE_GROUPS")
    configured_filters = [
        name for name, value in (
            ("MIGRATE_PROJECT", project_filter),
            ("MIGRATE_GROUP", group_filter),
            ("MIGRATE_GROUPS", group_filters),
        )
        if value
    ]
    if len(configured_filters) > 1:
        raise RuntimeError(
            "Set only one of MIGRATE_PROJECT, MIGRATE_GROUP, or "
            "MIGRATE_GROUPS."
        )
    if project_filter:
        requested_filter = project_filter
        project_filter = normalize_filter_path(
            project_filter, SOURCE_GROUP, DEST_ROOT_GROUP
        )
        filtered = [
            project for project in projects
            if project["path_with_namespace"] == project_filter
        ]
        if not filtered:
            raise RuntimeError(f"Project not found: {project_filter}")
        if requested_filter.strip("/") != project_filter:
            print(
                f"Resolved project filter: "
                f"{requested_filter} -> {project_filter}"
            )
        projects = filtered
    elif group_filter:
        requested_filter = group_filter
        normalized = normalize_filter_path(
            group_filter, SOURCE_GROUP, DEST_ROOT_GROUP
        )
        source_root = SOURCE_GROUP.strip("/")
        if normalized != source_root and not normalized.startswith(source_root + "/"):
            raise RuntimeError(
                "MIGRATE_GROUP must be SOURCE_GROUP or one of its subgroups."
            )
        filtered = [
            project for project in projects
            if project["path_with_namespace"] == normalized
            or project["path_with_namespace"].startswith(normalized + "/")
        ]
        if not filtered:
            raise RuntimeError(f"No projects found below: {group_filter}")
        if requested_filter.strip("/") != normalized:
            print(
                f"Resolved group filter: "
                f"{requested_filter} -> {normalized}"
            )
        projects = filtered
    elif group_filters:
        normalized_groups = normalize_filter_paths(
            group_filters, SOURCE_GROUP, DEST_ROOT_GROUP
        )
        if not normalized_groups:
            raise RuntimeError(
                "MIGRATE_GROUPS must contain at least one group."
            )
        filtered = select_group_projects(projects, normalized_groups)
        if not filtered:
            raise RuntimeError(
                "No projects found below MIGRATE_GROUPS: "
                + ", ".join(sorted(normalized_groups))
            )
        print("Migrating merge requests for selected groups:")
        for selected_group in sorted(normalized_groups):
            print(f"  - {selected_group}")
        projects = filtered

    projects, excluded = apply_project_exclusions(projects, SOURCE_GROUP)
    for project in excluded:
        print(f"{project['path_with_namespace']} - skipped (excluded)")
    if excluded:
        print(f"Excluded {len(excluded)} projects.")
    return projects


def source_key(project, merge_request):
    return f"{project['id']}:{merge_request['iid']}"


def migration_marker(project, merge_request):
    return (
        "<!-- gitlab-migrator-source-mr:"
        f"{project['id']}:{merge_request['iid']} -->"
    )


def note_marker(project, merge_request, note):
    return (
        "<!-- gitlab-migrator-source-note:"
        f"{project['id']}:{merge_request['iid']}:{note['id']} -->"
    )


def author_text(author):
    if not author:
        return "unknown"
    name = author.get("name") or author.get("username") or "unknown"
    username = author.get("username")
    return f"{name} (@{username})" if username else name


def migrated_description(project, merge_request):
    original = merge_request.get("description") or ""
    metadata = [
        migration_marker(project, merge_request),
        "---",
        "### Migration record",
        "",
        f"- Original: {merge_request.get('web_url')}",
        f"- Original author: {author_text(merge_request.get('author'))}",
        f"- Original state: `{merge_request.get('state', 'unknown')}`",
        f"- Created: `{merge_request.get('created_at') or 'unknown'}`",
        f"- Updated: `{merge_request.get('updated_at') or 'unknown'}`",
    ]
    if merge_request.get("merged_at"):
        metadata.append(f"- Merged: `{merge_request['merged_at']}`")
        metadata.append(
            "- Merged by: " + author_text(
                merge_request.get("merge_user")
                or merge_request.get("merged_by")
            )
        )
    if merge_request.get("closed_at"):
        metadata.append(f"- Closed: `{merge_request['closed_at']}`")
    metadata.extend([
        "",
        "> Imported as an audit record. A source MR marked merged is closed",
        "> here because replaying a merge would modify destination Git history.",
    ])
    return original.rstrip() + "\n\n" + "\n".join(metadata) + "\n"


def historical_note_body(project, merge_request, note):
    kind = "System event" if note.get("system") else "Comment"
    return "\n".join([
        note_marker(project, merge_request, note),
        f"**Migrated {kind.lower()} by {author_text(note.get('author'))}**",
        f"Original timestamp: `{note.get('created_at') or 'unknown'}`",
        "",
        note.get("body") or "",
    ])


def find_existing_destination_mr(api, project_id, marker):
    candidates = api.list_merge_requests(project_id)
    for candidate in candidates:
        if marker in (candidate.get("description") or ""):
            return candidate
    return None


def ensure_source_branch(destination_api, destination_project_id, merge_request):
    source_branch = merge_request["source_branch"]
    existing_branch = destination_api.find_branch(
        destination_project_id, source_branch
    )
    expected_sha = (
        (merge_request.get("diff_refs") or {}).get("head_sha")
        or merge_request.get("sha")
    )
    existing_sha = (
        (existing_branch.get("commit") or {}).get("id")
        if existing_branch else None
    )
    if existing_branch and (not expected_sha or existing_sha == expected_sha):
        return source_branch, None
    temporary_branch = (
        f"gitlab-migrator/mr-{merge_request['iid']}-"
        f"{str(merge_request.get('sha') or '')[:8]}"
    ).rstrip("-")
    if destination_api.find_branch(destination_project_id, temporary_branch):
        return temporary_branch, temporary_branch
    ref = (
        expected_sha
        or merge_request["target_branch"]
    )
    try:
        destination_api.create_branch(
            destination_project_id, temporary_branch, ref
        )
    except Exception:
        # A deleted/squash-merged source branch can leave its head SHA
        # unavailable in the destination object database. An audit-only MR
        # can still be created from the target branch and retain all metadata.
        if ref == merge_request["target_branch"]:
            raise
        destination_api.create_branch(
            destination_project_id,
            temporary_branch,
            merge_request["target_branch"],
        )
    return temporary_branch, temporary_branch


def create_or_find_merge_request(
    source_api, destination_api, source_project, destination_project, summary
):
    detail = source_api.get_merge_request(source_project["id"], summary["iid"])
    marker = migration_marker(source_project, detail)
    existing = find_existing_destination_mr(
        destination_api, destination_project["id"], marker
    )
    if existing:
        return detail, existing, None, False
    branch, temporary_branch = ensure_source_branch(
        destination_api, destination_project["id"], detail
    )
    payload = {
        "source_branch": branch,
        "target_branch": detail["target_branch"],
        "title": detail["title"],
        "description": migrated_description(source_project, detail),
        "remove_source_branch": False,
    }
    labels = [
        label if isinstance(label, str) else label.get("name")
        for label in detail.get("labels", [])
    ]
    labels = [label for label in labels if label]
    if labels:
        payload["labels"] = ",".join(labels)
    created = destination_api.create_merge_request(
        destination_project["id"], **payload
    )
    return detail, created, temporary_branch, True


def migrate_notes(
    source_api, destination_api, source_project, destination_project,
    source_merge_request, destination_merge_request,
):
    source_notes = source_api.list_merge_request_notes(
        source_project["id"], source_merge_request["iid"]
    )
    destination_notes = destination_api.list_merge_request_notes(
        destination_project["id"], destination_merge_request["iid"]
    )
    existing_bodies = {note.get("body") or "" for note in destination_notes}
    created_count = 0
    for note in source_notes:
        marker = note_marker(source_project, source_merge_request, note)
        if any(marker in body for body in existing_bodies):
            continue
        payload = {
            "body": historical_note_body(source_project, source_merge_request, note)
        }
        if note.get("created_at"):
            payload["created_at"] = note["created_at"]
        try:
            destination_api.create_merge_request_note(
                destination_project["id"], destination_merge_request["iid"],
                **payload,
            )
        except Exception as error:
            response = getattr(error, "response", None)
            status_code = response.status_code if response is not None else None
            if "created_at" not in payload or status_code not in {400, 403}:
                raise
            payload.pop("created_at")
            destination_api.create_merge_request_note(
                destination_project["id"], destination_merge_request["iid"],
                **payload,
            )
        existing_bodies.add(payload["body"])
        created_count += 1
    return created_count


def migrate(days, reset):
    if reset:
        RESULTS_FILE.unlink(missing_ok=True)
        ERROR_FILE.unlink(missing_ok=True)
    results = load_json_list(RESULTS_FILE)
    completed = {
        result["source_key"] for result in results
        if result.get("status") == "completed" and result.get("source_key")
    }
    cutoff = cutoff_for_days(days)
    source_api = GitLabAPI(SOURCE_URL, SOURCE_TOKEN)
    destination_api = GitLabAPI(DEST_URL, DEST_TOKEN)
    try:
        projects = filter_projects(source_api.list_projects(SOURCE_GROUP))
        work = []
        project_failures = 0
        print(
            f"Collecting merge requests updated during the last {days:g} days "
            f"(updated at or after {cutoff})."
        )
        for index, project in enumerate(projects, start=1):
            path = project["path_with_namespace"]
            print(f"[Project {index}/{len(projects)}] {path}", flush=True)
            try:
                merge_requests = source_api.list_merge_requests(
                    project["id"], updated_after=cutoff,
                    order_by="updated_at", sort="asc",
                )
                print(f"  Found {len(merge_requests)} merge requests.", flush=True)
                work.extend((project, item) for item in merge_requests)
            except Exception as error:
                project_failures += 1
                append_error({
                    "stage": "list_merge_requests",
                    "source_project": path,
                    "error": str(error),
                })
                print(f"  Failed: {error}", flush=True)

        print(f"\nMigrating {len(work)} recent merge requests.\n")
        newly_completed = 0
        previously_completed = 0
        failed = 0
        for index, (project, summary) in enumerate(work, start=1):
            key = source_key(project, summary)
            path = project["path_with_namespace"]
            prefix = (
                f"[Merge request {index}/{len(work)}] "
                f"{path}!{summary['iid']} [{summary.get('state', 'unknown')}]"
            )
            if key in completed:
                print(f"{prefix} - skipped (checkpoint exists)", flush=True)
                previously_completed += 1
                continue
            print(prefix, flush=True)
            temporary_branch = None
            detail = None
            destination_project = None
            destination_merge_request = None
            try:
                destination_project_path = destination_path(path)
                destination_project = destination_api.find_project(
                    destination_project_path
                )
                if destination_project is None:
                    raise RuntimeError(
                        f"Destination project not found: {destination_project_path}"
                    )
                (
                    detail, destination_merge_request, temporary_branch, created,
                ) = create_or_find_merge_request(
                    source_api, destination_api, project,
                    destination_project, summary,
                )
                notes_created = migrate_notes(
                    source_api, destination_api, project, destination_project,
                    detail, destination_merge_request,
                )
                if detail.get("state") in {"closed", "merged"}:
                    destination_merge_request = destination_api.update_merge_request(
                        destination_project["id"],
                        destination_merge_request["iid"], state_event="close",
                    )
                record = {
                    "source_key": key,
                    "source_project": path,
                    "source_merge_request_iid": detail["iid"],
                    "source_state": detail.get("state"),
                    "source_web_url": detail.get("web_url"),
                    "destination_project": destination_project_path,
                    "destination_merge_request_iid": destination_merge_request["iid"],
                    "destination_web_url": destination_merge_request.get("web_url"),
                    "destination_state": destination_merge_request.get("state"),
                    "created_new": created,
                    "notes_created": notes_created,
                    "status": "completed",
                    "completed_at": utc_now(),
                }
                results.append(record)
                atomic_write_json(RESULTS_FILE, results)
                completed.add(key)
                newly_completed += 1
                print(
                    f"  Completed as destination !{destination_merge_request['iid']} "
                    f"({notes_created} notes added; checkpoint saved)",
                    flush=True,
                )
            except Exception as error:
                failed += 1
                append_error({
                    "stage": "migrate_merge_request",
                    "source_key": key,
                    "source_project": path,
                    "source_merge_request_iid": summary.get("iid"),
                    "destination_project_id": (
                        destination_project.get("id") if destination_project else None
                    ),
                    "destination_merge_request_iid": (
                        destination_merge_request.get("iid")
                        if destination_merge_request else None
                    ),
                    "error": str(error),
                })
                print(f"  Failed: {error}", flush=True)
            finally:
                if (
                    temporary_branch
                    and destination_project
                    and (not detail or detail.get("state") != "opened")
                ):
                    try:
                        destination_api.delete_branch(
                            destination_project["id"], temporary_branch
                        )
                    except Exception as cleanup_error:
                        append_error({
                            "stage": "delete_temporary_branch",
                            "source_key": key,
                            "branch": temporary_branch,
                            "error": str(cleanup_error),
                        })
                        print(
                            f"  Warning: could not delete temporary branch "
                            f"{temporary_branch}: {cleanup_error}", flush=True,
                        )

        print()
        print(
            f"Merge-request migration complete: {newly_completed} newly "
            f"completed, {previously_completed} checkpointed, {failed} failed; "
            f"{project_failures} project listing failures."
        )
        print(f"Results: {RESULTS_FILE}")
        if failed or project_failures:
            print(f"Failures: {ERROR_FILE}")
        return 1 if failed or project_failures else 0
    finally:
        source_api.close()
        destination_api.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    validate()
    if args.days <= 0:
        raise RuntimeError("--days must be greater than zero.")
    if not args.execute:
        raise RuntimeError(
            "Merge-request migration creates records and notes; add --execute."
        )
    return migrate(args.days, args.reset)


if __name__ == "__main__":
    raise SystemExit(main())
