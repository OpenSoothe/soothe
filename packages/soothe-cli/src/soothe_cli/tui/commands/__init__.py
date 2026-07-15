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
    SUBAGENT_DISPLAY_NAMES,
    SUBAGENT_SLASH_ROUTE_IDS,
    get_subagent_display_name,
    parse_subagent_from_input,
)

__all__ = [
    "SUBAGENT_DISPLAY_NAMES",
    "SUBAGENT_SLASH_ROUTE_IDS",
    "find_command_by_daemon_command",
    "get_subagent_display_name",
    "handle_rpc_command",
    "handle_routing_command",
    "parse_command_params",
    "parse_slash_command",
    "parse_subagent_from_input",
    "route_slash_command",
    "validate_command",
]
