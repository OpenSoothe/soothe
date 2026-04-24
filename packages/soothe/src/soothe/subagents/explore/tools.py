"""Explore subagent read-only filesystem tools (RFC-613).

Lightweight tools using Python standard library for file operations.
These are self-contained and don't require deepagents backend setup.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def glob(pattern: str) -> list[str]:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "src/**/auth*").

    Returns:
        List of matching file paths (relative to workspace).
    """
    from glob import glob as _glob

    matches = _glob(pattern, recursive=True)
    return sorted([str(Path(m).relative_to(os.getcwd())) for m in matches])


@tool
def grep(pattern: str, path: str | None = None) -> list[dict[str, Any]]:
    """Search for a text pattern in files.

    Args:
        pattern: Text pattern to search for (literal, not regex).
        path: Directory or file to search in. Defaults to current directory.

    Returns:
        List of matches with path, line number, and line content.
    """
    try:
        cmd = ["grep", "-r", "-n", "--fixed-strings", pattern]
        if path:
            cmd.append(path)
        else:
            cmd.append(".")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        matches = []
        for line in result.stdout.splitlines()[:50]:  # Limit results
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append(
                    {
                        "path": parts[0],
                        "line_number": int(parts[1]),
                        "line": parts[2][:100],
                    }
                )
        return matches
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


@tool
def ls(path: str) -> list[str]:
    """List directory contents.

    Args:
        path: Directory path to list.

    Returns:
        List of file and directory names.
    """
    try:
        entries = sorted(os.listdir(path))
        return [str(Path(path) / e) for e in entries]
    except FileNotFoundError:
        return []


@tool
def read_file(path: str, offset: int = 0, limit: int = 50) -> str:
    """Read file content.

    Args:
        path: File path to read.
        offset: Starting line number (0-indexed).
        limit: Maximum number of lines to read.

    Returns:
        File content as string.
    """
    try:
        with open(path) as f:
            lines = f.readlines()
            return "".join(lines[offset : offset + limit])
    except FileNotFoundError:
        return "File not found"


@tool
def file_info(path: str) -> dict[str, Any]:
    """Get file metadata.

    Args:
        path: File path.

    Returns:
        Dict with size, mtime, permissions.
    """
    try:
        stat = os.stat(path)
        return {
            "path": path,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "permissions": oct(stat.st_mode)[-3:],
        }
    except FileNotFoundError:
        return {"path": path, "error": "File not found"}


def get_explore_tools() -> list[Any]:
    """Get all explore subagent tools.

    Returns:
        List of langchain tool instances.
    """
    return [glob, grep, ls, read_file, file_info]
