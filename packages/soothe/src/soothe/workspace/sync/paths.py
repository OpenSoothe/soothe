"""Path validation utilities for workspace sync security.

Prevent path traversal attacks and ensure that server-generated IDs and
user-supplied relative paths cannot escape their intended storage prefixes.
"""

from __future__ import annotations

import posixpath
import re

_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._\-]{1,128}$")

_MAX_PATH_LENGTH = 4096


def validate_path_component(component: str, *, name: str) -> str:
    """Validate a single path component (run_id, checkpoint_id, sha256).

    Rejects empty strings, null bytes, path separators, and characters
    outside the safe set (alphanumeric + hyphens + underscores + dots).

    Args:
        component: The path component to validate.
        name: Human-readable label for error messages (e.g. `"run_id"`).

    Returns:
        The validated component (unchanged if valid).

    Raises:
        ValueError: If the component is empty, contains null bytes,
            path separators, or disallowed characters.
    """
    if not component:
        raise ValueError(f"invalid {name}: empty")
    if "\x00" in component:
        raise ValueError(f"invalid {name}: contains null bytes")
    if ".." in component:
        raise ValueError(f"invalid {name}: contains path traversal sequence '..': {component!r}")
    if len(component) > 128:
        raise ValueError(f"invalid {name}: exceeds 128 characters")
    if not _SAFE_ID_PATTERN.match(component):
        raise ValueError(
            f"invalid {name}: contains path separators or disallowed characters: {component!r}"
        )
    return component


def validate_relative_path(path: str, *, name: str = "path") -> str:
    """Validate a relative path (artifact_path) and reject traversal.

    Rejects empty paths, absolute paths, null bytes, and `..` segments
    that would escape the intended storage prefix after normalization.

    Args:
        path: The relative path to validate.
        name: Human-readable label for error messages.

    Returns:
        The normalized path if valid.

    Raises:
        ValueError: If the path is empty, absolute, contains null bytes,
            or escapes the prefix after normalization.
    """
    if not path:
        raise ValueError(f"invalid {name}: empty")
    if "\x00" in path:
        raise ValueError(f"invalid {name}: contains null bytes")
    if len(path) > _MAX_PATH_LENGTH:
        raise ValueError(f"invalid {name}: exceeds {_MAX_PATH_LENGTH} characters")
    if path.startswith("/"):
        raise ValueError(f"invalid {name}: absolute paths not allowed: {path!r}")

    normalized = posixpath.normpath(path)

    if normalized.startswith("..") or normalized == "..":
        raise ValueError(f"path traversal in {name}: {path!r}")

    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise ValueError(f"path traversal in {name}: {path!r}")

    return normalized
