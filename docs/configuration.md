# Configuration

Copy the template into the directory where you will run the command:

```bash
cp .env.example .env
chmod 600 .env
```

The default configuration file is `./.env` in the current working directory.

## Required values

| Variable | Purpose |
| --- | --- |
| `SOURCE_URL` | Source GitLab base URL |
| `SOURCE_TOKEN` | Token that can read source groups and projects |
| `SOURCE_GROUP` | Full source group path |
| `DEST_URL` | Destination GitLab base URL |
| `DEST_TOKEN` | Token that can create and update destination resources |
| `DEST_ROOT_GROUP` | Destination root group path |

## Optional values

| Variable | Purpose | Default |
| --- | --- | --- |
| `MIGRATE_PROJECT` | Process one full source project path | empty |
| `MIGRATE_GROUP` | Process one source group subtree | empty |
| `MIGRATE_WORKERS` | Concurrent repository workers | `1` |
| `RUNNER_GROUP` | Limit runner export to a group | empty |
| `RUNNER_SSH_CONNECT_TIMEOUT` | Runner host SSH timeout in seconds | `5` |

Set only one of `MIGRATE_PROJECT` and `MIGRATE_GROUP`.

Registry operations additionally use `SOURCE_REGISTRY`, `SOURCE_REGISTRY_USER`, `SOURCE_REGISTRY_TOKEN`, `DEST_REGISTRY`, `DEST_REGISTRY_USER`, and `DEST_REGISTRY_TOKEN`.

## Custom locations

Global location options must come before the subcommand:

```bash
gitlab-migrator \
  --env-file /srv/gitlab-migrator/config/.env \
  --workspace-dir /srv/gitlab-migrator/data/repositories \
  --output-dir /srv/gitlab-migrator/data/reports \
  migrate all
```

You can export the same locations for repeated use:

```bash
export GITLAB_MIGRATOR_ENV_FILE=/srv/gitlab-migrator/config/.env
export GITLAB_MIGRATOR_WORKSPACE_DIR=/srv/gitlab-migrator/data/repositories
export GITLAB_MIGRATOR_OUTPUT_DIR=/srv/gitlab-migrator/data/reports
gitlab-migrator migrate all
```

CLI location options override the corresponding environment variables. The
defaults are `data/reports` and `data/repositories`. Relative paths resolve
from the current directory.

## Protect secrets

Never commit `.env`, tokens, runner SSH keys, reports, or repository data.
Revoke a token immediately if it is exposed in a terminal recording, issue,
chat, or commit.
