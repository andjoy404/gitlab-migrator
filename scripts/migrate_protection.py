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
    # Source protections
    #

    source_protected = src.list_protected_branches(
        project["id"]
    )

    if not source_protected:

        print("No protected branches.")

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
    # Existing protections
    #

    destination_protected = {
        branch["name"]: branch
        for branch in dst.list_protected_branches(
            destination_project["id"]
        )
    }

    #
    # Sync protections
    #

    for branch in source_protected:

        branch_name = branch["name"]

        if branch_name in destination_protected:

            print(
                f"Protected branch already exists: {branch_name}"
            )

            continue

        payload = {
            "name": branch_name,
        }

        #
        # Push access levels
        #

        if branch.get("push_access_levels"):

            payload["allowed_to_push"] = [
                {
                    "access_level": item["access_level"]
                }
                for item in branch["push_access_levels"]
                if item.get("access_level") is not None
            ]

        #
        # Merge access levels
        #

        if branch.get("merge_access_levels"):

            payload["allowed_to_merge"] = [
                {
                    "access_level": item["access_level"]
                }
                for item in branch["merge_access_levels"]
                if item.get("access_level") is not None
            ]

        #
        # Unprotect access levels
        #

        if branch.get("unprotect_access_levels"):

            payload["allowed_to_unprotect"] = [
                {
                    "access_level": item["access_level"]
                }
                for item in branch["unprotect_access_levels"]
                if item.get("access_level") is not None
            ]

        #
        # Optional settings
        #

        if "allow_force_push" in branch:
            payload["allow_force_push"] = branch[
                "allow_force_push"
            ]

        if "code_owner_approval_required" in branch:
            payload["code_owner_approval_required"] = branch[
                "code_owner_approval_required"
            ]

        try:

            print(
                f"Protecting branch: {branch_name}"
            )

            dst.protect_branch(
                destination_project["id"],
                **payload,
            )

        except Exception as e:

            print(
                f"Failed: {branch_name}"
            )

            print(e)

print()
print("=" * 70)
print("Protected branches migration completed.")
print("=" * 70)
