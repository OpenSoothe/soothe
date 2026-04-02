"""Subagent display names and routing helpers (CLI module path; implementation in shared)."""

from __future__ import annotations

from soothe.ux.shared.subagent_routing import (
    BUILTIN_SUBAGENT_NAMES,
    SUBAGENT_DISPLAY_NAMES,
    get_subagent_display_name,
    parse_subagent_from_input,
)

__all__ = [
    "BUILTIN_SUBAGENT_NAMES",
    "SUBAGENT_DISPLAY_NAMES",
    "get_subagent_display_name",
    "parse_subagent_from_input",
]
