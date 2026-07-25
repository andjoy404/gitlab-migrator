# GitLab Group Migrator

[![CI](https://github.com/andjoy404/gitlab-migrator/actions/workflows/ci.yml/badge.svg)](https://github.com/andjoy404/gitlab-migrator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)

Migrate GitLab repositories, merge-request history, runners, pipeline audit
records, and container images from one GitLab instance to another.

Generated exports, checkpoints, results, and error logs are stored in `output/`.
Most workflows resume from successful checkpoints after interruption.

## Project layout

```text
main.py                  Source-checkout compatibility launcher
src/gitlab_migrator/     CLI, shared modules, and command implementations

keys/                    Runner SSH keys; never commit
workspace/               Temporary repository mirrors; never commit
output/                  Results, checkpoints, exports, and error logs
```

## Setup

Install the CLI directly from GitHub with `pipx`:

```bash
pipx install git+https://github.com/andjoy404/gitlab-migrator.git
gitlab-migrator --help
```

The SSH form also works when your GitHub SSH key is configured:

```bash
pipx install git+ssh://git@github.com/andjoy404/gitlab-migrator.git
```

Upgrade an existing installation after a new release:

```bash
pipx upgrade gitlab-migrator
```

If pipx cannot detect the new GitHub revision, force a reinstall:

```bash
pipx install --force git+https://github.com/andjoy404/gitlab-migrator.git
```

### Migrating from version 0.1.x

The distribution was renamed from `gitlab-group-migrator` to
`gitlab-migrator` in version 0.2.0. Remove the old pipx package once, then
install the renamed package:

```bash
pipx uninstall gitlab-group-migrator
pipx install git+https://github.com/andjoy404/gitlab-migrator.git
```

Future upgrades use the same name as the executable:

```bash
pipx upgrade gitlab-migrator
```

For local development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

The original `python3 main.py ...` launcher remains available from a checkout.
Installed users can run the same subcommands with `gitlab-migrator`.

Runtime files default to `./output` and `./workspace`. Use `--env-file`,
`--output-dir`, and `--workspace-dir` before the subcommand to customize them.

Copy the example configuration and replace its placeholder values:

```bash
cp .env.example .env
$EDITOR .env
```

The six GitLab connection variables at the top are required. Registry
credentials are needed only for container-registry commands; filters and
runtime paths are optional. See [.env.example](.env.example) for descriptions.

Never commit the resulting `.env`, `keys/`, `workspace/`, or `output/`.

## Command reference

Run `gitlab-migrator --help` to list all commands:

| Task | Command |
|---|---|
| Repositories and recent MRs | `gitlab-migrator migrate` |
| Only recent MRs | `gitlab-migrator migrate-merge-requests --days 30` |
| Project variables | `gitlab-migrator migrate-variables` |
| Group variables | `gitlab-migrator migrate-group-variables` |
| Project hooks | `gitlab-migrator migrate-hooks` |
| Branch protection | `gitlab-migrator migrate-protection` |
| Export runners | `gitlab-migrator export-runners` |
| Deploy paused runners | `gitlab-migrator deploy-runners` |
| Resume deployed runners | `gitlab-migrator resume-runners` |
| Export pipeline audit history | `gitlab-migrator export-pipelines --days 30` |
| Replay pipelines as new runs | `gitlab-migrator replay-pipelines` |
| Cancel active/stuck pipelines | `gitlab-migrator cancel-pipelines` |
| Migrate recent registry images | `gitlab-migrator migrate-registry --days 30` |
| Configure registry retention | `gitlab-migrator set-registry-retention --day 7` |
| Purge old registry images | `gitlab-migrator purge-registry-images --days 7` |
| Purge every registry image | `gitlab-migrator purge-registry-images --all` |

Deletion, cancellation, and retention commands are dry runs unless `--execute`
is supplied.

## Repositories and merge requests

Migrate repositories, then MRs updated during the last 30 days:

```bash
gitlab-migrator migrate
```

Use another MR window or run repositories concurrently:

```bash
gitlab-migrator migrate --days 14
MIGRATE_WORKERS=4 gitlab-migrator migrate
```

Limit migration to one source project or subgroup. Set only one filter:

```bash
MIGRATE_PROJECT='source-group/team/project' gitlab-migrator migrate
MIGRATE_GROUP='source-group/team' gitlab-migrator migrate
```

Retry only merge requests without mirroring repositories:

```bash
gitlab-migrator migrate-merge-requests --days 30
```

Open MRs remain open. Closed and merged source MRs become closed historical
records containing original state, author, timestamps, source link, labels, and
notes. GitLab cannot import an immutable MR as already merged without performing
a new merge, so historical merged MRs do not appear in the destination
**Merged** tab.

Use `--reset` on the standalone MR command to clear its successful checkpoints.

## Runners

Export runners:

```bash
gitlab-migrator export-runners
RUNNER_GROUP='source-group/team' gitlab-migrator export-runners
```

Deploy equivalent paused runners on their existing hosts:

```bash
gitlab-migrator deploy-runners
```

The deployer:

- tries SSH agent/default identities and private keys from `keys/`;
- prompts for custom port, username, key, or password after automatic failure;
- reuses one SSH connection and manual settings per host;
- reads `/etc/gitlab-runner/config.toml` with passwordless sudo;
- asks which configuration matches when a host has multiple runners;
- preserves shell/Docker executor settings, Docker image, and volumes;
- supports old Runner clients with compatible token flags;
- creates destination runners as paused; and
- skips successful source-runner checkpoints on reruns.

Passwords are handled by OpenSSH and never stored. The remote user needs
passwordless sudo to read the configuration and invoke `gitlab-runner`.

Use a short timeout for destroyed hosts:

```bash
RUNNER_SSH_CONNECT_TIMEOUT=2 gitlab-migrator deploy-runners
```

After reviewing paused runners, enable successful registrations:

```bash
gitlab-migrator resume-runners
```

## Pipelines

GitLab cannot import historical pipelines. Export an audit archive:

```bash
gitlab-migrator export-pipelines --days 30
```

Changing the window requires a new snapshot:

```bash
gitlab-migrator export-pipelines --days 7 --reset
```

Replay creates new pipelines using current destination code, variables, and CI
rules. It does not preserve original IDs, timestamps, jobs, or statuses:

```bash
gitlab-migrator replay-pipelines
gitlab-migrator replay-pipelines --all-records
```

The default replays only the newest record per project/ref. Merge-request refs
are skipped. Destination CI rules must permit `CI_PIPELINE_SOURCE == "api"` or
GitLab may reject the request because the resulting pipeline would be empty.

### Cancel active and stuck pipelines

Preview, then execute:

```bash
gitlab-migrator cancel-pipelines
gitlab-migrator cancel-pipelines --execute
```

Filter by project, job age, and manual jobs:

```bash
gitlab-migrator cancel-pipelines \
  --project destination-group/team/project \
  --hours 48 \
  --include-manual \
  --execute
```

The command checks active pipelines and project-level jobs, including jobs in
child/downstream pipelines. Manual jobs are preserved unless
`--include-manual` is supplied.

## Container Registry

Install [Skopeo](https://github.com/containers/skopeo) before image migration or
raw image-age inspection.

### Migrate recent images

```bash
gitlab-migrator migrate-registry --days 30
```

The checkpoint stores one fixed cutoff. To change from 30 to 7 days:

```bash
gitlab-migrator migrate-registry --days 7 --reset
```

`--reset` clears local migration checkpoints; it does not delete destination
images. Images copied by a wider earlier run remain in the destination.

### Scheduled retention

Preview and apply a three-day policy:

```bash
gitlab-migrator set-registry-retention --day 3
gitlab-migrator set-registry-retention --day 3 --execute
```

`--day` and `--days` are aliases. Supported values are `1`, `3`, `7`, `14`,
`30`, `60`, `90`, `180`, `365`, `730`, and `1095`. The policy runs daily,
matches all tag names, and keeps the newest tag per image. GitLab always
excludes `latest`, protected tags, and immutable tags.

### Purge by raw image creation time

This command uses `skopeo inspect` and compares the raw image configuration's
`Created` timestamp, not the destination push/publish date.

```bash
gitlab-migrator purge-registry-images --days 7
gitlab-migrator purge-registry-images --days 7 --execute
```

`latest` is skipped unless `--include-latest` is supplied. Limit the operation
with `--project destination-group/team/project`.

### Purge every image tag

Preview every deletable tag, then execute:

```bash
gitlab-migrator purge-registry-images --all
gitlab-migrator purge-registry-images --all --execute
```

`--all` includes `latest`. Protected tags cannot be deleted. Deleting tags does
not reclaim blob storage immediately; the registry administrator must run
garbage collection.

## Output files

| Workflow | Results/archive | Errors/progress |
|---|---|---|
| Repositories | N/A | `output/migration_errors.log` |
| Merge requests | `output/merge_request_migration_results.json` | `output/merge_request_migration_errors.log` |
| Runner export | `output/runners.json` | N/A |
| Runner deployment | `output/runner_deployment_results.json` | `output/runner_creation_errors.log`, `output/runner_ssh_errors.log` |
| Pipeline export | `output/pipeline_history.json` | `output/pipeline_history_progress.json`, `output/pipeline_history_errors.log` |
| Pipeline replay | `output/pipeline_replay_results.json` | `output/pipeline_history_errors.log` |
| Pipeline cancellation | `output/pipeline_cancel_results.json` | `output/pipeline_cancel_errors.log` |
| Registry migration | `output/container_registry_results.json` | `output/container_registry_progress.json`, `output/container_registry_errors.log` |
| Registry retention | `output/registry_retention_results.json` | `output/registry_retention_errors.log` |
| Registry purge | `output/registry_purge_results.json` | `output/registry_purge_errors.log` |

Successful item-level operations are saved immediately or atomically. Reruns
skip successful checkpoints and retry unfinished items. Most error logs use
JSON Lines so progress survives interruption.

## Troubleshooting

### Different window already checkpointed

Use the relevant `--reset` option when changing days. Resetting a checkpoint
does not undo destination changes.

### Custom runner SSH port

Enter it when prompted, or set the default:

```bash
gitlab-migrator deploy-runners --port 2222
```

### `sudo: gitlab-runner: command not found`

Restart with the latest script. It discovers the absolute executable path to
avoid sudo's restricted PATH. Verify manually:

```bash
command -v gitlab-runner
sudo -n /usr/local/bin/gitlab-runner --version
```

### Pipeline replay produces an empty pipeline

Permit `CI_PIPELINE_SOURCE == "api"` in the destination workflow and job rules
before replaying.

