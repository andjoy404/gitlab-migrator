# Runners

Runner migration is deliberately staged: export, deploy while paused, verify, then resume.

## Export the plan

```bash
gitlab-migrator export-runners
```

The default plan is `output/runners.json`. Use `RUNNER_GROUP` to limit its scope when necessary.

## Prepare SSH access

Put private keys in `keys/` for a native installation or `docker/data/keys/` for Docker. Restrict permissions:

```bash
chmod 600 keys/*
```

Do not commit keys. The Docker deployment mounts them read-only.

## Deploy

```bash
gitlab-migrator deploy-runners \
  --plan output/runners.json \
  --keys-dir keys \
  --port 22
```

Deployment may request manual SSH choices for individual hosts. Run it in an attached terminal. With Docker:

```bash
docker exec -it gitlab-migrator \
  gitlab-migrator deploy-runners --keys-dir /data/keys
```

Runners remain paused so you can verify executor configuration, tags, protected status, host services, and connectivity.

## Resume verified runners

```bash
gitlab-migrator resume-runners
```

Only resume after checking the deployment report. Failed hosts can be corrected and the deployment command rerun from the saved plan.
