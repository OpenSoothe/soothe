"""Path helpers for community plugins (mirrors ``soothe.utils.path.expand_path``)."""

from __future__ import annotations

import os
from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand and resolve a filesystem path."""
    path_str = str(path)
    expanded = os.path.expandvars(path_str)
    expanded_path = Path(expanded).expanduser()
    return expanded_path.resolve()


__all__ = ["expand_path"]
