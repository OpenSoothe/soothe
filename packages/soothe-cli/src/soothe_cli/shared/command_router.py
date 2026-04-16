"""Command routing logic for CLI/TUI (RFC-404).

Routes slash commands based on registry metadata:
- CLI-only commands: handled locally
- Daemon RPC commands: send command_request, handle command_response
- Daemon routing commands: send plain text input
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console
    from soothe_sdk.client import WebSocketClient

logger = logging.getLogger(__name__)


def parse_slash_command(input_text: str) -> tuple[str, str | None]:
    """Parse slash command and extract command + query.

    Args:
        input_text: Full user input (e.g., "/browser AI trends")

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
    entry: dict[str, Any], command: str, query: str | None, thread_id: str | None
) -> tuple[bool, str | None]:
    """Validate command before routing.

    Args:
        entry: Command registry entry
        command: Command name
        query: Query parameter (if present)
        thread_id: Current thread ID

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check thread requirement
    if entry.get("requires_thread") and not thread_id:
        return (False, "No active thread")

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
    from soothe_cli.shared.slash_commands import COMMANDS

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


async def route_slash_command(cmd_input: str, console: Console, client: WebSocketClient) -> bool:
    """Route slash command based on registry metadata (RFC-404).

    Args:
        cmd_input: Full command input (e.g., "/memory", "/browser AI trends")
        console: Rich console for rendering
        client: WebSocket client for daemon communication

    Returns:
        True if command was handled, False if unknown command
    """
    from soothe_cli.shared.slash_commands import COMMANDS

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
    is_valid, error = validate_command(entry, command, query, client.thread_id)
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
        # Daemon RPC: send command_request
        await handle_rpc_command(entry, command, query, console, client)
        return True

    elif entry["location"] == "daemon" and entry.get("type") == "routing":
        # Daemon routing: send as plain text input
        await handle_routing_command(cmd_input, console, client)
        return True

    return False


async def handle_rpc_command(
    entry: dict[str, Any],
    command: str,
    query: str | None,
    console: Console,
    client: WebSocketClient,
) -> None:
    """Handle daemon RPC command with structured request/response (RFC-404).

    Args:
        entry: Command registry entry
        command: Command name
        query: Query/params (if present)
        console: Rich console
        client: WebSocket client
    """
    daemon_command = entry["daemon_command"]

    # Build request
    request = {
        "type": "command_request",
        "command": daemon_command,
        "thread_id": client.thread_id,
    }

    # Parse params if schema exists
    if entry.get("params_schema") and query:
        params = parse_command_params(entry, query)
        request["params"] = params

    # Send request and wait for response
    try:
        response = await client.request_response(
            request, response_type="command_response", timeout=5.0
        )

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


async def handle_routing_command(cmd_input: str, console: Console, client: WebSocketClient) -> None:
    """Handle daemon routing command by sending plain text input (RFC-404).

    Args:
        cmd_input: Full command input (e.g., "/browser AI trends")
        console: Rich console
        client: WebSocket client
    """
    # Send as plain text - daemon input parser will route
    await client.send_input(cmd_input)


__all__ = [
    "parse_slash_command",
    "route_slash_command",
    "validate_command",
    "find_command_by_daemon_command",
    "parse_command_params",
    "handle_rpc_command",
    "handle_routing_command",
]
