# Docker

The image includes Git, Git LFS, OpenSSH, and Skopeo. It runs as an unprivileged user and stores mutable data under `/data`.

## Prepare

```bash
cp docker/.env.example docker/.env
```

Edit `docker/.env`, then make it private:

```bash
chmod 600 docker/.env
```

Runner SSH keys belong in docker/data/keys; the container mounts that directory read-only.
Compose creates the runtime directories and a short-lived initialization service
assigns them to USER_ID and GROUP_ID before the migrator starts.

## Use the GHCR image

```bash
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d
```

The Compose service is a persistent toolbox. It stays running after a migration finishes:

```bash
docker exec -it gitlab-migrator gitlab-migrator migrate
```

## Build locally

Build through Compose:

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

Or build directly:

```bash
docker build -f docker/Dockerfile -t gitlab-migrator:local .
```

To make Compose use that direct-build tag, set this in `docker/.env`:

```dotenv
GITLAB_MIGRATOR_IMAGE=gitlab-migrator:local
```

## Attached and detached execution

Interactive repository migration:

```bash
docker exec -it gitlab-migrator gitlab-migrator migrate
```

Detached migration without the initial confirmation:

```bash
docker compose -f docker/docker-compose.yml run -d \
  --name gitlab-migrator-job \
  gitlab-migrator migrate --yes

docker logs -f gitlab-migrator-job
```

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
| `docker/data/output` | `/data/output` | Reports, archives, checkpoints |
| `docker/data/workspace` | `/data/workspace` | Temporary Git mirrors |
| `docker/data/keys` | `/data/keys` | Read-only runner SSH keys |

If files are owned by the wrong host user, set `USER_ID` and `GROUP_ID` in `docker/.env`, then rebuild.

## Stop

```bash
docker compose -f docker/docker-compose.yml down
```

This leaves the bind-mounted output and workspace data on the host.
