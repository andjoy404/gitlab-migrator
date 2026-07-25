import json

from .gitlab_api import GitLabAPI


# ==========================================================
# Export
# ==========================================================

def export_protected_branches(
    api: GitLabAPI,
    project_id,
):

    protections = api.list_protected_branches(
        project_id
    )

    print(
        f"Found {len(protections)} protected branches"
    )

    return protections


# ==========================================================
# Disable
# ==========================================================

def disable_protected_branches(
    api: GitLabAPI,
    project_id,
):

    protections = export_protected_branches(
        api,
        project_id,
    )

    if not protections:

        print("No protected branches.")

        return []

    for branch in protections:

        name = branch["name"]

        print(
            f"Removing protection: {name}"
        )

        api.unprotect_branch(
            project_id,
            name,
        )

    return protections


# ==========================================================
# Restore
# ==========================================================

def restore_protected_branches(
    api: GitLabAPI,
    project_id,
    protections,
):

    if not protections:

        return

    print()

    print(
        "Restoring protected branches..."
    )

    for branch in protections:

        payload = {
            "name": branch["name"],
        }

        #
        # Push access
        #

        if branch.get(
            "push_access_levels"
        ):

            payload[
                "push_access_level"
            ] = branch[
                "push_access_levels"
            ][0][
                "access_level"
            ]

        #
        # Merge access
        #

        if branch.get(
            "merge_access_levels"
        ):

            payload[
                "merge_access_level"
            ] = branch[
                "merge_access_levels"
            ][0][
                "access_level"
            ]

                #
        # Allow force push
        #

        payload[
            "allow_force_push"
        ] = branch.get(
            "allow_force_push",
            False,
        )

        #
        # Code owner approval
        #

        payload[
            "code_owner_approval_required"
        ] = branch.get(
            "code_owner_approval_required",
            False,
        )

        try:

            print(
                f"Restoring: {branch['name']}"
            )

            api.protect_branch(
                project_id,
                **payload,
            )

        except Exception as e:

            #
            # Don't stop migration because
            # one branch couldn't be restored.
            #

            print(
                f"WARNING: Failed restoring {branch['name']}"
            )

            print(e)


# ==========================================================
# Save / Load (optional)
# ==========================================================

def save_protected_branches(
    filename,
    protections,
):

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            protections,
            f,
            indent=2,
        )


def load_protected_branches(
    filename,
):

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as f:

        return json.load(f)


# ==========================================================
# All-in-one helper
# ==========================================================

def migrate_protected_branches(
    src,
    dst,
    source_project_id,
    destination_project_id,
):

    protections = export_protected_branches(
        src,
        source_project_id,
    )

    disable_protected_branches(
        dst,
        destination_project_id,
    )

    return protections
