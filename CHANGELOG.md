# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
