"""Make the local ``src`` package importable for direct script execution."""

import sys
from pathlib import Path


def configure_import_path():
    source_root = Path(__file__).resolve().parents[2]
    source_root_text = str(source_root)

    if source_root_text not in sys.path:
        sys.path.insert(0, source_root_text)
