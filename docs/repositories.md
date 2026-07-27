# Repositories and merge requests

## Migrate

```bash
gitlab-migrator migrate all
```

The command prints the source and destination and waits for `yes`. Any other answer cancels both repository and merge-request phases.

For reviewed automation, skip only that confirmation:

```bash
gitlab-migrator migrate all --yes
```

Repository mirrors run first. Every successful repository is immediately saved to
`data/reports/repository_migration_results.json`. If the command is stopped, run the
same command again; completed repositories are skipped and unfinished ones retry.
Recent merge requests are then recreated for the configured time window:

```bash
gitlab-migrator migrate all --days 90
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

Exclude individual projects, entire group subtrees, or both:

```dotenv
EXCLUDE_PROJECTS=source-group/legacy/app,source-group/archive/test
EXCLUDE_GROUPS=source-group/archive,source-group/deprecated
```

Values must be full source paths below `SOURCE_GROUP` and may be separated by
commas and optional whitespace. An excluded group includes all nested
subgroups and projects. Matching respects path boundaries, so excluding
`source-group/archive` does not exclude `source-group/archive-new`.
Exclusions take precedence over `MIGRATE_PROJECT` and `MIGRATE_GROUP`.

Increase `MIGRATE_WORKERS` cautiously; Git operations, GitLab rate limits, and destination capacity usually determine a safe value.

## Merge requests only

```bash
gitlab-migrator migrate mr --days 30
```

Restart all repository mirrors intentionally:

```bash
gitlab-migrator migrate all --reset
```

This resets repository checkpoints only. To reset recent merge requests too:

```bash
gitlab-migrator migrate all --reset --reset-mr
```

Reset the merge-request-only checkpoint when intentionally rebuilding its result:

```bash
gitlab-migrator migrate mr --days 30 --reset
```

Merge requests are recreated as historical migration records/new destination objects; GitLab does not provide a perfect cross-instance transfer of every internal event and identifier. Review results before relying on them as an audit archive.

## Supporting metadata

```bash
gitlab-migrator migrate vars group
gitlab-migrator migrate vars
gitlab-migrator migrate hooks
gitlab-migrator migrate branch protection
```

Treat report checkpoints as operational state. Back them up before using reset
options.
