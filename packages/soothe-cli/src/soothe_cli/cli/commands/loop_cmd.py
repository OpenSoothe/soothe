"""Loop management CLI commands for StrangeLoop instances.: Loop-First User Experience: Loop Management CLI Commands

All loop operations use daemon WebSocket RPC; the daemon must be running.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from soothe_client import (
    is_daemon_live,
    protocol1_rpc,
    websocket_url_from_config,
)

from soothe_cli.runtime import load_config

console = Console()
logger = logging.getLogger(__name__)

# Create loop command group
loop_app = typer.Typer(help="Manage StrangeLoop instances.")


def _require_daemon(ws_url: str) -> None:
    """Check daemon is running, exit with error if not."""
    live = asyncio.run(_check_daemon(ws_url))
    if not live:
        typer.echo(
            "Error: Daemon not running. Start with 'soothed start'.",
            err=True,
        )
        sys.exit(1)


async def _check_daemon(ws_url: str) -> bool:
    return await is_daemon_live(ws_url, timeout=5.0)


def _resolve_continue_loop_id(ws_url: str, loop_id: str | None) -> str:
    """Resolve target loop ID for `loop continue`.

    If `loop_id` is omitted, chooses the most recent loop, preferring active
    statuses such as `running` and `detached`.
    """
    if loop_id:
        return loop_id

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_list",
            {"limit": 20},
        )
    )
    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    loops = response.get("loops", [])
    if not loops:
        typer.echo(
            "Error: No loops found. Start one first with `soothe loop new`.",
            err=True,
        )
        sys.exit(1)

    preferred_statuses = {"running", "detached"}
    selected = next(
        (loop for loop in loops if loop.get("status") in preferred_statuses),
        loops[0],
    )
    selected_loop_id = str(selected.get("loop_id", "")).strip()
    if not selected_loop_id:
        typer.echo(
            "Error: Unable to resolve loop ID from loop list response.",
            err=True,
        )
        sys.exit(1)

    console.print(
        "[info]No LOOP_ID provided; using most recent loop: "
        f"{selected_loop_id} ({selected.get('status', 'unknown')})[/info]"
    )
    return selected_loop_id


@loop_app.command("list")
def list_loops(
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (running, completed, detached)."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Limit number of results."),
    ] = 20,
) -> None:
    """List all StrangeLoop instances.

    Examples:
    soothe loop list
    soothe loop list --status running
    soothe loop list --limit 10
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_list",
            {"filter": {"status": status} if status else None, "limit": limit},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    loops = response.get("loops", [])
    if not loops:
        console.print("[info]No loops found matching criteria.[/info]")
        return

    # Render table
    table = Table(title="StrangeLoops")
    table.add_column("Loop ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Goals", justify="right")
    table.add_column("Switches", justify="right")
    table.add_column("Created", style="dim")

    for loop in loops:
        table.add_row(
            loop.get("loop_id", ""),
            loop.get("status", "unknown"),
            str(loop.get("goals", 0)),
            str(loop.get("switches", 0)),
            loop.get("created", "")[:16],
        )

    console.print(table)


@loop_app.command("show")
def describe_loop(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier.")],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed branch analysis."),
    ] = False,
) -> None:
    """Show detailed loop information.

    Example:
    soothe loop show loop_abc123
    soothe loop show loop_abc123 --verbose
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_get",
            {"loop_id": loop_id, "verbose": verbose},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    loop = response.get("loop", {})
    if not loop:
        typer.echo(f"Error: Loop {loop_id} not found", err=True)
        sys.exit(1)

    # Render basic info
    console.print(
        Panel(
            f"Loop: {loop.get('loop_id', loop_id)}\n"
            f"Status: {loop.get('status', 'unknown')}\n"
            f"Schema: {loop.get('schema_version', 'unknown')}",
            title="Loop Overview",
            border_style="cyan",
        )
    )

    # Execution summary
    console.print(
        Panel(
            f"Goals Completed: {loop.get('total_goals_completed', 0)}\n"
            f"Context switches: {loop.get('total_thread_switches', 0)}\n"
            f"Duration: {format_duration(loop.get('total_duration_ms', 0))}\n"
            f"Tokens Used: {format_tokens(loop.get('total_tokens_used', 0))}",
            title="Execution Summary",
            border_style="green",
        )
    )

    # Timeline
    console.print(
        Panel(
            f"Created: {loop.get('created_at', 'unknown')}\n"
            f"Updated: {loop.get('updated_at', 'unknown')}",
            title="Timeline",
            border_style="dim",
        )
    )


@loop_app.command("delete")
def delete_loop(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier.")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Delete without confirmation."),
    ] = False,
) -> None:
    """Delete loop entirely.

    Removes this loop's run directory and related artifacts.

    Example:
    soothe loop delete loop_abc123
    soothe loop delete loop_abc123 --force
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    # Get loop metadata for confirmation
    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_get",
            {"loop_id": loop_id, "verbose": False},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    loop = response.get("loop", {})
    if not loop:
        typer.echo(f"Error: Loop {loop_id} not found", err=True)
        sys.exit(1)

    if not force:
        console.print(
            f"[warning]Warning: This will permanently delete {loop_id} and all associated data:[/warning]"
        )
        console.print(f"  - {loop.get('total_goals_completed', 0)} goal execution records")
        console.print("  - Working memory spills")

        confirm = Prompt.ask("Are you sure?", choices=["y", "N"], default="N")
        if confirm != "y":
            console.print("[info]Cancelled.[/info]")
            return

    # Delete loop
    delete_response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_delete",
            {"loop_id": loop_id},
        )
    )

    if "error" in delete_response:
        typer.echo(f"Error: {delete_response['error']}", err=True)
        sys.exit(1)

    console.print(f"[success]Deleted {loop_id}:[/success]")
    console.print("  Removed checkpoint database")
    console.print("  Removed metadata")
    console.print("  Removed working memory spills")
    console.print("[dim]  LangGraph checkpoints may remain until pruned separately[/dim]")


