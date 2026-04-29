"""Filesystem path normalization for workspace backends (IG-300).

Shared helpers for expanding ``~``, resolving paths, and validating containment
against the effective workspace root.
"""

from __future__ import annotations

from pathlib import Path

from soothe_sdk.utils import INVALID_WORKSPACE_DIRS


def strict_workspace_path(raw: str, *, workspace: Path) -> Path:
    """Resolve *raw* to an absolute path and ensure it stays under *workspace*.

    Expands user home and resolves ``.`` / ``..`` components. Used by unit tests
    and policy-adjacent validation where a concrete ``Path`` is required.

    Args:
        raw: User- or model-supplied path string.
        workspace: Absolute workspace root.

    Returns:
        Resolved absolute path within *workspace*.

    Raises:
        ValueError: If path is empty, escapes the workspace, or resolves to a
            forbidden system directory (see ``INVALID_WORKSPACE_DIRS``).
    """
    text = raw.strip()
    if not text:
        msg = "Path must be non-empty"
        raise ValueError(msg)

    root = workspace.expanduser().resolve()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    resolved_str = str(candidate)
    if resolved_str in INVALID_WORKSPACE_DIRS:
        msg = f"Invalid path: {resolved_str} is a disallowed system directory"
        raise ValueError(msg)

    try:
        candidate.relative_to(root)
    except ValueError as e:
        msg = f"Path {raw!r} resolves outside workspace {root}"
        raise ValueError(msg) from e

    return candidate
