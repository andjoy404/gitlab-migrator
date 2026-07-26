# Docker

The image includes Git, Git LFS, OpenSSH, and Skopeo. It runs as an unprivileged user and stores mutable data under `/data`.

## Prepare

```bash
cp .env.example .env
```

Edit the root-level `.env`, then make it private:

```bash
chmod 600 .env
```

This is the same configuration file used by native `gitlab-migrator`
commands. Pass it to Compose with `--env-file .env` so it is also used for
Compose interpolation such as the image name and host user IDs.

Runner SSH keys belong in the root-level `data/keys` directory. Compose mounts
the entire root-level `data` directory at `/data`, so native CLI and Docker
commands share repositories, reports, and keys without duplicate storage.
Compose creates the runtime directories and a short-lived initialization
service assigns them to USER_ID and GROUP_ID before the migrator starts.

## Use the GHCR image

```bash
docker compose --env-file .env -f docker/docker-compose.yml pull
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

The Compose service is a persistent toolbox. It stays running after a migration finishes:

```bash
docker exec -it gitlab-migrator gitlab-migrator migrate
```

## Build locally

Build through Compose:

```bash
docker compose --env-file .env -f docker/docker-compose.yml build
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

Or build directly:

```bash
docker build -f docker/Dockerfile -t gitlab-migrator:local .
```

To make Compose use that direct-build tag, set this in the root `.env`:

```dotenv
GITLAB_MIGRATOR_IMAGE=gitlab-migrator:local
```

## Attached and detached execution

Interactive repository migration:

```bash
docker exec -it gitlab-migrator gitlab-migrator migrate
```

Detached migration without the initial confirmation (recommended for long runs):

```bash
docker compose --env-file .env -f docker/docker-compose.yml run -d \
  --name gitlab-migrator-job \
  gitlab-migrator migrate --yes

docker logs -f gitlab-migrator-job
```

You may close the log viewer with Ctrl+C without stopping the detached job.
Reattach later with the same `docker logs -f` command. Successful repositories
are checkpointed in the mounted reports directory, so a stopped job can be rerun
without starting over.

Inspect the exit status and remove the completed job:

```bash
docker inspect gitlab-migrator-job --format '{{.State.ExitCode}}'
docker rm gitlab-migrator-job
```

Runner deployment can ask per-host SSH questions, so keep it attached:

```bash
docker exec -it gitlab-migrator \
  gitlab-migrator deploy-runners --keys-dir /data/keys
```

## Persistent data

| Host directory | Container path | Contents |
| --- | --- | --- |
| `data/reports` | `/data/reports` | Reports, archives, checkpoints |
| `data/repositories` | `/data/repositories` | Temporary Git mirrors |
| `data/keys` | `/data/keys` | Runner SSH keys |

These are provided through one Compose bind mount: `../data:/data`. If files
are owned by the wrong host user, set `USER_ID` and `GROUP_ID` in `.env`, then
recreate the services.

## Stop

```bash
docker compose --env-file .env -f docker/docker-compose.yml down
```

This leaves the bind-mounted `data` directory on the host.
