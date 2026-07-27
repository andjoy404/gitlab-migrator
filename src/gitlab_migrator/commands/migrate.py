#!/usr/bin/env python3

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

try:
    from .bootstrap import configure_import_path
except ImportError:
    from bootstrap import configure_import_path

configure_import_path()

from gitlab_migrator.config import *
from gitlab_migrator.constants import USER_CANCELLED

validate()

from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.namespace import NamespaceManager
from gitlab_migrator.mirror import mirror
from gitlab_migrator.paths import output_path
from gitlab_migrator.project_filters import apply_project_exclusions
from gitlab_migrator.repository_progress import (
    load_repository_progress,
    save_repository_progress,
)

from gitlab_migrator.migrate_protected_branches import (
    migrate_protected_branches,
    restore_protected_branches,
)

# ==========================================================
# CONNECT
# ==========================================================

src = GitLabAPI(
    SOURCE_URL,
    SOURCE_TOKEN,
)

namespace_api = GitLabAPI(
    DEST_URL,
    DEST_TOKEN,
)

namespace = NamespaceManager(
    namespace_api,
    DEST_ROOT_GROUP,
)
namespace_lock = Lock()
results_lock = Lock()
results_file = output_path("repository_migration_results.json")
migration_context = {
    "source_url": SOURCE_URL.rstrip("/"),
    "source_group": SOURCE_GROUP.strip("/"),
    "destination_url": DEST_URL.rstrip("/"),
    "destination_root_group": DEST_ROOT_GROUP.strip("/"),
}


# ==========================================================
# START
# ==========================================================

print("=" * 70)
print("GitLab Group Migrator")
print("=" * 70)

print(f"Source      : {SOURCE_URL}")
print(f"Source Group: {SOURCE_GROUP}")
print(f"Destination : {DEST_URL}")
print(f"Root Group  : {DEST_ROOT_GROUP}")

try:
    workers = int(os.getenv("MIGRATE_WORKERS", "1"))
except ValueError as error:
    raise RuntimeError("MIGRATE_WORKERS must be a positive integer.") from error

if workers < 1:
    raise RuntimeError("MIGRATE_WORKERS must be a positive integer.")

print(f"Workers     : {workers}")
print()

if "--yes" not in sys.argv[1:]:
    answer = input(
        "Continue migration? (yes/no): "
    ).strip().lower()

    if answer != "yes":

        print("Cancelled.")

        raise SystemExit(USER_CANCELLED)

print()

repository_results = load_repository_progress(
    results_file,
    migration_context,
    reset="--reset" in sys.argv[1:],
)
completed_paths = {
    result["source_path"]
    for result in repository_results
    if result.get("status") == "completed" and result.get("source_path")
}
# ==========================================================
# PROJECTS
# ==========================================================


projects = src.list_projects(
    SOURCE_GROUP
)

# Set one of these filters to avoid reprocessing every repository.  Values
# must be full source paths.  The source root remains unchanged, so the
# destination namespace hierarchy is preserved.
project_filter = os.getenv("MIGRATE_PROJECT")
group_filter = os.getenv("MIGRATE_GROUP")

if project_filter and group_filter:
    raise RuntimeError(
        "Set only one of MIGRATE_PROJECT or MIGRATE_GROUP."
    )

if project_filter:
    projects = [
        project
        for project in projects
        if project["path_with_namespace"] == project_filter
    ]

    if not projects:
        raise RuntimeError(
            f"Project not found in source group: {project_filter}"
        )

    print(f"Retrying only: {project_filter}")

elif group_filter:
    group_filter = group_filter.strip("/")
    source_root = SOURCE_GROUP.strip("/")

    if (
        group_filter != source_root
        and not group_filter.startswith(source_root + "/")
    ):
        raise RuntimeError(
            "MIGRATE_GROUP must be SOURCE_GROUP or one of its subgroups."
        )

    projects = [
        project
        for project in projects
        if project["path_with_namespace"].startswith(
            group_filter + "/"
        )
    ]

    if not projects:
        raise RuntimeError(
            f"No projects found in source group: {group_filter}"
        )

    print(f"Syncing only group: {group_filter}")

