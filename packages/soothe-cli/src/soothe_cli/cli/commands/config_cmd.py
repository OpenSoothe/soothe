"""Config management CLI commands for the soothe daemon."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from soothe_client import (
    connected_websocket,
    request_daemon_config_reload,
    websocket_url_from_config,
)

from soothe_cli.config.loader import load_config

console = Console()

# Create config command group
config_app = typer.Typer(help="Manage daemon configuration", no_args_is_help=True)


async def _trigger_config_reload(ws_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Trigger config reload via WebSocket RPC.

    Args:
        ws_url: WebSocket URL to connect to.
        timeout: Request timeout in seconds.

    Returns:
        Response dict from daemon, or error dict on failure.
    """
    try:
        async with connected_websocket(ws_url, timeout=timeout) as client:
            return await request_daemon_config_reload(client, timeout=timeout)
    except Exception as e:
        return {"success": False, "error": str(e)}


@config_app.command("reload")
def config_reload(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Trigger config hot-reload on the running daemon.

    Sends a config_reload RPC request to the daemon, which triggers immediate
    reload of watched config files (config.yml and daemon.yml). Requires the
    daemon to have hot-reload enabled via daemon.enable_config_reload().

    Examples:
        soothe config reload
        soothe config reload --json
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)

    # Trigger reload
    result = asyncio.run(_trigger_config_reload(ws_url, timeout=5.0))

    if json_output:
        output = {
            "websocket_url": ws_url,
            "success": result.get("success", False),
        }
        if result.get("error"):
            output["error"] = result.get("error")
        if result.get("message"):
            output["message"] = result.get("message")
        console.print_json(json.dumps(output))
        return

    if result.get("success"):
        console.print(
            Panel(
                f"WebSocket URL: {ws_url}\n"
                f"Status: [green]Reload triggered[/green]\n"
                f"Message: {result.get('message', 'Config reload initiated')}",
                title="Config Reload",
                border_style="green",
            )
        )
    else:
        error_msg = result.get("error", "Unknown error")
        if result.get("message"):
            error_msg = result.get("message")
        console.print(
            Panel(
                f"WebSocket URL: {ws_url}\nStatus: [red]Failed[/red]\nError: {error_msg}",
                title="Config Reload",
                border_style="red",
            )
        )
        sys.exit(1)
