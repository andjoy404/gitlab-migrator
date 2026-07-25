#!/usr/bin/env python3
"""Compatibility launcher for running the CLI from a source checkout."""

from pathlib import Path
import sys


source_root = Path(__file__).resolve().parent / "src"
if str(source_root) not in sys.path:
    sys.path.insert(0, str(source_root))

from gitlab_migrator.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
