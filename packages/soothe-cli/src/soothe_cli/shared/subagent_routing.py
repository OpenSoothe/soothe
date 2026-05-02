"""Compatibility re-export (IG-351). Implementation lives in ``commands.subagent_routing``."""

from soothe_cli.shared.commands.subagent_routing import (
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
