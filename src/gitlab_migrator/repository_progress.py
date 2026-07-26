"""Persistent checkpoints for repository migration."""

import json
from pathlib import Path


FORMAT_VERSION = 1


def load_repository_progress(path, context, reset=False):
    """Load completed repository records and validate their migration context."""

    path = Path(path)
    if reset:
        path.unlink(missing_ok=True)
        return []
    if not path.exists():
        return []

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Cannot read repository checkpoint {path}: {error}"
        ) from error

    if value.get("format_version") != FORMAT_VERSION:
        raise RuntimeError(
            f"Unsupported repository checkpoint format in {path}; "
            "use migrate --reset to start again."
        )
    if value.get("context") != context:
        raise RuntimeError(
            f"Repository checkpoint {path} belongs to a different source or "
            "destination; use migrate --reset to start again."
        )

    results = value.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"Invalid repository checkpoint results in {path}.")
    return results


def save_repository_progress(path, context, results):
    """Atomically replace a repository checkpoint file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = {
        "format_version": FORMAT_VERSION,
        "context": context,
        "results": results,
    }
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
