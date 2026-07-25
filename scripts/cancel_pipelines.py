#!/usr/bin/env python3
"""Cancel active pipelines and stuck jobs under the destination group."""

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
    DEST_ROOT_GROUP,
    DEST_TOKEN,
    DEST_URL,
    validate,
)
from gitlab_migrator.gitlab_api import GitLabAPI
from gitlab_migrator.paths import output_path


ACTIVE_PIPELINE_STATUSES = (
    "created",
    "waiting_for_resource",
    "preparing",
    "waiting_for_callback",
    "pending",
    "running",
    "canceling",
    "scheduled",
)
STUCK_JOB_STATUSES = {
    "created",
    "waiting_for_resource",
    "preparing",
    "waiting_for_callback",
    "pending",
    "running",
    "canceling",
    "scheduled",
}
ERROR_FILE = output_path("pipeline_cancel_errors.log")
RESULTS_FILE = output_path("pipeline_cancel_results.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def append_error(entry):
    record = dict(entry)
    record["recorded_at"] = utc_now()

    with ERROR_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_results():
    if not RESULTS_FILE.exists():
        return []

    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    if not isinstance(results, list):
        raise RuntimeError(f"{RESULTS_FILE} must contain a JSON list")

    return results


def checkpoint_results(results):
    temporary = RESULTS_FILE.with_name(RESULTS_FILE.name + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(results, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(RESULTS_FILE)


def destination_projects(api, project_filter):
    if not project_filter:
        return api.list_projects(DEST_ROOT_GROUP)

    root = DEST_ROOT_GROUP.strip("/")
    requested = project_filter.strip("/")

    if requested != root and not requested.startswith(root + "/"):
        raise RuntimeError(
            "--project must be DEST_ROOT_GROUP or one of its projects."
        )

    project = api.find_project(requested)

    if project is None:
        raise RuntimeError(f"Destination project not found: {requested}")

    return [project]


def candidate_pipelines(api, project, updated_after, include_manual):
    """Return all active pipelines plus recent pipelines whose jobs need inspection."""

    pipelines = {}
    listing_failures = 0
    statuses = list(ACTIVE_PIPELINE_STATUSES)

    if include_manual:
        statuses.append("manual")

    for status in statuses:
        try:
            for pipeline in api.list_pipelines(project["id"], status=status):
                pipelines[pipeline["id"]] = pipeline
        except Exception as error:
            append_error({
                "stage": "list_pipelines",
                "project_id": project["id"],
                "project_path": project["path_with_namespace"],
                "status": status,
                "error": str(error),
            })
            listing_failures += 1
            print(f"  Failed listing status {status}: {error}", flush=True)

    try:
        for pipeline in api.list_pipelines(
            project["id"],
            updated_after=updated_after,
        ):
            pipelines[pipeline["id"]] = pipeline
    except Exception as error:
        append_error({
            "stage": "list_recent_pipelines",
            "project_id": project["id"],
            "project_path": project["path_with_namespace"],
            "updated_after": updated_after,
            "error": str(error),
        })
        listing_failures += 1
        print(f"  Failed listing recent pipelines: {error}", flush=True)

    return list(pipelines.values()), listing_failures


def cancellable_jobs(api, project, pipeline, include_manual):
    jobs = api.list_pipeline_jobs(project["id"], pipeline["id"])
    statuses = set(STUCK_JOB_STATUSES)

    if include_manual:
        statuses.add("manual")

    return [job for job in jobs if job.get("status") in statuses]


def save_result(results, record):
    results.append(record)
    checkpoint_results(results)


def cancel_one_job(api, results, project, pipeline, job):
    force = job.get("status") == "canceling"
    response = api.cancel_job(project["id"], job["id"], force=force)
    save_result(results, {
        "record_type": "job",
        "project_id": project["id"],
        "project_path": project["path_with_namespace"],
        "pipeline_id": pipeline["id"],
        "job_id": job["id"],
        "job_name": job.get("name"),
        "previous_status": job.get("status"),
        "result_status": (
            response.get("status") if isinstance(response, dict) else "canceled"
        ),
        "canceled_at": utc_now(),
    })


def cancel_one_pipeline(api, results, project, pipeline):
    response = api.cancel_pipeline(project["id"], pipeline["id"])
    save_result(results, {
        "record_type": "pipeline",
        "project_id": project["id"],
        "project_path": project["path_with_namespace"],
        "pipeline_id": pipeline["id"],
        "ref": pipeline.get("ref"),
        "previous_status": pipeline.get("status"),
        "result_status": (
            response.get("status") if isinstance(response, dict) else "canceled"
        ),
        "canceled_at": utc_now(),
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually cancel pipelines/jobs; otherwise perform a dry run.",
    )
    parser.add_argument(
        "--project",
        help="Limit cancellation to one full destination project path.",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=24,
        help="Inspect jobs in finished pipelines updated within this many hours.",
    )
    parser.add_argument(
        "--include-manual",
        action="store_true",
        help="Also cancel optional manual jobs (the orange pause icons).",
    )
    args = parser.parse_args()

    if args.hours <= 0:
        raise RuntimeError("--hours must be greater than zero.")

    validate()
    api = GitLabAPI(DEST_URL, DEST_TOKEN)
    results = load_results()
    pipeline_found_count = 0
    pipeline_canceled_count = 0
    job_found_count = 0
    job_canceled_count = 0
    failed_count = 0
    updated_after = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=args.hours)
    ).isoformat()

    try:
        try:
            projects = destination_projects(api, args.project)
        except Exception as error:
            append_error({
                "stage": "list_projects",
                "destination_group": DEST_ROOT_GROUP,
                "project_filter": args.project,
                "error": str(error),
            })
            raise RuntimeError(
                f"Cannot list destination projects; failure saved to {ERROR_FILE}"
            ) from error

        mode = "EXECUTE" if args.execute else "DRY RUN"
        print(f"Mode: {mode}")
        print(f"Found {len(projects)} destination projects.")
        print(
            f"Inspecting active pipelines and jobs in pipelines updated during "
            f"the last {args.hours:g} hours."
        )

        if args.include_manual:
            print("Optional manual jobs will also be canceled.")

        print()

        for project_index, project in enumerate(projects, start=1):
            project_path = project["path_with_namespace"]
            print(
                f"[Project {project_index}/{len(projects)}] {project_path}",
                flush=True,
            )
            pipelines, listing_failures = candidate_pipelines(
                api,
                project,
                updated_after,
                args.include_manual,
            )
            failed_count += listing_failures
            pipelines.sort(key=lambda item: item["id"])
            project_actions = 0
            handled_job_ids = set()

            for pipeline in pipelines:
                pipeline_status = pipeline.get("status")
                pipeline_is_active = pipeline_status in ACTIVE_PIPELINE_STATUSES

                if args.include_manual and pipeline_status == "manual":
                    pipeline_is_active = True

                try:
                    jobs = cancellable_jobs(
                        api,
                        project,
                        pipeline,
                        args.include_manual,
                    )
                except Exception as error:
                    append_error({
                        "stage": "list_pipeline_jobs",
                        "project_id": project["id"],
                        "project_path": project_path,
                        "pipeline_id": pipeline["id"],
                        "pipeline_status": pipeline_status,
                        "error": str(error),
                    })
                    failed_count += 1
                    print(
                        f"  Failed listing jobs for pipeline {pipeline['id']}: "
                        f"{error}",
                        flush=True,
                    )
                    jobs = []

                if not pipeline_is_active and not jobs:
                    continue

                project_actions += 1
                pipeline_label = (
                    f"  Pipeline {pipeline['id']} "
                    f"ref={pipeline.get('ref', 'unknown')} "
                    f"status={pipeline_status or 'unknown'}"
                )

                if pipeline_is_active:
                    pipeline_found_count += 1

                    if not args.execute:
                        print(f"{pipeline_label} - would cancel pipeline", flush=True)
                    else:
                        print(pipeline_label, flush=True)

                        try:
                            cancel_one_pipeline(api, results, project, pipeline)
                            pipeline_canceled_count += 1
                            print("    Pipeline canceled (checkpoint saved)", flush=True)
                            continue
                        except Exception as error:
                            append_error({
                                "stage": "cancel_pipeline",
                                "project_id": project["id"],
                                "project_path": project_path,
                                "pipeline_id": pipeline["id"],
                                "ref": pipeline.get("ref"),
                                "status": pipeline_status,
                                "error": str(error),
                            })
                            failed_count += 1
                            print(
                                f"    Pipeline cancellation failed: {error}; "
                                "trying its jobs individually.",
                                flush=True,
                            )

                for job_index, job in enumerate(jobs, start=1):
                    handled_job_ids.add(job["id"])
                    job_found_count += 1
                    job_label = (
                        f"    [Job {job_index}/{len(jobs)}] ID {job['id']} "
                        f"name={job.get('name', 'unknown')} "
                        f"status={job.get('status', 'unknown')}"
                    )

                    if not args.execute:
                        print(f"{job_label} - would cancel", flush=True)
                        continue

                    print(job_label, flush=True)

                    try:
                        cancel_one_job(api, results, project, pipeline, job)
                        job_canceled_count += 1
                        print("      Job canceled (checkpoint saved)", flush=True)
                    except Exception as error:
                        append_error({
                            "stage": "cancel_job",
                            "project_id": project["id"],
                            "project_path": project_path,
                            "pipeline_id": pipeline["id"],
                            "job_id": job["id"],
                            "job_name": job.get("name"),
                            "status": job.get("status"),
                            "error": str(error),
                        })
                        failed_count += 1
                        print(f"      Failed: {error}", flush=True)

            # Query jobs directly at project level as a second discovery path.
            # This catches jobs in child/downstream pipelines that are omitted
            # from the default project pipeline listing.
            direct_statuses = set(STUCK_JOB_STATUSES)

            if args.include_manual:
                direct_statuses.add("manual")

            try:
                direct_jobs = api.list_project_jobs(
                    project["id"],
                    statuses=sorted(direct_statuses),
                )
            except Exception as error:
                append_error({
                    "stage": "list_project_jobs",
                    "project_id": project["id"],
                    "project_path": project_path,
                    "statuses": sorted(direct_statuses),
                    "error": str(error),
                })
                failed_count += 1
                print(f"  Failed direct stuck-job listing: {error}", flush=True)
                direct_jobs = []

            direct_jobs = [
                job
                for job in direct_jobs
                if job["id"] not in handled_job_ids
                and job.get("status") in direct_statuses
            ]

            if direct_jobs:
                project_actions += 1
                print(
                    f"  Found {len(direct_jobs)} additional stuck jobs "
                    "through direct project job discovery.",
                    flush=True,
                )

            for job_index, job in enumerate(direct_jobs, start=1):
                job_found_count += 1
                pipeline_data = job.get("pipeline") or {}
                pipeline = {
                    "id": pipeline_data.get("id"),
                    "ref": pipeline_data.get("ref") or job.get("ref"),
                    "status": pipeline_data.get("status"),
                }
                job_label = (
                    f"    [Direct job {job_index}/{len(direct_jobs)}] "
                    f"ID {job['id']} name={job.get('name', 'unknown')} "
                    f"status={job.get('status', 'unknown')} "
                    f"pipeline={pipeline.get('id', 'unknown')}"
                )

                if not args.execute:
                    print(f"{job_label} - would cancel", flush=True)
                    continue

                print(job_label, flush=True)

                try:
                    cancel_one_job(api, results, project, pipeline, job)
                    job_canceled_count += 1
                    print("      Job canceled (checkpoint saved)", flush=True)
                except Exception as error:
                    append_error({
                        "stage": "cancel_job",
                        "discovery": "project_jobs",
                        "project_id": project["id"],
                        "project_path": project_path,
                        "pipeline_id": pipeline.get("id"),
                        "job_id": job["id"],
                        "job_name": job.get("name"),
                        "status": job.get("status"),
                        "tag_list": job.get("tag_list") or [],
                        "error": str(error),
                    })
                    failed_count += 1
                    print(f"      Failed: {error}", flush=True)

            if project_actions == 0:
                print("  No active pipelines or stuck jobs.", flush=True)

        print()

        if args.execute:
            print(
                "Cancellation complete: "
                f"{pipeline_canceled_count}/{pipeline_found_count} pipelines and "
                f"{job_canceled_count}/{job_found_count} jobs canceled; "
                f"{failed_count} failures."
            )
        else:
            print(
                f"Dry run complete: {pipeline_found_count} active pipelines and "
                f"{job_found_count} stuck jobs would be canceled; "
                f"{failed_count} listing failures."
            )
            print("Run again with --execute to cancel them.")

        if failed_count:
            print(f"Failures: {ERROR_FILE}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
