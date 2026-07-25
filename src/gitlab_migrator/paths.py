"""Configurable paths for generated migration output."""
import os

from pathlib import Path




def output_path(filename):
    """Return a path under the output directory, creating it when needed."""

    output_dir = Path(os.getenv("GITLAB_MIGRATOR_OUTPUT_DIR", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename

