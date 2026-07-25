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
# HELPERS
# ==========================================================

def sync_group(source_path, destination_path):

    print("=" * 70)
    print(source_path)
    print("=" * 70)

    source_group = src.find_group(
        source_path
    )

    if source_group is None:
        print("Source group not found.")
        return

    destination_group = dst.find_group(
        destination_path
    )

    if destination_group is None:
        print("Destination group not found.")
        return

    #
    # Variables
    #

    source_variables = src.list_group_variables(
        source_group["id"]
    )

    destination_variables = {
        variable["key"]: variable
        for variable in dst.list_group_variables(
            destination_group["id"]
        )
    }

    if not source_variables:
        print("No variables.")

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

                dst.update_group_variable(
                    destination_group["id"],
                    key,
                    **payload,
                )

            else:

                print(f"Creating {key}")

                dst.create_group_variable(
                    destination_group["id"],
                    **payload,
                )

        except Exception as e:

            print(f"Failed: {key}")
            print(e)

    #
    # Child Groups
    #

    children = src._paginate(
        f"/groups/{source_group['id']}/subgroups"
    )

    for child in children:

        child_source = child["full_path"]

        relative = child_source.replace(
            SOURCE_GROUP,
            "",
            1,
        ).lstrip("/")

        child_destination = (
            DEST_ROOT_GROUP
            + "/"
            + relative
        )

        sync_group(
            child_source,
            child_destination,
        )


# ==========================================================
# START
# ==========================================================

sync_group(
    SOURCE_GROUP,
    DEST_ROOT_GROUP,
)

print()
print("=" * 70)
print("Group variables migration completed.")
print("=" * 70)