# Helper functions


def format_duration(duration_ms: int) -> str:
    """Format duration in human-readable format."""
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    elif duration_ms < 60000:
        return f"{duration_ms // 1000}s"
    elif duration_ms < 3600000:
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) // 1000
        return f"{minutes}m {seconds}s"
    else:
        hours = duration_ms // 3600000
        minutes = (duration_ms % 3600000) // 60000
        return f"{hours}h {minutes}m"


def format_tokens(tokens: int) -> str:
    """Format token count."""
    if tokens < 1000:
        return str(tokens)
    elif tokens < 1000000:
        return f"{tokens // 1000}K"
    else:
        return f"{tokens // 1000000}M"


@loop_app.command("continue")
def continue_loop(
    loop_id: Annotated[str | None, typer.Argument(help="Loop identifier to continue.")] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Optional prompt to send after continuing."),
    ] = None,
) -> None:
    """Continue execution on an existing loop.

    Behavior:
    - Resolve target loop (explicit `LOOP_ID` or most-recent loop)
    - Launch TUI on that loop, which resumes from the daemon's last execution
    step index unless the loop is unknown or already finished
    - Optionally submit initial prompt in the resumed session

    Example:
    soothe loop continue
    soothe loop continue loop_abc123
    soothe loop continue loop_abc123 --prompt "translate to chinese"
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)
    resolved_loop_id = _resolve_continue_loop_id(ws_url, loop_id)

    # Show explicit message when user specified a loop_id
    if loop_id:
        console.print(f"[info]Continuing loop: {resolved_loop_id}[/info]")

    from soothe_cli.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        resume_loop_id=resolved_loop_id,
        no_tui=False,
    )


@loop_app.command("resume")
def resume_loop(
    loop_id: Annotated[str | None, typer.Argument(help="Loop identifier to continue.")] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Optional prompt to send after continuing."),
    ] = None,
) -> None:
    """Alias for continue — resume from the daemon's last execution step index."""
    continue_loop(loop_id, prompt)


@loop_app.command("detach")
def detach_loop(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier to detach.")],
) -> None:
    """Detach loop (keep running in the background).

    Behavior:
    - Unsubscribe client from loop events
    - Loop keeps running on the daemon
    - Loop checkpoint saved at detachment point
    - Client can reattach later with 'soothe loop attach'

    Example:
    soothe loop detach loop_abc123
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_detach",
            {"loop_id": loop_id},
            mode="notify",
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    console.print(f"[success]Detached loop {loop_id}[/success]")
    console.print("[info]Loop continues running in background[/info]")
    console.print("[dim]To reattach: soothe loop attach {loop_id}[/dim]")


@loop_app.command("attach")
def attach_loop(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier to attach.")],
) -> None:
    """Attach to detached loop (reattach capability).

    Behavior:
    - Subscribe client to loop events
    - Reconstruct full history from loop checkpoint
    - Send history replay to client
    - Show current loop status

    Example:
    soothe loop attach loop_abc123
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    # Subscribe to loop (same as continue)
    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_events",
            {"loop_id": loop_id},
            mode="subscribe",
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    console.print(f"[success]Attached to loop {loop_id}[/success]")

    # Show reattachment status
    status_response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_get",
            {"loop_id": loop_id, "verbose": False},
        )
    )

    loop = status_response.get("loop", {})
    detached_at = loop.get("detached_at")
    if detached_at:
        console.print(f"[dim]Previously detached at: {detached_at}[/dim]")

    console.print(
        Panel(
            f"Status: {loop.get('status', 'unknown')}\n"
            f"Goals: {loop.get('total_goals_completed', 0)} completed",
            title=f"Loop: {loop_id} (Reattached)",
        )
    )


@loop_app.command("new")
def new_loop(
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Optional prompt to send on new loop."),
    ] = None,
) -> None:
    """Create fresh loop for new query.

    Example:
    soothe loop new
    soothe loop new --prompt "analyze performance"
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    # Create new loop
    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_new",
            {},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    loop_id = response.get("loop_id")
    console.print(f"[success]Created new loop: {loop_id}[/success]")

    # Execute prompt if provided
    if prompt:
        input_response = asyncio.run(
            protocol1_rpc(
                ws_url,
                "loop_input",
                {"loop_id": loop_id, "content": prompt},
                mode="notify",
            )
        )
        if "error" in input_response:
            typer.echo(f"Error: {input_response['error']}", err=True)
            sys.exit(1)
        console.print("[info]Prompt sent to new loop[/info]")


__all__ = [
    "loop_app",
    "list_loops",
    "describe_loop",
    "delete_loop",
    "continue_loop",
    "resume_loop",
    "detach_loop",
    "attach_loop",
    "new_loop",
]
