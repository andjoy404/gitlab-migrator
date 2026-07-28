# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.7.0] - 2026-07-28

### Added

- Add comma-separated `MIGRATE_GROUPS` for selecting multiple source group
  subtrees in repository and merge-request migration.

### Fixed

- Refresh repository history when an explicit project or group filter is
  selected instead of skipping repositories with completion checkpoints.
- Replace prior repository checkpoint records during a scoped refresh instead
  of appending duplicate completion entries.

## [0.6.1] - 2026-07-28

### Fixed

- Accept full source, source-relative, and destination-root paths in
  `MIGRATE_PROJECT` and `MIGRATE_GROUP`.

## [0.6.0] - 2026-07-28

### Added

- Add comma-separated `EXCLUDE_PROJECTS` and recursive `EXCLUDE_GROUPS`
  filters for repository and merge-request migration.

## [0.5.1] - 2026-07-27

### Added

- Add a colorful Rich banner to interactive CLI output, including interactive
  `--version`, while keeping redirected version output machine-readable.

### Changed

- Refresh the quick-start animation with the CLI banner and make its renderer
  portable across macOS and Linux system fonts.

## [0.5.0] - 2026-07-27

### Added

- Add grouped CLI commands for migrations, runners, pipelines, and container
  registry operations while retaining the pre-0.5 command names as aliases.

### Fixed

- Keep migration data created with the pre-0.4 `output`, `workspace`, and
  `keys` paths ignored during upgrades.

## [0.4.0] - 2026-07-27

### Added

- Add resumable repository migration checkpoints and `migrate --reset` for an
  intentional full repository replay.

### Changed

- Store native and Docker runtime data in the shared root-level
  `data/repositories`, `data/reports`, and `data/keys` directories.
- Use the same root-level `.env` file for native and Docker execution.

### Fixed

- Initialize Docker bind-mounted data directories with the configured host
  user and group ownership before starting the migrator container.
- Replace the corrupted repository synchronization symbol with a portable
  ASCII status marker.
- Handle Ctrl+C in the command launcher without printing parent and child
  Python tracebacks.

## [0.3.0] - 2026-07-26

### Added

- Add `migrate --yes` for reviewed, non-interactive repository migrations.
- Add a non-root Docker image with Git, Git LFS, OpenSSH, and Skopeo.
- Add persistent and detached Docker Compose execution workflows.
- Add GHCR multi-platform image publishing for version tags.
- Add focused installation, configuration, Docker, repository, runner,
  pipeline, and container-registry guides.

### Changed

- Restructure the README as a concise project landing page.

## [0.2.0] - 2026-07-25

### Changed

- Rename the Python distribution from `gitlab-group-migrator` to
  `gitlab-migrator`, matching the repository and executable names.



## [0.1.5] - 2026-07-25

### Fixed

- Replace corrupted README table characters with portable ASCII text.



## [0.1.4] - 2026-07-25

### Removed

- Obsolete rsync synchronization helpers and their documentation.



## [0.1.3] - 2026-07-25

### Fixed

- Stop the combined migration when repository migration is cancelled.



## [0.1.2] - 2026-07-25

### Fixed

- Load `.env` from the current working directory for pipx installations.
- Report the configuration file path when required variables are missing.



## [0.1.1] - 2026-07-25

### Changed

- Display CLI commands on separate lines in top-level help.
- Generalize local/remote synchronization tools.
- Package command modules under `src/gitlab_migrator/commands`.



### Added

- Installable `gitlab-migrator` command.
- GitHub installation support through HTTPS and SSH.
- Configurable environment, output, and workspace paths.
- Offline CLI tests and GitHub Actions validation.
