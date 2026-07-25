# Installation

## Requirements

- Python 3.9 or newer and `pipx`
- Git; Git LFS when migrating LFS objects
- `skopeo` only for container-registry migration
- Network access to both GitLab instances

## Install with pipx

Public repository over HTTPS:

```bash
pipx install git+https://github.com/andjoy404/gitlab-migrator.git
```

Private repository or SSH preference:

```bash
pipx install git+ssh://git@github.com/andjoy404/gitlab-migrator.git
```

Confirm the installation:

```bash
gitlab-migrator --version
gitlab-migrator --help
```

## Upgrade

The package and command now share the same name:

```bash
pipx upgrade gitlab-migrator
```

For a Git installation, force a fresh install if pipx reports no newer published version:

```bash
pipx install --force git+https://github.com/andjoy404/gitlab-migrator.git
```

## Development install

```bash
git clone git@github.com:andjoy404/gitlab-migrator.git
cd gitlab-migrator
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

See [configuration](configuration.md) next, or use the [Docker guide](docker.md).
