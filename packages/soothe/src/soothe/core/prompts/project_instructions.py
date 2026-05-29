"""Load workspace AGENTS.md (preferred) or CLAUDE.md for system-message WORKSPACE_INSTRUCTIONS (RFC-214)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_INSTRUCTION_MAX_LINES = 500


def _read_file_head_lines(path: Path, *, max_lines: int) -> tuple[str, bool]:
    """Read up to ``max_lines`` from a text file.

    Args:
        path: File to read.
        max_lines: Maximum number of lines to include.

    Returns:
        Tuple of (content, truncated) where truncated is True when more lines exist.
    """
    lines: list[str] = []
    truncated = False
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line_no > max_lines:
                    truncated = True
                    break
                lines.append(line.rstrip("\n\r"))
    except OSError as exc:
        logger.debug("Could not read project instruction file %s: %s", path, exc)
        return "", False
    return "\n".join(lines), truncated


def _agents_md_candidates(workspace: Path) -> list[Path]:
    """Return AGENTS.md paths to try, in precedence order."""
    return [
        workspace / "AGENTS.md",
        workspace / ".soothe" / "AGENTS.md",
    ]


def load_workspace_project_instructions(
    workspace: str | Path | None,
    *,
    max_lines: int = DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
) -> str | None:
    """Load AGENTS.md (preferred) or CLAUDE.md from the workspace for system message injection.

    Priority order:
    1. AGENTS.md in workspace root
    2. .soothe/AGENTS.md
    3. CLAUDE.md in workspace root (fallback when no AGENTS.md found)

    Only ONE file is loaded - AGENTS.md takes priority, CLAUDE.md is fallback.

    Args:
        workspace: Thread workspace directory.
        max_lines: Per-file line cap (default 500).

    Returns:
        XML fragment ``<WORKSPACE_INSTRUCTIONS>`` for system message semi-static tier,
        or ``None`` when no files were found or ``workspace`` is unset.
    """
    if not workspace:
        return None
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        return None

    # Try AGENTS.md first (preferred)
    for candidate in _agents_md_candidates(root):
        if candidate.is_file():
            body, truncated = _read_file_head_lines(candidate, max_lines=max_lines)
            if body.strip():
                rel = candidate.relative_to(root).as_posix()
                block = _format_instruction_block(rel, candidate, body, truncated=truncated)
                return "<WORKSPACE_INSTRUCTIONS>\n" + block + "\n</WORKSPACE_INSTRUCTIONS>"

    # Fallback to CLAUDE.md when no AGENTS.md found
    claude_path = root / "CLAUDE.md"
    if claude_path.is_file():
        body, truncated = _read_file_head_lines(claude_path, max_lines=max_lines)
        if body.strip():
            block = _format_instruction_block("CLAUDE.md", claude_path, body, truncated=truncated)
            return "<WORKSPACE_INSTRUCTIONS>\n" + block + "\n</WORKSPACE_INSTRUCTIONS>"

    return None


def _format_instruction_block(
    label: str,
    path: Path,
    body: str,
    *,
    truncated: bool,
) -> str:
    """Format one instruction file as a CDATA-wrapped XML element."""
    trunc_attr = "true" if truncated else "false"
    return (
        f'<file name="{label}" path="{path}" truncated="{trunc_attr}">\n'
        f"<![CDATA[\n{body}\n]]>\n"
        f"</file>"
    )


__all__ = [
    "DEFAULT_PROJECT_INSTRUCTION_MAX_LINES",
    "load_workspace_project_instructions",
]
