"""Load workspace CLAUDE.md and AGENTS.md for user-message CONTEXT_INFO (RFC-214)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_INSTRUCTION_MAX_LINES = 500
_PROJECT_INSTRUCTION_FILENAMES = ("CLAUDE.md", "AGENTS.md")


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
    """Load CLAUDE.md and AGENTS.md from the workspace for CONTEXT_INFO injection.

    Reads the first ``max_lines`` of each file when present. AGENTS.md is resolved from
    the workspace root, then ``.soothe/AGENTS.md`` when the root file is missing.

    Args:
        workspace: Thread workspace directory.
        max_lines: Per-file line cap (default 500).

    Returns:
        XML fragment for embedding under ``<CONTEXT_INFO>``, or ``None`` when no files
        were found or ``workspace`` is unset.
    """
    if not workspace:
        return None
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        return None

    blocks: list[str] = []

    claude_path = root / "CLAUDE.md"
    if claude_path.is_file():
        body, truncated = _read_file_head_lines(claude_path, max_lines=max_lines)
        if body.strip():
            blocks.append(
                _format_instruction_block("CLAUDE.md", claude_path, body, truncated=truncated)
            )

    agents_path: Path | None = None
    for candidate in _agents_md_candidates(root):
        if candidate.is_file():
            agents_path = candidate
            break
    if agents_path is not None:
        body, truncated = _read_file_head_lines(agents_path, max_lines=max_lines)
        if body.strip():
            rel = agents_path.relative_to(root).as_posix()
            blocks.append(_format_instruction_block(rel, agents_path, body, truncated=truncated))

    if not blocks:
        return None

    return "<project_instructions>\n" + "\n".join(blocks) + "\n</project_instructions>"


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
