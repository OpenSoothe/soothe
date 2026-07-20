"""Load workspace AGENTS.md (preferred) or CLAUDE.md for system-message AGENT_INSTRUCTIONS (RFC-214).

Progressive disclosure: small files inline verbatim; larger files emit a
paragraph-clean headline plus a ``<NOTE>`` hint that points the LLM at
``read_file`` for the full body. Read+format results are cached per
``(path, mtime)`` so repeated prompt builds within a session don't re-hit disk.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_INSTRUCTION_MAX_LINES = 500
# Char cap for inlined headline. Files at or below this size are emitted
# verbatim; larger files emit a paragraph-clean prefix plus a read_file hint.
# 25K chars covers typical AGENTS.md / CLAUDE.md (this project's own CLAUDE.md
# is ~25KB / 584 lines) so the model receives the full project instructions
# in the cache-stable system prelude rather than a partial headline.
PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS = 25000
# Paragraph boundary used to back off the headline cut so the model never
# sees mid-sentence truncation. Falls back to a hard cut if no boundary
# exists within the budget.
PROJECT_INSTRUCTION_HEADLINE_PARAGRAPH_BOUNDARY = "\n\n"


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


def _headline_excerpt(body: str, max_chars: int) -> tuple[str, bool]:
    """Return ``(headline, was_truncated)``.

    When ``body`` exceeds ``max_chars``, cut on the last paragraph boundary
    within budget. If no paragraph boundary fits, hard-cut at ``max_chars`` —
    bounded token cost beats a clean cut.
    """
    if len(body) <= max_chars:
        return body, False
    cut = body.rfind(PROJECT_INSTRUCTION_HEADLINE_PARAGRAPH_BOUNDARY, 0, max_chars)
    if cut <= 0:
        cut = max_chars
    return body[:cut].rstrip(), True


def _agents_md_candidates(workspace: Path) -> list[Path]:
    """Return AGENTS.md paths to try, in precedence order."""
    return [
        workspace / "AGENTS.md",
        workspace / ".soothe" / "AGENTS.md",
    ]


def load_agent_instructions(
    workspace: str | Path | None,
    *,
    max_lines: int = DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    headline_max_chars: int = PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
) -> str | None:
    """Load AGENTS.md (preferred) or CLAUDE.md from the workspace.

    Priority order:
    1. AGENTS.md in workspace root
    2. .soothe/AGENTS.md
    3. CLAUDE.md in workspace root (fallback when no AGENTS.md found)

    Only ONE file is loaded. Files under ``headline_max_chars`` inline
    verbatim; larger files emit a partial headline plus a ``<NOTE>`` directing
    the LLM to ``read_file`` for the full body (progressive disclosure).

    Args:
        workspace: Thread workspace directory.
        max_lines: Per-file line cap (default 500).
        headline_max_chars: Inline char cap (default 25000); above this the
            full body is suppressed in favor of a read_file hint.

    Returns:
        XML fragment ``<AGENT_INSTRUCTIONS>`` for execute-type system messages,
        or ``None`` when no files were found or ``workspace`` is unset.
    """
    if not workspace:
        return None
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        return None

    candidates: list[tuple[str, Path]] = [
        (path.relative_to(root).as_posix(), path)
        for path in _agents_md_candidates(root)
        if path.is_file()
    ]
    if not candidates:
        claude_path = root / "CLAUDE.md"
        if claude_path.is_file():
            candidates.append(("CLAUDE.md", claude_path))

    for label, path in candidates:
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError as exc:
            logger.debug("stat failed for %s: %s", path, exc)
            continue
        block = _build_block_cached(
            label=label,
            path_str=str(path),
            mtime_ns=mtime_ns,
            max_lines=max_lines,
            headline_max_chars=headline_max_chars,
        )
        if block is not None:
            return block
    return None


@functools.lru_cache(maxsize=32)
def _build_block_cached(
    *,
    label: str,
    path_str: str,
    mtime_ns: int,  # cache key — invalidates on file edit
    max_lines: int,
    headline_max_chars: int,
) -> str | None:
    """Read + format one instruction file. Cached on ``(path, mtime, caps)``."""
    path = Path(path_str)
    body, truncated_lines = _read_file_head_lines(path, max_lines=max_lines)
    if not body.strip():
        return None
    headline, partial = _headline_excerpt(body, max_chars=headline_max_chars)
    inlined: Literal["full", "partial"] = "partial" if partial else "full"
    block = _format_instruction_block(
        label,
        path,
        headline,
        truncated_lines=truncated_lines,
        inlined=inlined,
    )
    if partial or truncated_lines:
        note = f'\n<NOTE>Full body — use `read_file("{path}")` to load on demand.</NOTE>'
    else:
        note = ""
    return "<AGENT_INSTRUCTIONS>\n" + block + note + "\n</AGENT_INSTRUCTIONS>"


def _format_instruction_block(
    label: str,
    path: Path,
    body: str,
    *,
    truncated_lines: bool,
    inlined: Literal["full", "partial"],
) -> str:
    """Format one instruction file as a CDATA-wrapped XML element."""
    trunc_attr = "true" if truncated_lines else "false"
    return (
        f'<FILE name="{label}" path="{path}" inlined="{inlined}" '
        f'truncated_lines="{trunc_attr}">\n'
        f"<![CDATA[\n{body}\n]]>\n"
        f"</FILE>"
    )


load_workspace_project_instructions = load_agent_instructions

__all__ = [
    "DEFAULT_PROJECT_INSTRUCTION_MAX_LINES",
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "load_agent_instructions",
    "load_workspace_project_instructions",
]
