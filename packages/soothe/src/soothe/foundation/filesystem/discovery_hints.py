"""Filesystem discovery guidance for tool descriptions and error recovery."""

from __future__ import annotations

GLOB_DISCOVERY_FALLBACK_HINT = (
    "If glob fails, times out, or returns empty: narrow the path (e.g. packages/foo/), "
    "use grep(pattern=..., glob='*.ts') for content-based discovery, or ls on known "
    "directories before read_file on specific targets. Avoid repeating broad ** globs."
)

GLOB_TOOL_DESCRIPTION = f"""Find files matching a glob pattern.

Supports standard glob patterns: `*` (any characters), `**` (any directories), `?` (single character).
Returns a list of file paths that match the pattern (relative to workspace root when virtual mode is on).

Prefer narrow patterns scoped to a directory (e.g. `packages/foo/**/*.test.ts`) over repo-wide `**` scans.
Set `path` to a subdirectory when the search target is known.

Examples:
- `**/*.py` - Find all Python files (may be slow on large repos)
- `packages/api/**/*.test.ts` - TypeScript tests under one package
- `*.txt` - Text files in the search root

{GLOB_DISCOVERY_FALLBACK_HINT}"""


def format_glob_timeout_error(timeout_seconds: float) -> str:
    """Build a glob timeout error with discovery fallback guidance."""
    return (
        f"Error: glob timed out after {timeout_seconds:.0f}s. "
        "Try a more specific pattern, set path to a narrower directory, "
        f"or switch strategy: {GLOB_DISCOVERY_FALLBACK_HINT}"
    )


__all__ = [
    "GLOB_DISCOVERY_FALLBACK_HINT",
    "GLOB_TOOL_DESCRIPTION",
    "format_glob_timeout_error",
]
