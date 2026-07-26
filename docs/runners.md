# Runners

Runner migration is deliberately staged: export, deploy while paused, verify, then resume.

## Export the plan

```bash
gitlab-migrator export-runners
```

The default plan is `data/reports/runners.json`. Use `RUNNER_GROUP` to limit
its scope when necessary.

## Prepare SSH access

Put private keys in `data/keys/`. Native and Docker commands use the same
root-level directory. Restrict permissions:

```bash
chmod 600 data/keys/*
```

Do not commit keys. The shared `data` directory is writable by the container,
so keep the private-key files read-only for the configured host user.

## Deploy

```bash
gitlab-migrator deploy-runners \
  --plan data/reports/runners.json \
  --keys-dir data/keys \
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
