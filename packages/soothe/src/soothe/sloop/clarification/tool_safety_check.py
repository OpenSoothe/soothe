"""Bypass-immune safety checks for tool-approval pipeline (RFC-622 §9b).

Adapts Claude Code's ``filesystem.ts`` dangerous-path detection. The
dangerous file and directory lists are built-in constants — not configurable
per-rule — because they represent bypass-immune security boundaries (same
principle as Claude Code's ``DANGEROUS_FILES`` / ``DANGEROUS_DIRECTORIES``
which cannot be overridden by allow rules).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Built-in safety constants (bypass-immune)
# ---------------------------------------------------------------------------

DANGEROUS_FILES: frozenset[str] = frozenset(
    {
        ".gitconfig",
        ".gitmodules",
        ".bashrc",
        ".bash_profile",
        ".zshrc",
        ".zprofile",
        ".profile",
        ".ripgreprc",
        ".mcp.json",
        ".claude.json",
    }
)
"""Files dangerous to auto-approve for editing (code execution / data exfiltration)."""

DANGEROUS_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".vscode",
        ".idea",
        ".claude",
    }
)
"""Directories dangerous to auto-approve for editing (sensitive config / executable files)."""

DESTRUCTIVE_COMMAND_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -r",
    "rm -f",
    "sudo ",
    "chmod 777",
    "chmod -R",
    "git push --force",
    "git push -f",
    "dd if=",
    "mkfs",
    "shred",
)
"""Shell command substrings that indicate a destructive action."""


@dataclass(frozen=True)
class SafetyResult:
    """Result of a safety check."""

    safe: bool
    reason: str = ""


def check_path_safety(path: str) -> SafetyResult:
    """Check if a file path is dangerous to auto-approve.

    Returns unsafe for:

    - Paths inside ``DANGEROUS_DIRECTORIES`` (``.git/``, ``.vscode/``, etc.)
    - Paths ending in ``DANGEROUS_FILES`` (``.bashrc``, ``.gitconfig``, etc.)
    - Path traversal (``..`` segments)
    - UNC paths (``//server`` or ``\\\\server``)
    - Trailing dots/spaces (Windows canonicalization bypass)

    Adapted from Claude Code's ``checkPathSafetyForAutoEdit`` /
    ``isDangerousFilePathToAutoEdit``.
    """
    if not path:
        return SafetyResult(safe=True)

    # UNC paths (defense-in-depth)
    if path.startswith("\\\\") or path.startswith("//"):
        return SafetyResult(
            safe=False,
            reason=f"UNC path blocked: {path}",
        )

    # Path traversal detection
    normalized = os.path.normpath(path)
    if ".." in normalized.split(os.sep):
        return SafetyResult(
            safe=False,
            reason=f"path traversal blocked: {path}",
        )

    # Trailing dots/spaces (Windows canonicalization bypass)
    if path != path.rstrip(". "):
        return SafetyResult(
            safe=False,
            reason=f"suspicious trailing chars in path: {path}",
        )

    # Normalize for case-insensitive comparison
    path_lower = normalized.lower()
    segments = path_lower.replace("\\", "/").split("/")
    filename = segments[-1] if segments else ""

    # Check dangerous directories
    for segment in segments:
        if segment in DANGEROUS_DIRECTORIES:
            return SafetyResult(
                safe=False,
                reason=f"dangerous directory blocked: {segment} in {path}",
            )

    # Check dangerous files
    if filename in DANGEROUS_FILES:
        return SafetyResult(
            safe=False,
            reason=f"dangerous file blocked: {filename}",
        )

    return SafetyResult(safe=True)


def check_command_safety(command: str) -> SafetyResult:
    """Check if a shell command is destructive.

    Returns unsafe for ``DESTRUCTIVE_COMMAND_PATTERNS`` substring matches.
    Matching is case-insensitive.
    """
    if not command:
        return SafetyResult(safe=True)

    cmd_lower = command.lower().strip()
    for pattern in DESTRUCTIVE_COMMAND_PATTERNS:
        if pattern in cmd_lower:
            return SafetyResult(
                safe=False,
                reason=f"destructive command pattern blocked: '{pattern}' in {command}",
            )

    return SafetyResult(safe=True)


__all__ = [
    "DANGEROUS_DIRECTORIES",
    "DANGEROUS_FILES",
    "DESTRUCTIVE_COMMAND_PATTERNS",
    "SafetyResult",
    "check_command_safety",
    "check_path_safety",
]
