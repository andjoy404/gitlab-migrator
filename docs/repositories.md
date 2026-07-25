# Repositories and merge requests

## Migrate

```bash
gitlab-migrator migrate
```

The command prints the source and destination and waits for `yes`. Any other answer cancels both repository and merge-request phases.

For reviewed automation, skip only that confirmation:

```bash
gitlab-migrator migrate --yes
```

Repository mirrors run first. Recent merge requests are then recreated for the configured time window:

```bash
gitlab-migrator migrate --days 90
```

## Limit the scope

Use one `.env` filter at a time:

```dotenv
MIGRATE_PROJECT=source-group/team/project
MIGRATE_GROUP=
```

or:

```dotenv
MIGRATE_PROJECT=
MIGRATE_GROUP=source-group/team
```

Increase `MIGRATE_WORKERS` cautiously; Git operations, GitLab rate limits, and destination capacity usually determine a safe value.

## Merge requests only

```bash
gitlab-migrator migrate-merge-requests --days 30
```

Reset its checkpoint when intentionally rebuilding the migration result:

```bash
gitlab-migrator migrate-merge-requests --days 30 --reset
```

Merge requests are recreated as historical migration records/new destination objects; GitLab does not provide a perfect cross-instance transfer of every internal event and identifier. Review results before relying on them as an audit archive.

## Supporting metadata

```bash
gitlab-migrator migrate-group-variables
gitlab-migrator migrate-variables
gitlab-migrator migrate-hooks
gitlab-migrator migrate-protection
```

Treat output checkpoints as operational state. Back them up before using reset options.
