"""Host wrappers for shared AGENTS.md/CLAUDE.md prompt loading.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.prompts.project_instructions``.  The host adds a test-hook
sync helper for monkeypatch propagation; all business logic is in nano.
"""

from __future__ import annotations

from pathlib import Path

# Re-export facade — canonical source: soothe_nano.prompts.project_instructions
from soothe_nano.prompts import project_instructions
from soothe_nano.prompts.project_instructions import (
    DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
    build_block_cached,
    read_file_head_lines,
)


def _sync_test_hooks() -> None:
    """Propagate host-module monkeypatches of ``read_file_head_lines`` into nano.

    Tests monkeypatch this module's public ``read_file_head_lines`` attribute to
    intercept disk reads. Since ``load_agent_instructions`` delegates to nano,
    the patched reference must be propagated into nano's module globals so
    ``build_block_cached`` (which calls the public alias) picks it up.
    """
    if project_instructions.read_file_head_lines is read_file_head_lines:
        return
    project_instructions.read_file_head_lines = read_file_head_lines
    build_block_cached.cache_clear()


def load_agent_instructions(
    workspace: str | Path | None,
    *,
    max_lines: int = DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    headline_max_chars: int = PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
) -> str | None:
    """Load AGENTS.md/CLAUDE.md using nano implementation with host test hooks."""
    _sync_test_hooks()
    return project_instructions.load_agent_instructions(
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
    """Compat alias — routes through host ``load_agent_instructions`` (test hooks)."""
    return load_agent_instructions(
        workspace,
        max_lines=max_lines,
        headline_max_chars=headline_max_chars,
    )


__all__ = [
    "DEFAULT_PROJECT_INSTRUCTION_MAX_LINES",
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "build_block_cached",
    "load_agent_instructions",
    "load_workspace_project_instructions",
    "read_file_head_lines",
]
