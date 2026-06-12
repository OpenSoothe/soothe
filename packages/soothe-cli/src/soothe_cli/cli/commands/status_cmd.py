"""Daemon status CLI command for client-side validation.

Provides lightweight status checks for the soothe daemon from the client side,
useful for validating daemon connectivity before running commands.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from soothe_sdk.client import WebSocketClient, is_daemon_live, websocket_url_from_config

from soothe_cli.config.loader import load_config

console = Console()

# Create status command group
status_app = typer.Typer(help="Check daemon and client status", no_args_is_help=False)


async def _fetch_status(ws_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch daemon status via WebSocket RPC.

    Args:
        ws_url: WebSocket URL to connect to.
        timeout: Request timeout in seconds.

    Returns:
        Status dict from daemon, or error dict on failure.
    """
    client = WebSocketClient(url=ws_url)
    try:
        await client.connect()
        status = await client.fetch_daemon_status(timeout=timeout)
        return status
    except Exception as e:
        return {"error": str(e)}
    finally:
        await client.close()


async def _fetch_ready_state(ws_url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Fetch daemon readiness state via WebSocket handshake.

    The daemon sends a daemon_ready message on connect with its state.

    Args:
        ws_url: WebSocket URL.
        timeout: Timeout for handshake.

    Returns:
        daemon_ready message dict or None.
    """
    import websockets

    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(ws_url) as ws:
                # Read initial messages - daemon sends status then daemon_ready
                for _ in range(3):
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("type") == "daemon_ready":
                        return data
    except Exception:
        pass
    return None


def _render_connection_table(config: Any, ws_url: str) -> Table:
    """Render connection settings table."""
    table = Table(title="Connection Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("WebSocket URL", ws_url)
    table.add_row("Daemon Host", config.daemon_host)
    table.add_row("Daemon Port", str(config.daemon_port))
    table.add_row("Soothe Home", str(config.soothe_home))

    return table


def _render_daemon_table(
    ws_url: str,
    running: bool,
    port_live: bool,
    active_threads: int,
    daemon_pid: int | None,
    ready_state: dict[str, Any] | None = None,
) -> Table:
    """Render daemon status table."""
    table = Table(title="Daemon Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("WebSocket URL", ws_url)
    table.add_row("Running", "[green]Yes[/green]" if running else "[red]No[/red]")
    table.add_row("Port Live", "[green]Yes[/green]" if port_live else "[red]No[/red]")
    table.add_row("Active Threads", str(active_threads))
    if daemon_pid:
        table.add_row("Daemon PID", str(daemon_pid))

    if ready_state:
        state = ready_state.get("state", "unknown")
        state_color = {
            "ready": "green",
            "degraded": "yellow",
            "error": "red",
            "starting": "blue",
            "warming": "blue",
            "stopped": "dim",
        }.get(state, "white")
        table.add_row("Readiness", f"[{state_color}]{state}[/{state_color}]")
        if ready_state.get("message"):
            table.add_row("Message", ready_state["message"])

    return table


@status_app.command("daemon")
def daemon_status(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed status."),
    ] = False,
) -> None:
    """Check daemon status from client side.

    Validates that the soothe daemon is running and responsive.

    Examples:
        soothe status daemon
        soothe status daemon --json
        soothe status daemon -v
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)

    # Quick liveness check
    live = asyncio.run(is_daemon_live(ws_url, timeout=5.0))

    if not live:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "status": "not_running",
                        "websocket_url": ws_url,
                        "message": "Daemon not reachable",
                    }
                )
            )
        else:
            console.print(
                Panel(
                    f"WebSocket URL: {ws_url}\n"
                    "Status: [red]Not running[/red]\n"
                    "Hint: Start with 'soothed start'",
                    title="Daemon Status",
                    border_style="red",
                )
            )
        sys.exit(1)

    # Fetch detailed status
    status = asyncio.run(_fetch_status(ws_url, timeout=5.0))

    if "error" in status:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "status": "error",
                        "websocket_url": ws_url,
                        "error": status["error"],
                    }
                )
            )
        else:
            console.print(
                Panel(
                    f"WebSocket URL: {ws_url}\nError: [red]{status['error']}[/red]",
                    title="Daemon Status",
                    border_style="red",
                )
            )
        sys.exit(1)

    # Get readiness state for verbose mode
    ready_state = None
    if verbose:
        ready_state = asyncio.run(_fetch_ready_state(ws_url, timeout=5.0))

    if json_output:
        output = {
            "status": "running",
            "websocket_url": ws_url,
            "running": status.get("running", True),
            "port_live": status.get("port_live", True),
            "active_threads": status.get("active_threads", 0),
            "daemon_pid": status.get("daemon_pid"),
        }
        if ready_state:
            output["readiness_state"] = ready_state.get("state", "unknown")
            output["readiness_message"] = ready_state.get("message")
        console.print_json(json.dumps(output))
        return

    # Render daemon status table
    running = status.get("running", True)
    port_live = status.get("port_live", True)
    active_threads = status.get("active_threads", 0)
    daemon_pid = status.get("daemon_pid")

    table = _render_daemon_table(
        ws_url, running, port_live, active_threads, daemon_pid, ready_state
    )
    console.print(table)


