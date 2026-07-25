# Pipelines

Pipeline history migration is an audit/replay workflow, not a byte-for-byte transfer of GitLab pipeline records.

## Export recent history

```bash
gitlab-migrator export-pipelines --days 30
```

The default archive is written under `output/`. To intentionally start the export again:

```bash
gitlab-migrator export-pipelines --days 30 --reset
```

## Replay archived entries

```bash
gitlab-migrator replay-pipelines
```

Choose another archive or include all records:

```bash
gitlab-migrator replay-pipelines \
  --file /srv/gitlab-migrator/output/pipeline_history.json \
  --all-records
```

Replay creates new destination pipelines. It cannot preserve original pipeline IDs, timestamps, job logs, artifacts, approvals, or historical status. Review which refs and variables may trigger deployment before replaying.

## Cancel active destination work

Preview first (the default):

```bash
gitlab-migrator cancel-pipelines --hours 24
```

Execute only after reviewing the preview:

```bash
gitlab-migrator cancel-pipelines --hours 24 --execute
```

Optional controls include `--project` and `--include-manual`. Cancellation is a destructive operational action, so keep the preview output with the change record.
