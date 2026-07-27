"""Host wrappers for shared AGENTS.md/CLAUDE.md prompt loading.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.prompts.project_instructions``.
"""

from __future__ import annotations

# Re-export facade — canonical source: soothe_nano.prompts.project_instructions
from soothe_nano.prompts.project_instructions import (
    PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
    build_block_cached,
    load_agent_instructions,
)

__all__ = [
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "build_block_cached",
    "load_agent_instructions",
]
