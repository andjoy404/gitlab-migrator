#!/usr/bin/env python3
"""Export self-hosted group and project runners from the source group.

GitLab no longer guarantees an IP address for every runner.  A usable reported
IP is therefore the explicit criterion for inclusion: it lets the deployment
tool locate the existing Ubuntu host.  The export never contains tokens.
"""

import json
import os

try:
    from .bootstrap import configure_import_path
except ImportError:
    from bootstrap import configure_import_path

configure_import_path()

from gitlab_migrator.config import SOURCE_GROUP, SOURCE_TOKEN, SOURCE_URL, validate
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


OUTPUT_FILE = output_path("runners.json")
ERROR_FILE = output_path("runner_export_errors.log")


def runner_record(runner, runner_type, source_scope_path):
    """Keep only portable, non-secret runner metadata."""

    return {
        "source_runner_id": runner["id"],
        "runner_type": runner_type,
        "source_scope_path": source_scope_path,
        "description": runner.get("description") or runner.get("name"),
        "ip_address": runner.get("ip_address") or "",
        "tag_list": runner.get("tag_list") or [],
        "run_untagged": runner.get("run_untagged", False),
        "locked": runner.get("locked", False),
        "access_level": runner.get("access_level", "not_protected"),
        "maximum_timeout": runner.get("maximum_timeout"),
        "maintenance_note": runner.get("maintenance_note"),
    }


def collect_groups(api, root_group):
    """Return the root group and all of its descendants."""

    groups = [root_group]
    pending = [root_group]

    while pending:
        parent = pending.pop(0)
        children = api._paginate(f"/groups/{parent['id']}/subgroups")
        groups.extend(children)
        pending.extend(children)

    return groups


def get_detail(api, runner):
    """Use the detailed endpoint when the current token can access it."""

    try:
        detail = api.get_runner(runner["id"])
    except Exception:
        return runner

    if not detail.get("ip_address"):
        detail["ip_address"] = runner.get("ip_address")

    if not detail.get("ip_address"):
        try:
            managers = api.list_runner_managers(runner["id"])
            online = [
                manager
                for manager in managers
                if manager.get("status") == "online"
            ]
            selected = (online or managers)

            if selected:
                detail["ip_address"] = selected[0].get("ip_address", "")
        except Exception:
            pass

    return detail


def main():
    validate()
    api = GitLabAPI(SOURCE_URL, SOURCE_TOKEN)
    records = {}
    errors = []

    try:
        print("Connecting to source GitLab...")
        root_group = api.get_group(SOURCE_GROUP)
        groups = collect_groups(api, root_group)
        projects = api.list_projects(SOURCE_GROUP)

        group_filter = os.getenv("RUNNER_GROUP")

        if group_filter:
            group_filter = group_filter.strip("/")
            source_root = SOURCE_GROUP.strip("/")

            if (
                group_filter != source_root
                and not group_filter.startswith(source_root + "/")
            ):
                raise RuntimeError(
                    "RUNNER_GROUP must be SOURCE_GROUP or one of its subgroups."
                )

            groups = [
                group
                for group in groups
                if group["full_path"] == group_filter
                or group["full_path"].startswith(group_filter + "/")
            ]
            projects = [
                project
                for project in projects
                if project["path_with_namespace"].startswith(
                    group_filter + "/"
                )
            ]

            print(f"Exporting only runners in: {group_filter}")

        print(f"Found {len(groups)} groups and {len(projects)} projects.")
        print()

        for index, group in enumerate(groups, start=1):
            try:
                runners = api.list_group_runners(group["id"])
                print(
                    f"[Group {index}/{len(groups)}] "
                    f"{group['full_path']} ({len(runners)} runners)"
                )

                for runner in runners:
                    detail = get_detail(api, runner)

                    if detail.get("runner_type") != "group_type":
                        continue

                    if not detail.get("ip_address"):
                        continue

                    records.setdefault(
                        detail["id"],
                        runner_record(
                            detail,
                            "group_type",
                            group["full_path"],
                        ),
                    )
            except Exception as error:
                errors.append(f"Group {group['full_path']}: {error}")

        for index, project in enumerate(projects, start=1):
            try:
                runners = api.list_project_runners(project["id"])
                print(
                    f"[Project {index}/{len(projects)}] "
                    f"{project['path_with_namespace']} "
                    f"({len(runners)} runners)"
                )

                for runner in runners:
                    detail = get_detail(api, runner)

                    if detail.get("runner_type") != "project_type":
                        continue

                    if not detail.get("ip_address"):
                        continue

                    records.setdefault(
                        detail["id"],
                        runner_record(
                            detail,
                            "project_type",
                            project["path_with_namespace"],
                        ),
                    )
            except Exception as error:
                errors.append(
                    f"Project {project['path_with_namespace']}: {error}"
                )

        with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
            json.dump(list(records.values()), file, indent=2)

        if errors:
            with open(ERROR_FILE, "w", encoding="utf-8") as file:
                file.write("\n".join(errors) + "\n")

        print(f"Exported {len(records)} Ubuntu-hosted runners to {OUTPUT_FILE}")

        if errors:
            print(f"Some runner metadata could not be exported: {ERROR_FILE}")

    finally:
        api.close()


if __name__ == "__main__":
    main()
