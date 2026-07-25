#!/usr/bin/env python3

try:
    from .bootstrap import configure_import_path
except ImportError:
    from bootstrap import configure_import_path

configure_import_path()

from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.config import *

validate()

# ==========================================================
# CONNECT
# ==========================================================

src = GitLabAPI(
    SOURCE_URL,
    SOURCE_TOKEN,
)

dst = GitLabAPI(
    DEST_URL,
    DEST_TOKEN,
)

# ==========================================================
# PROJECTS
# ==========================================================

projects = src.list_projects(
    SOURCE_GROUP
)

print(f"Found {len(projects)} projects.")
print()

for index, project in enumerate(projects, start=1):

    print("=" * 70)
    print(
        f"[{index}/{len(projects)}] "
        f"{project['path_with_namespace']}"
    )
    print("=" * 70)

    #
    # Source hooks
    #

    source_hooks = src.list_hooks(
        project["id"]
    )

    if not source_hooks:

        print("No hooks.")

        continue

    #
    # Destination project
    #

    relative = project["path_with_namespace"].replace(
        SOURCE_GROUP + "/",
        "",
        1,
    )

    destination_path = (
        DEST_ROOT_GROUP + "/" + relative
    )

    destination_project = dst.find_project(
        destination_path
    )

    if destination_project is None:

        print("Destination project not found.")

        continue

    #
    # Existing destination hooks
    #

    destination_hooks = {
        hook["url"]: hook
        for hook in dst.list_hooks(
            destination_project["id"]
        )
    }

    #
    # Sync hooks
    #

    for hook in source_hooks:

        url = hook["url"]

        if url in destination_hooks:

            print(f"Hook already exists: {url}")

            continue

        payload = {
            "url": url,
            "push_events": hook.get("push_events", False),
            "push_events_branch_filter": hook.get(
                "push_events_branch_filter"
            ),
            "issues_events": hook.get("issues_events", False),
            "confidential_issues_events": hook.get(
                "confidential_issues_events",
                False,
            ),
            "merge_requests_events": hook.get(
                "merge_requests_events",
                False,
            ),
            "tag_push_events": hook.get(
                "tag_push_events",
                False,
            ),
            "note_events": hook.get(
                "note_events",
                False,
            ),
            "confidential_note_events": hook.get(
                "confidential_note_events",
                False,
            ),
            "job_events": hook.get(
                "job_events",
                False,
            ),
            "pipeline_events": hook.get(
                "pipeline_events",
                False,
            ),
            "wiki_page_events": hook.get(
                "wiki_page_events",
                False,
            ),
            "deployment_events": hook.get(
                "deployment_events",
                False,
            ),
            "releases_events": hook.get(
                "releases_events",
                False,
            ),
            "enable_ssl_verification": hook.get(
                "enable_ssl_verification",
                True,
            ),
            "token": hook.get("token"),
        }

        #
        # Remove None values
        #

        payload = {
            k: v
            for k, v in payload.items()
            if v is not None
        }

        try:

            print(f"Creating hook: {url}")

            dst.create_hook(
                destination_project["id"],
                **payload,
            )

        except Exception as e:

            print(f"Failed: {url}")
            print(e)

print()
print("=" * 70)
print("Hooks migration completed.")
print("=" * 70)
