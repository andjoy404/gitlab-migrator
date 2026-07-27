"""Shared inclusion and exclusion filters for source GitLab projects."""

import os


def comma_separated_paths(name):
    """Return normalized, unique paths from a comma-separated environment value."""

    return {
        value.strip().strip("/")
        for value in os.getenv(name, "").split(",")
        if value.strip().strip("/")
    }


def validate_exclusions(source_group, excluded_projects, excluded_groups):
    """Reject exclusions outside the configured source group."""

    source_root = source_group.strip("/")
    invalid_projects = sorted(
        path
        for path in excluded_projects
        if not path.startswith(source_root + "/")
    )
    invalid_groups = sorted(
        path
        for path in excluded_groups
        if path != source_root and not path.startswith(source_root + "/")
    )
    invalid = invalid_projects + invalid_groups
    if invalid:
        raise RuntimeError(
            "Exclusion paths must be SOURCE_GROUP or one of its descendants: "
            + ", ".join(invalid)
        )


def apply_project_exclusions(projects, source_group):
    """Exclude exact projects and every project below excluded group subtrees."""

    excluded_projects = comma_separated_paths("EXCLUDE_PROJECTS")
    excluded_groups = comma_separated_paths("EXCLUDE_GROUPS")
    validate_exclusions(source_group, excluded_projects, excluded_groups)

    included = []
    excluded = []
    for project in projects:
        path = project["path_with_namespace"].strip("/")
        is_excluded = path in excluded_projects or any(
            path == group or path.startswith(group + "/")
            for group in excluded_groups
        )
        (excluded if is_excluded else included).append(project)
    return included, excluded
