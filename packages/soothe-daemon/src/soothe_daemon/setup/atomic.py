"""Atomic file writes for setup."""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* via a temp file + replace.

    Args:
        path: Destination file path.
        content: Text to write.
        encoding: Text encoding (default UTF-8).
    """
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
