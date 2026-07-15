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
from soothe_client import (
    WebSocketClient,
    check_daemon_status,
    is_daemon_live,
    websocket_url_from_config,
)

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
        return await check_daemon_status(client, timeout=timeout)
    except Exception as e:
        return {"error": str(e)}
    finally:
        await client.close()


def _render_unified_status_table(
    config: Any,
    ws_url: str,
    running: bool | None = None,
    port_live: bool | None = None,
    active_threads: int | None = None,
    daemon_pid: int | None = None,
    ready_state: dict[str, Any] | None = None,
    daemon_live: bool = True,
    daemon_version: str | None = None,
    core_version: str | None = None,
) -> Table:
    """Render unified status table without duplicated info.

    Sections:
    - Connection: WebSocket URL, Soothe Home
    - Daemon: Running, Threads, PID, Versions (only when daemon is live)
    """
    table = Table(title="Soothe Status")
    table.add_column("Section", style="dim", width=12)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    # Connection section
    table.add_row("Connection", "WebSocket URL", ws_url)
    table.add_row("", "Soothe Home", str(config.soothe_home))

    # Daemon section
    if not daemon_live:
        table.add_row("Daemon", "Status", "[red]Not running[/red]")
        return table

    table.add_row("Daemon", "Status", "[green]Running[/green]")
    if daemon_pid:
        table.add_row("", "PID", str(daemon_pid))
    if active_threads is not None:
        table.add_row("", "Active Threads", str(active_threads))
    if daemon_version:
        table.add_row("", "Daemon Version", daemon_version)
    if core_version:
        table.add_row("", "Core Version", core_version)

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
        table.add_row("", "Readiness", f"[{state_color}]{state}[/{state_color}]")
        if ready_state.get("message"):
            table.add_row("", "Message", ready_state["message"])

    return table


@status_app.command("daemon")
def daemon_status(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON."),
    ] = False,
) -> None:
    """Check daemon status from client side.

    Validates that the soothe daemon is running and responsive.

    Examples:
        soothe status daemon
        soothe status daemon --json
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
            table = _render_unified_status_table(config, ws_url, daemon_live=False)
            console.print(table)
            console.print("\n[dim]Hint: Start with 'soothed start'[/dim]")
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

    if json_output:
        output = {
            "status": "running",
            "websocket_url": ws_url,
            "running": status.get("running", True),
            "port_live": status.get("port_live", True),
            "active_threads": status.get("active_threads", 0),
            "daemon_pid": status.get("daemon_pid"),
            "daemon_version": status.get("daemon_version"),
            "core_version": status.get("core_version"),
            "readiness_state": status.get("readiness_state", "unknown"),
        }
        if status.get("readiness_message"):
            output["readiness_message"] = status.get("readiness_message")
        console.print_json(json.dumps(output))
        return

    # Render unified daemon status table
    running = status.get("running", True)
    port_live = status.get("port_live", True)
    active_threads = status.get("active_threads", 0)
    daemon_pid = status.get("daemon_pid")
    daemon_version = status.get("daemon_version")
    core_version = status.get("core_version")
    # Use readiness_state from daemon_status RPC (already includes state + message)
    readiness_state_from_status = (
        {
            "state": status.get("readiness_state", "unknown"),
            "message": status.get("readiness_message"),
        }
        if status.get("readiness_state")
        else None
    )

    table = _render_unified_status_table(
        config,
        ws_url,
        running,
        port_live,
        active_threads,
        daemon_pid,
        readiness_state_from_status,
        daemon_live=True,
        daemon_version=daemon_version,
        core_version=core_version,
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

    # Simple connection table
    table = Table(title="Connection Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("WebSocket URL", ws_url)
    table.add_row("Soothe Home", str(config.soothe_home))
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
                output["daemon"]["daemon_version"] = status.get("daemon_version")
                output["daemon"]["core_version"] = status.get("core_version")
                output["daemon"]["readiness_state"] = status.get("readiness_state", "unknown")
                if status.get("readiness_message"):
                    output["daemon"]["readiness_message"] = status.get("readiness_message")
        console.print_json(json.dumps(output))
        return

    # Render unified status table
    if not live:
        table = _render_unified_status_table(config, ws_url, daemon_live=False)
        console.print(table)
        console.print("\n[dim]Hint: Start with 'soothed start'[/dim]")
        sys.exit(1)

    # Fetch detailed daemon status
    status = asyncio.run(_fetch_status(ws_url, timeout=5.0))

    if "error" in status:
        console.print(
            Panel(
                f"WebSocket URL: {ws_url}\nError: [red]{status['error']}[/red]",
                title="Daemon Status",
                border_style="red",
            )
        )
        sys.exit(1)

    running = status.get("running", True)
    port_live = status.get("port_live", True)
    active_threads = status.get("active_threads", 0)
    daemon_pid = status.get("daemon_pid")
    daemon_version = status.get("daemon_version")
    core_version = status.get("core_version")
    # Use readiness_state from daemon_status RPC (already includes state + message)
    readiness_state_from_status = (
        {
            "state": status.get("readiness_state", "unknown"),
            "message": status.get("readiness_message"),
        }
        if status.get("readiness_state")
        else None
    )

    table = _render_unified_status_table(
        config,
        ws_url,
        running,
        port_live,
        active_threads,
        daemon_pid,
        readiness_state_from_status,
        daemon_live=True,
        daemon_version=daemon_version,
        core_version=core_version,
    )
    console.print(table)


__all__ = [
    "status_app",
    "daemon_status",
    "connection_status",
]