@status_app.command("connection")
def connection_status(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Check client-daemon connection settings.

    Shows the WebSocket URL and connection parameters the CLI will use.

    Examples:
        soothe status connection
        soothe status connection --json
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)

    if json_output:
        console.print_json(
            json.dumps(
                {
                    "websocket_url": ws_url,
                    "daemon_host": config.daemon_host,
                    "daemon_port": config.daemon_port,
                    "soothe_home": str(config.soothe_home),
                }
            )
        )
        return

    table = _render_connection_table(config, ws_url)
    console.print(table)


@status_app.callback(invoke_without_command=True)
def status_main(
    ctx: typer.Context,
    show_help: Annotated[
        bool,
        typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Show overall daemon and connection status (default when no subcommand)."""
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)

    if ctx.invoked_subcommand is not None:
        return

    config = load_config()
    ws_url = websocket_url_from_config(config)

    # Check daemon liveness
    live = asyncio.run(is_daemon_live(ws_url, timeout=5.0))

    if json_output:
        output: dict[str, Any] = {
            "daemon": {
                "status": "running" if live else "not_running",
                "websocket_url": ws_url,
            },
            "connection": {
                "daemon_host": config.daemon_host,
                "daemon_port": config.daemon_port,
                "soothe_home": str(config.soothe_home),
            },
        }
        if live:
            status = asyncio.run(_fetch_status(ws_url, timeout=5.0))
            if "error" not in status:
                output["daemon"]["running"] = status.get("running", True)
                output["daemon"]["port_live"] = status.get("port_live", True)
                output["daemon"]["active_threads"] = status.get("active_threads", 0)
                output["daemon"]["daemon_pid"] = status.get("daemon_pid")
        console.print_json(json.dumps(output))
        return

    # Render combined status with tables
    if not live:
        console.print(
            Panel(
                f"WebSocket URL: {ws_url}\n"
                f"Daemon Host: {config.daemon_host}\n"
                f"Daemon Port: {config.daemon_port}\n"
                f"Soothe Home: {config.soothe_home}\n\n"
                "Daemon Status: [red]Not running[/red]\n"
                "Hint: Start with 'soothed start'",
                title="Soothe Status",
                border_style="red",
            )
        )
        sys.exit(1)

    # Fetch detailed daemon status
    status = asyncio.run(_fetch_status(ws_url, timeout=5.0))

    if "error" in status:
        console.print(
            Panel(
                f"WebSocket URL: {ws_url}\n"
                f"Daemon Host: {config.daemon_host}\n"
                f"Daemon Port: {config.daemon_port}\n"
                f"Soothe Home: {config.soothe_home}\n\n"
                f"Daemon Status: [red]Error[/red]\n"
                f"Error: {status['error']}",
                title="Soothe Status",
                border_style="red",
            )
        )
        sys.exit(1)

    # Render both tables
    connection_table = _render_connection_table(config, ws_url)
    console.print(connection_table)

    running = status.get("running", True)
    port_live = status.get("port_live", True)
    active_threads = status.get("active_threads", 0)
    daemon_pid = status.get("daemon_pid")

    daemon_table = _render_daemon_table(ws_url, running, port_live, active_threads, daemon_pid)
    console.print(daemon_table)


__all__ = [
    "status_app",
    "daemon_status",
    "connection_status",
]
