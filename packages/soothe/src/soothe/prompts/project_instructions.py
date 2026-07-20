"""Host wrappers for shared AGENTS.md/CLAUDE.md prompt loading."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.prompts import project_instructions as _nano_project_instructions
from soothe_nano.prompts.project_instructions import (
    DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
)

_build_block_cached = _nano_project_instructions._build_block_cached
_read_file_head_lines = _nano_project_instructions._read_file_head_lines


def _sync_test_hooks() -> None:
    """Keep monkeypatchable helper references aligned with nano implementation."""
    if _nano_project_instructions._read_file_head_lines is _read_file_head_lines:
        return
    _nano_project_instructions._read_file_head_lines = _read_file_head_lines
    _build_block_cached.cache_clear()


def load_agent_instructions(
    workspace: str | Path | None,
    *,
    max_lines: int = DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    headline_max_chars: int = PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
) -> str | None:
    """Load AGENTS.md/CLAUDE.md using nano implementation with host test hooks."""
    _sync_test_hooks()
    return _nano_project_instructions.load_agent_instructions(
        workspace,
        max_lines=max_lines,
        headline_max_chars=headline_max_chars,
    )


def load_workspace_project_instructions(
    workspace: str | Path | None,
    *,
    max_lines: int = DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    headline_max_chars: int = PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
) -> str | None:
    """Compat alias for workspace project instruction loading."""
    return load_agent_instructions(
        workspace,
        max_lines=max_lines,
        headline_max_chars=headline_max_chars,
    )


__all__ = [
    "DEFAULT_PROJECT_INSTRUCTION_MAX_LINES",
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "load_agent_instructions",
    "load_workspace_project_instructions",
]
