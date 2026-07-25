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
    # Source variables
    #

    source_variables = src.list_project_variables(
        project["id"]
    )

    if not source_variables:

        print("No variables.")

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
    # Existing destination variables
    #

    destination_variables = {
        item["key"]: item
        for item in dst.list_project_variables(
            destination_project["id"]
        )
    }

    #
    # Sync variables
    #

    for variable in source_variables:

        key = variable["key"]

        payload = {
            "key": key,
            "value": variable["value"],
            "variable_type": variable.get(
                "variable_type",
                "env_var",
            ),
            "protected": variable.get(
                "protected",
                False,
            ),
            "masked": variable.get(
                "masked",
                False,
            ),
            "hidden": variable.get(
                "hidden",
                False,
            ),
            "raw": variable.get(
                "raw",
                False,
            ),
            "environment_scope": variable.get(
                "environment_scope",
                "*",
            ),
            "description": variable.get(
                "description",
                "",
            ),
        }

        try:

            if key in destination_variables:

                print(f"Updating {key}")

                dst.update_project_variable(
                    destination_project["id"],
                    key,
                    **payload,
                )

            else:

                print(f"Creating {key}")

                dst.create_project_variable(
                    destination_project["id"],
                    **payload,
                )

        except Exception as e:

            print(
                f"Failed: {key}"
            )

            print(e)

print()
print("=" * 70)
print("Project variables migration completed.")
print("=" * 70)
