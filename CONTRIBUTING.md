# Contributing

Thanks for helping improve GitLab Group Migrator.

## Development setup

Fork and clone the repository, then create an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the offline test suite:

```bash
python -m unittest discover -s tests -v
```

## Pull requests

- Keep changes focused and explain the migration scenario they address.
- Add or update tests for behavior changes.
- Preserve dry-run defaults for destructive administration commands.
- Never commit tokens, `.env` files, SSH keys, repository mirrors, or reports.
- Document new commands and configuration in `README.md`.

By submitting a contribution, you agree that it is licensed under the MIT
License used by this project.
