"""Host wrappers for shared AGENTS.md/CLAUDE.md prompt loading.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.prompts.project_instructions``.
"""

from __future__ import annotations

# Re-export facade — canonical source: soothe_nano.prompts.project_instructions
from soothe_nano.prompts.project_instructions import (
    DEFAULT_PROJECT_INSTRUCTION_MAX_LINES,
    PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
    build_block_cached,
    load_agent_instructions,
    load_workspace_project_instructions,
    read_file_head_lines,
)

__all__ = [
    "DEFAULT_PROJECT_INSTRUCTION_MAX_LINES",
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "build_block_cached",
    "load_agent_instructions",
    "load_workspace_project_instructions",
    "read_file_head_lines",
]
