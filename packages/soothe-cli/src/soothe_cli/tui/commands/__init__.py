"""Slash command routing and handling."""

from soothe_cli.tui.commands.command_router import (
    find_command_by_daemon_command,
    handle_routing_command,
    handle_rpc_command,
    parse_command_params,
    parse_slash_command,
    route_slash_command,
    validate_command,
)
from soothe_cli.tui.commands.subagent_routing import (
    BUILTIN_SUBAGENT_NAMES,
    SUBAGENT_DISPLAY_NAMES,
    get_subagent_display_name,
    parse_subagent_from_input,
)

# Backward-compatible names
route_command = route_slash_command
parse_subagent_command = parse_subagent_from_input

__all__ = [
    "BUILTIN_SUBAGENT_NAMES",
    "SUBAGENT_DISPLAY_NAMES",
    "find_command_by_daemon_command",
    "get_subagent_display_name",
    "handle_rpc_command",
    "handle_routing_command",
    "parse_command_params",
    "parse_slash_command",
    "parse_subagent_command",
    "parse_subagent_from_input",
    "route_command",
    "route_slash_command",
    "validate_command",
]
