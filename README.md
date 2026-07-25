# GitLab Group Migrator

Migrate GitLab repositories, merge-request history, runners, pipeline audit
records, and container images from one GitLab instance to another.

Generated exports, checkpoints, results, and error logs are stored in `output/`.
Most workflows resume from successful checkpoints after interruption.

## Project layout

```text
main.py                  Command launcher
scripts/                 Migration and administration commands
src/gitlab_migrator/     Shared API and migration modules
tools/                   H200 synchronization scripts
keys/                    Runner SSH keys; never commit
workspace/               Temporary repository mirrors; never commit
output/                  Results, checkpoints, exports, and error logs
```

## Setup

Install the CLI directly from GitHub with `pipx`:

```bash
pipx install github.com/andjoy404/gitlab-migrator.git
gitlab-migrator --help
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

Create a non-committed `.env` file:

```dotenv
SOURCE_URL=https://gitlab.com
SOURCE_TOKEN=source-api-token
SOURCE_GROUP=source-group

DEST_URL=https://gitlab.example.com
DEST_TOKEN=destination-api-token
DEST_ROOT_GROUP=destination-group

SOURCE_REGISTRY=registry.gitlab.com
SOURCE_REGISTRY_USER=source-registry-user
SOURCE_REGISTRY_TOKEN=source-token-with-read_registry

DEST_REGISTRY=registry.example.com
DEST_REGISTRY_USER=destination-registry-user
DEST_REGISTRY_TOKEN=destination-token-with-write_registry
```

Never commit `.env`, `keys/`, `workspace/`, or `output/`.

## Command reference

Run `gitlab-migrator --help` to list all commands:

| Task | Command |
|---|---|
| Repositories and recent MRs | `python3 main.py migrate` |
| Only recent MRs | `python3 main.py migrate-merge-requests --days 30` |
| Export runners | `python3 main.py export-runners` |
| Deploy paused runners | `python3 main.py deploy-runners` |
| Resume deployed runners | `python3 main.py resume-runners` |
| Export pipeline audit history | `python3 main.py export-pipelines --days 30` |
| Replay pipelines as new runs | `python3 main.py replay-pipelines` |
| Cancel active/stuck pipelines | `python3 main.py cancel-pipelines` |
| Migrate recent registry images | `python3 main.py migrate-registry --days 30` |
| Configure registry retention | `python3 main.py set-registry-retention --day 7` |
| Purge old registry images | `python3 main.py purge-registry-images --days 7` |
| Purge every registry image | `python3 main.py purge-registry-images --all` |

Deletion, cancellation, and retention commands are dry runs unless `--execute`
is supplied.

## Synchronize the code

### Laptop to H200

```bash
./tools/sync_to_h200.sh afxsvr01@afxh200svr01 /apps/gitlab-migrator
```

Custom port and key:

```bash
H200_SSH_KEY="$HOME/.ssh/h200.pem" \
  ./tools/sync_to_h200.sh -p 2222 \
  afxsvr01@afxh200svr01 /apps/gitlab-migrator
```

Uploads exclude `.env`, `keys/`, `.venv/`, `workspace/`, Python caches, and
`output/`. The script does not use `--delete`.

### H200 to a laptop

```bash
./tools/sync_to_local.sh afxsvr01@afxh200svr01
```

Custom remote path and port:

```bash
./tools/sync_to_local.sh -p 2222 \
  afxsvr01@afxh200svr01 /other/path/gitlab-migrator
```

Downloads include `output/`, allowing both laptops to receive results,
checkpoints, and logs. Secrets, keys, virtual environments, repository
workspaces, and Python caches remain excluded.

## Repositories and merge requests

Migrate repositories, then MRs updated during the last 30 days:

```bash
python3 main.py migrate
```

Use another MR window or run repositories concurrently:

```bash
python3 main.py migrate --days 14
MIGRATE_WORKERS=4 python3 main.py migrate
```

Limit migration to one source project or subgroup. Set only one filter:

```bash
MIGRATE_PROJECT='source-group/team/project' python3 main.py migrate
MIGRATE_GROUP='source-group/team' python3 main.py migrate
```

Retry only merge requests without mirroring repositories:

```bash
python3 main.py migrate-merge-requests --days 30
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
python3 main.py export-runners
RUNNER_GROUP='source-group/team' python3 main.py export-runners
```

Deploy equivalent paused runners on their existing hosts:

```bash
python3 main.py deploy-runners
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
RUNNER_SSH_CONNECT_TIMEOUT=2 python3 main.py deploy-runners
```

After reviewing paused runners, enable successful registrations:

```bash
python3 main.py resume-runners
```

## Pipelines

GitLab cannot import historical pipelines. Export an audit archive:

```bash
python3 main.py export-pipelines --days 30
```

Changing the window requires a new snapshot:

```bash
python3 main.py export-pipelines --days 7 --reset
```

Replay creates new pipelines using current destination code, variables, and CI
rules. It does not preserve original IDs, timestamps, jobs, or statuses:

```bash
python3 main.py replay-pipelines
python3 main.py replay-pipelines --all-records
```

The default replays only the newest record per project/ref. Merge-request refs
are skipped. Destination CI rules must permit `CI_PIPELINE_SOURCE == "api"` or
GitLab may reject the request because the resulting pipeline would be empty.

### Cancel active and stuck pipelines

Preview, then execute:

```bash
python3 main.py cancel-pipelines
python3 main.py cancel-pipelines --execute
```

Filter by project, job age, and manual jobs:

```bash
python3 main.py cancel-pipelines \
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
python3 main.py migrate-registry --days 30
```

The checkpoint stores one fixed cutoff. To change from 30 to 7 days:

```bash
python3 main.py migrate-registry --days 7 --reset
```

`--reset` clears local migration checkpoints; it does not delete destination
images. Images copied by a wider earlier run remain in the destination.

### Scheduled retention

Preview and apply a three-day policy:

```bash
python3 main.py set-registry-retention --day 3
python3 main.py set-registry-retention --day 3 --execute
```

`--day` and `--days` are aliases. Supported values are `1`, `3`, `7`, `14`,
`30`, `60`, `90`, `180`, `365`, `730`, and `1095`. The policy runs daily,
matches all tag names, and keeps the newest tag per image. GitLab always
excludes `latest`, protected tags, and immutable tags.

### Purge by raw image creation time

This command uses `skopeo inspect` and compares the raw image configuration's
`Created` timestamp, not the destination push/publish date.

```bash
python3 main.py purge-registry-images --days 7
python3 main.py purge-registry-images --days 7 --execute
```

`latest` is skipped unless `--include-latest` is supplied. Limit the operation
with `--project destination-group/team/project`.

### Purge every image tag

Preview every deletable tag, then execute:

```bash
python3 main.py purge-registry-images --all
python3 main.py purge-registry-images --all --execute
```

`--all` includes `latest`. Protected tags cannot be deleted. Deleting tags does
not reclaim blob storage immediately; the registry administrator must run
garbage collection.

## Output files

| Workflow | Results/archive | Errors/progress |
|---|---|---|
| Repositories | Ã¢â‚¬â€ | `output/migration_errors.log` |
| Merge requests | `output/merge_request_migration_results.json` | `output/merge_request_migration_errors.log` |
| Runner export | `output/runners.json` | Ã¢â‚¬â€ |
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
python3 main.py deploy-runners --port 2222
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

