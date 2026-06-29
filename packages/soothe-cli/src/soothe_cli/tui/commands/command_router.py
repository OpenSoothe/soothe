"""Command routing logic for CLI/TUI (RFC-454).

Routes slash commands based on registry metadata:
- CLI-only commands: handled locally
- Daemon RPC commands: send command_request, handle command_response
- Daemon routing commands: send plain text input
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from soothe_cli.tui.commands.subagent_routing import parse_subagent_from_input

if TYPE_CHECKING:
    from rich.console import Console
    from soothe_sdk.client import WebSocketClient

logger = logging.getLogger(__name__)


def parse_slash_command(input_text: str) -> tuple[str, str | None]:
    """Parse slash command and extract command + query.

    Args:
        input_text: Full user input (e.g., "/research topic summary")

    Returns:
        Tuple of (command, query) where query may be None
    """
    stripped = input_text.strip()
    if not stripped.startswith("/"):
        return ("", None)

    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    query = parts[1] if len(parts) > 1 else None

    return (command, query)


def validate_command(
    entry: dict[str, Any], command: str, query: str | None, loop_id: str | None
) -> tuple[bool, str | None]:
    """Validate command before routing.

    Args:
        entry: Command registry entry
        command: Command name
        query: Query parameter (if present)
        loop_id: Active StrangeLoop id for this session

    Returns:
        Tuple of (is_valid, error_message)
    """
    if entry.get("requires_loop") and not loop_id:
        return (False, "No active loop")

    # Check query requirement for routing commands
    if entry.get("requires_query") and not query:
        return (False, f"Command requires query: {command} <query>")

    return (True, None)


def find_command_by_daemon_command(daemon_command: str) -> dict[str, Any] | None:
    """Find command entry by daemon command name.

    Args:
        daemon_command: Daemon command name (e.g., "memory")

    Returns:
        Command entry dict or None if not found
    """
    from soothe_cli.tui.commands.slash_commands import COMMANDS

    for cmd_name, entry in COMMANDS.items():
        if entry.get("daemon_command") == daemon_command:
            return entry
    return None


def parse_command_params(entry: dict[str, Any], query: str) -> dict[str, Any]:
    """Parse query into params based on schema.

    Args:
        entry: Command registry entry with params_schema
        query: Query string to parse

    Returns:
        Dict of params
    """
    schema = entry.get("params_schema", {})
    if not schema:
        return {}

    parts = query.strip().split()
    params = {}

    # Map parts to schema keys
    schema_keys = list(schema.keys())
    for i, part in enumerate(parts):
        if i < len(schema_keys):
            key = schema_keys[i]
            params[key] = part

    return params


async def route_slash_command(
    cmd_input: str,
    console: Console,
    client: WebSocketClient,
    *,
    loop_id: str | None = None,
) -> bool:
    """Route slash command based on registry metadata (RFC-454).

    Args:
        cmd_input: Full command input (e.g., "/memory", "/research topic")
        console: Rich console for rendering
        client: WebSocket client for daemon communication

    Returns:
        True if command was handled, False if unknown command
    """
    from soothe_cli.tui.commands.slash_commands import COMMANDS

    command, query = parse_slash_command(cmd_input)

    # Not a slash command
    if not command:
        return False

    # Lookup command in registry
    entry = COMMANDS.get(command)
    if not entry:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print("[dim]Type /help for available commands[/dim]")
        return True  # Handled (as error)

    # Validate command
    is_valid, error = validate_command(entry, command, query, loop_id)
    if not is_valid:
        console.print(f"[red]Error: {error}[/red]")
        return True  # Handled (as error)

    # Route based on location and type
    if entry["location"] == "cli":
        # CLI-only: call handler directly
        handler = entry.get("handler")
        if handler:
            handler(console)
        return True

    elif entry["location"] == "daemon" and entry.get("type") == "rpc":
        # Daemon RPC: send command_request (scoped by loop_id)
        await handle_rpc_command(entry, command, query, console, client, loop_id=loop_id)
        return True

    elif entry["location"] == "daemon" and entry.get("type") == "routing":
        # Daemon routing: send as plain text input
        await handle_routing_command(cmd_input, console, client, loop_id=loop_id)
        return True

    return False


async def handle_rpc_command(
    entry: dict[str, Any],
    command: str,
    query: str | None,
    console: Console,
    client: WebSocketClient,
    *,
    loop_id: str | None = None,
) -> None:
    """Handle daemon RPC command with structured request/response (RFC-454).

    Args:
        entry: Command registry entry
        command: Command name
        query: Query/params (if present)
        console: Rich console
        client: WebSocket client
        loop_id: Active subscribed loop (required for daemon-side binding)
    """
    daemon_command = entry["daemon_command"]

    # Build protocol-1 rpc_command params (RFC-450 §9.4). The wire method is
    # ``rpc_command``; ``command`` carries the daemon RPC name and ``payload``
    # carries the parsed args.
    rpc_params: dict[str, Any] = {"command": daemon_command}
    if loop_id:
        rpc_params["loop_id"] = loop_id
    if entry.get("params_schema") and query:
        rpc_params["payload"] = parse_command_params(entry, query)

    # Send request and wait for response
    try:
        response = await client.request("rpc_command", rpc_params, timeout=5.0)

        # Handle response
        if response.get("error"):
            console.print(f"[red]Error: {response['error']}[/red]")
        elif response.get("data"):
            handler = entry.get("handler")
            if handler:
                handler(console, response["data"])
            else:
                # Default: pretty print JSON
                from rich.panel import Panel

                console.print(
                    Panel(
                        json.dumps(response["data"], indent=2, default=str),
                        title=daemon_command,
                        border_style="cyan",
                    )
                )

    except TimeoutError:
        console.print("[red]Error: Command request timed out[/red]")
    except Exception as exc:
        logger.exception("RPC command failed")
        console.print(f"[red]Error: {exc}[/red]")


async def handle_routing_command(
    cmd_input: str,
    console: Console,
    client: WebSocketClient,
    *,
    loop_id: str | None = None,
) -> None:
    """Handle daemon routing command by sending input with optional subagent (RFC-454).

    For routing commands that map to a configured subagent id (e.g. ``/research``, ``/explore``),
    sets the WebSocket ``preferred_subagent`` field so the daemon merges a subagent hint into
    StrangeLoop (IG-349). Other routing commands (e.g. ``/plan``) are sent as plain text unchanged.

    Args:
        cmd_input: Full command input (e.g., "/research topic summary")
        console: Rich console
        client: WebSocket client
        loop_id: Subscribed loop to target (required for ``loop_input``)
    """
    if not loop_id:
        console.print("[red]Error: No active loop for routing command[/red]")
        return
    subagent_name, text = parse_subagent_from_input(cmd_input.strip())
    await client.send_input(loop_id, text, preferred_subagent=subagent_name)


__all__ = [
    "parse_slash_command",
    "route_slash_command",
    "validate_command",
    "find_command_by_daemon_command",
    "parse_command_params",
    "handle_rpc_command",
    "handle_routing_command",
]
