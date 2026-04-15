"""File path resolution and display helpers."""

from __future__ import annotations

import platform
import warnings
from pathlib import Path

from soothe.utils import expand_path

_MIN_PATH_SEGMENTS = 2


def _detect_stripped_absolute_path(file_path: str) -> str | None:
    """Detect if a relative path looks like a stripped absolute path.

    Some model/tool chains or the deepagents backend drop the leading "/" from
    absolute paths. This function detects common patterns and returns the
    corrected absolute path.

    Args:
        file_path: The path to check.

    Returns:
        Corrected absolute path if stripped pattern detected, None otherwise.

    Examples:
        >>> _detect_stripped_absolute_path("Users/john/file.txt")
        "/Users/john/file.txt"  # On macOS

        >>> _detect_stripped_absolute_path("home/john/file.txt")
        "/home/john/file.txt"  # On Linux

        >>> _detect_stripped_absolute_path("relative/path.txt")
        None  # Not a stripped absolute path
    """
    if not file_path:
        return None

    path = Path(file_path)

    # Already absolute, no issue
    if path.is_absolute():
        return None

    parts = path.parts
    if not parts:
        return None

    system = platform.system()

    # macOS pattern: Users/username/...
    if system == "Darwin" and parts[0] == "Users" and len(parts) >= _MIN_PATH_SEGMENTS:
        # Verify this looks like a real user path (not just a folder named "Users")
        # Typical pattern: Users/<username>/...
        corrected = Path("/") / file_path
        warnings.warn(
            f"Detected stripped absolute path: '{file_path}' → '{corrected}'. "
            f"The leading '/' was likely dropped. Using corrected absolute path.",
            UserWarning,
            stacklevel=3,
        )
        return str(corrected)

    # Linux pattern: home/username/...
    if system == "Linux" and parts[0] == "home" and len(parts) >= _MIN_PATH_SEGMENTS:
        corrected = Path("/") / file_path
        warnings.warn(
            f"Detected stripped absolute path: '{file_path}' → '{corrected}'. "
            f"The leading '/' was likely dropped. Using corrected absolute path.",
            UserWarning,
            stacklevel=3,
        )
        return str(corrected)

    return None


def _normalize_workspace_relative_input(file_path: str, work_dir: str) -> str:
    """Normalize stripped-absolute inputs into workspace-relative paths.

    Some model/tool chains or deepagents backend may drop the leading "/" from
    absolute paths, producing values like ``Users/name/workspace/project/tests/out.md``.

    Strategy:
    1. Check if this is a stripped absolute path (like Users/john/... or home/john/...)
    2. If workspace prefix matches, convert to workspace-relative
    3. Otherwise return as-is or corrected absolute path
    """
    # Check for stripped absolute path pattern first
    corrected = _detect_stripped_absolute_path(file_path)
    if corrected:
        # If we have a work_dir, check if the corrected path is within it
        if work_dir:
            try:
                work_path = expand_path(work_dir)
                corrected_path = Path(corrected)
                corrected_path.resolve().relative_to(work_path)
                # Path is within workspace, convert to relative
                # Continue to workspace-relative logic below
            except ValueError:
                # Corrected path is outside workspace, return the absolute path
                return corrected
        else:
            # No work_dir, return the corrected absolute path
            return corrected

    # Original workspace-relative logic
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