projects, excluded_projects = apply_project_exclusions(projects, SOURCE_GROUP)
for project in excluded_projects:
    print(f"{project['path_with_namespace']} - skipped (excluded)")
if excluded_projects:
    print(f"Excluded {len(excluded_projects)} projects.")

discovered_total = len(projects)
projects = [
    project
    for project in projects
    if project["path_with_namespace"] not in completed_paths
]
previously_completed = discovered_total - len(projects)
total = len(projects)

print(f"Found {discovered_total} projects.")
if previously_completed:
    print(
        f"Skipping {previously_completed} previously completed repositories "
        f"from {results_file}."
    )
print(f"Repositories remaining: {total}")
print()

success = 0
failed = 0

errors = []

# ==========================================================
# MIGRATION
# ==========================================================

def migrate_project(index, project):
    """Migrate one project and return an error record on failure."""

    print("=" * 70)
    print(f"[{index}/{total}] {project['path_with_namespace']}")
    print("=" * 70)

    src_api = GitLabAPI(SOURCE_URL, SOURCE_TOKEN)
    dst_api = GitLabAPI(DEST_URL, DEST_TOKEN)

    try:
        relative = project["path_with_namespace"].replace(
            SOURCE_GROUP + "/",
            "",
            1,
        )
        parts = relative.split("/")
        groups = parts[:-1]
        project_name = parts[-1]

        # Namespace creation is serialized so projects in the same subgroup
        # cannot race to create the same destination group.
        with namespace_lock:
            namespace_id = namespace.ensure(groups)

        destination_path = DEST_ROOT_GROUP + "/" + "/".join(parts)
        destination_project = dst_api.create_project_if_not_exists(
            project_name,
            project_name,
            namespace_id,
        )

        # A protected destination branch can reject the force-push used by
        # the mirror operation. Preserve source rules and restore them after.
        protections = migrate_protected_branches(
            src_api,
            dst_api,
            project["id"],
            destination_project["id"],
        )

        try:
            mirror(
                project["http_url_to_repo"],
                f"{DEST_URL}/{destination_path}.git",
            )
        finally:
            restore_protected_branches(
                dst_api,
                destination_project["id"],
                protections,
            )

        with results_lock:
            repository_results.append({
                "source_path": project["path_with_namespace"],
                "destination_path": destination_path,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            save_repository_progress(
                results_file,
                migration_context,
                repository_results,
            )

        print(
            f"Completed: {project['path_with_namespace']} "
            "(checkpoint saved)"
        )
        print()
        return None

    except Exception as error:
        print(f"ERROR: {project['path_with_namespace']}")
        print(error)
        print()
        return project["path_with_namespace"], str(error)

    finally:
        src_api.close()
        dst_api.close()


with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = [
        executor.submit(migrate_project, index, project)
        for index, project in enumerate(projects, start=1)
    ]

    for future in as_completed(futures):
        error = future.result()

        if error is None:
            success += 1
        else:
            failed += 1
            errors.append(error)

# ==========================================================
# REPORT
# ==========================================================

print()
print("=" * 70)
print("Migration Finished")
print("=" * 70)

print(f"Total     : {total}")
print(f"Success   : {success}")
print(f"Skipped   : {previously_completed}")
print(f"Failed    : {failed}")

if errors:

    error_file = output_path("migration_errors.log")

    with open(
        error_file,
        "w",
        encoding="utf-8",
    ) as f:

        for repo, err in errors:

            f.write(
                repo
                + "\n"
            )

            f.write(
                err
                + "\n"
            )

            f.write(
                "-" * 80
                + "\n"
            )

    print()
    print(
        f"Failure log written to {error_file}"
    )

print()
print("=" * 70)
print("Done.")
print("=" * 70)
