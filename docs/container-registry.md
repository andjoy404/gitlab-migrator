# Container registry

Registry migration uses Skopeo to copy images without a local Docker daemon. Configure both registry endpoints and credentials in `.env` first.

## Copy recent images

```bash
gitlab-migrator migrate-registry --days 30
```

Reset its progress only when you intentionally want to reconsider completed records:

```bash
gitlab-migrator migrate-registry --days 30 --reset
```

Verify authentication and available destination storage before a large run. Registry manifests may reference substantial shared blob data.

## Cleanup policy

Preview the policy changes:

```bash
gitlab-migrator set-registry-retention --days 7
```

Apply them after review:

```bash
gitlab-migrator set-registry-retention --days 7 --execute
```

Use `--project` to constrain the operation and `--reset` to rebuild its progress state.

## Purge old tags

Preview is the default:

```bash
gitlab-migrator purge-registry-images --days 30
```

Delete after validating the candidate list:

```bash
gitlab-migrator purge-registry-images --days 30 --execute
```

Additional options include `--project`, `--include-latest`, `--all`, and `--reset`. Purging is destructive; preserve the preview, confirm retention/legal requirements, and ensure required images exist elsewhere before execution.

Tag age metadata varies by GitLab/registry version. Treat calculated age as selection input, not a substitute for a recovery plan.
