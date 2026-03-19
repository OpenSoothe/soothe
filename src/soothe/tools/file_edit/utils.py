"""File path resolution and display helpers."""

from __future__ import annotations

from pathlib import Path

from soothe.utils import expand_path


def _normalize_workspace_relative_input(file_path: str, work_dir: str) -> str:
    """Normalize stripped-absolute inputs into workspace-relative paths.

    Some model/tool chains may drop the leading "/" from absolute paths, producing
    values like ``Users/name/workspace/project/tests/out.md``. If this prefix matches
    the current ``work_dir``, convert it back to a path relative to ``work_dir`` so
    writes stay inside the expected workspace tree.
    """
    if not work_dir:
        return file_path

    path = Path(file_path)
    if path.is_absolute():
        return file_path

    parts = path.parts
    if not parts:
        return file_path

    work_parts = expand_path(work_dir).parts
    stripped_work_parts = work_parts[1:] if work_parts and work_parts[0] == "/" else work_parts
    if (
        stripped_work_parts
        and len(parts) > len(stripped_work_parts)
        and tuple(parts[: len(stripped_work_parts)]) == stripped_work_parts
    ):
        return str(Path(*parts[len(stripped_work_parts) :]))
    return file_path


def _display_path(path: Path, work_dir: str) -> str:
    """Render a path relative to work_dir when possible."""
    if work_dir:
        try:
            return str(path.relative_to(expand_path(work_dir)))
        except ValueError:
            pass
    return str(path)
