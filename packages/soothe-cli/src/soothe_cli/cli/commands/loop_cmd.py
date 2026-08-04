"""Loop management CLI commands for StrangeLoop instances.

RFC-503: Loop-First User Experience
RFC-504: Loop Management CLI Commands

All loop operations use daemon WebSocket RPC; the daemon must be running.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Annotated, Any

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
    table.add_column("Contexts", justify="right")
    table.add_column("Goals", justify="right")
    table.add_column("Switches", justify="right")
    table.add_column("Created", style="dim")

    for loop in loops:
        table.add_row(
            loop.get("loop_id", ""),
            loop.get("status", "unknown"),
            str(loop.get("threads", 0)),
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

    # Internal checkpoint context counts from loop metadata
    console.print(
        Panel(
            f"Internal contexts: {len(loop.get('thread_ids', []))}\n"
            f"Context switches: {loop.get('total_thread_switches', 0)}",
            title="Checkpoint contexts (internal)",
            border_style="dim",
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

    # Failed branches
    branches = loop.get("failed_branches", [])
    if branches:
        console.print(
            Panel(
                f"Failed Branches: {len(branches)}\n" + format_branch_summary(branches),
                title="Failed Branches",
                border_style="red",
            )
        )

        if verbose:
            # Detailed branch analysis
            for branch in branches:
                console.print(
                    Panel(
                        format_branch_details(branch),
                        title=f"Branch: {branch['branch_id']}",
                        border_style="error",
                    )
                )

    # Checkpoint anchors
    anchors = loop.get("checkpoint_anchors", [])
    if anchors:
        console.print(
            Panel(
                f"Checkpoint Anchors: {len(anchors)}\n" + format_anchor_summary(anchors),
                title="Checkpoint Anchors",
                border_style="blue",
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


@loop_app.command("tree")
def visualize_loop_tree(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier.")],
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Visualization format (ascii, json, dot)."),
    ] = "ascii",
) -> None:
    """Visualize checkpoint tree structure.

    Shows main execution line + failed branches with learning insights.

    Example:
        soothe loop tree loop_abc123
        soothe loop tree loop_abc123 --format json
        soothe loop tree loop_abc123 --format dot
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_tree",
            {"loop_id": loop_id, "format": format},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    tree = response.get("tree", {})
    if not tree:
        typer.echo(f"Error: No checkpoint tree for loop {loop_id}", err=True)
        sys.exit(1)

    # Render tree based on format
    if format == "ascii":
        render_ascii_tree(tree)
    elif format == "json":
        import json

        console.print_json(json.dumps(tree, indent=2))
    elif format == "dot":
        render_dot_tree(tree)
    else:
        typer.echo(f"Error: Unknown format: {format}", err=True)
        sys.exit(1)


@loop_app.command("prune")
def prune_loop_branches(
    loop_id: Annotated[str, typer.Argument(help="Loop identifier.")],
    retention_days: Annotated[
        int,
        typer.Option("--retention-days", "-r", help="Retention period in days."),
    ] = 30,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be pruned."),
    ] = False,
) -> None:
    """Prune old failed branches.

    Soft delete branches older than retention period.

    Example:
        soothe loop prune loop_abc123
        soothe loop prune loop_abc123 --retention-days 7
        soothe loop prune loop_abc123 --dry-run
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)

    response = asyncio.run(
        protocol1_rpc(
            ws_url,
            "loop_prune",
            {"loop_id": loop_id, "retention_days": retention_days, "dry_run": dry_run},
        )
    )

    if "error" in response:
        typer.echo(f"Error: {response['error']}", err=True)
        sys.exit(1)

    # Protocol-1: request() returns the result dict directly (e.g.
    # {"pruned": N, "remaining": N, "dry_run": bool}), not wrapped in {"result": ...}.
    pruned = response.get("pruned", 0)
    remaining = response.get("remaining", 0)
    console.print("[green]Summary:[/green]")
    console.print(f"  Branches pruned: {pruned}")
    console.print(f"  Remaining: {remaining}")


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
        console.print(f"  - {len(loop.get('thread_ids', []))} internal checkpoint contexts")
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


def format_branch_summary(branches: list[dict[str, Any]]) -> str:
    """Format failed branches summary."""
    lines = []
    for branch in branches:
        line = f"  [dim]{branch['branch_id']}[/dim] (iteration {branch['iteration']})\n"
        line += f"    Failure: [red]{branch['failure_reason']}[/red]\n"
        if branch.get("analyzed_at"):
            line += f"    Analyzed: [dim]{branch['analyzed_at']}[/dim]\n"
        lines.append(line)
    return "\n".join(lines)


def format_branch_details(branch: dict[str, Any]) -> str:
    """Format detailed branch analysis."""
    details = []

    details.append(
        f"Root Checkpoint: [dim]{branch['root_checkpoint_id']}[/dim] (iteration {branch['iteration'] - 1})"
    )
    details.append(
        f"Failure Checkpoint: [dim]{branch['failure_checkpoint_id']}[/dim] (iteration {branch['iteration']})"
    )

    if branch.get("execution_path"):
        details.append(f"Execution Path: [dim]{' → '.join(branch['execution_path'])}[/dim]")

    if branch.get("failure_insights"):
        insights = branch["failure_insights"]
        details.append("\n[bold]Failure Insights:[/bold]")
        if insights.get("root_cause"):
            details.append(f"  - Root cause: [yellow]{insights['root_cause']}[/yellow]")
        if insights.get("context"):
            details.append(f"  - Context: [dim]{insights['context']}[/dim]")

    if branch.get("avoid_patterns"):
        details.append("\n[bold]Avoid Patterns:[/bold]")
        for pattern in branch["avoid_patterns"]:
            details.append(f"  - [red]{pattern}[/red]")

    if branch.get("suggested_adjustments"):
        details.append("\n[bold]Suggested Adjustments:[/bold]")
        for adjustment in branch["suggested_adjustments"]:
            details.append(f"  - [green]{adjustment}[/green]")

    return "\n".join(details)


def format_anchor_summary(anchors: list[dict[str, Any]]) -> str:
    """Format checkpoint anchors summary."""
    lines = []
    for anchor in anchors:
        line = f"  iteration {anchor['iteration']}: [dim]{anchor['checkpoint_id']}[/dim] "
        line += f"({anchor['anchor_type']})"

        # Context refresh when loop scope (LangGraph thread_id) changes between anchors
        if anchor["iteration"] > 0:
            prev_anchors = [a for a in anchors if a["iteration"] == anchor["iteration"] - 1]
            if prev_anchors and prev_anchors[0]["thread_id"] != anchor["thread_id"]:
                line += " [cyan][context refreshed][/cyan]"

        lines.append(line)
    return "\n".join(lines)


def render_ascii_tree(tree: dict[str, Any]) -> None:
    """Render ASCII tree visualization."""
    console.print("\n[bold cyan]Main Execution Line:[/bold cyan]")

    main_line = tree.get("main_line", [])
    for iteration in main_line:
        iter_num = iteration["iteration"]

        # Iteration marker (IDs omitted in UI)
        console.print(f"  iteration {iter_num}")

        # Context refresh when the tree marks a switch
        if iteration.get("thread_switch"):
            console.print("    [cyan][context refreshed][/cyan]")

        if iteration.get("start_checkpoint"):
            console.print(f"    ├─ [dim]{iteration['start_checkpoint']}[/dim] [start]")

        # Tools executed (if available)
        if iteration.get("tools_executed"):
            for tool in iteration["tools_executed"]:
                console.print(f"    ├─ Tool: [green]{tool}[/green]")

        if iteration.get("end_checkpoint"):
            console.print(f"    └─ [dim]{iteration['end_checkpoint']}[/dim] [end] ✓")

    branches = tree.get("failed_branches", [])
    if branches:
        console.print("\n[bold red]Failed Branches:[/bold red]")

        for branch in branches:
            # Branch identity only (no per-anchor checkpoint id in UI)
            console.print(f"  [dim]{branch['branch_id']}[/dim] (iteration {branch['iteration']})")
            console.print(f"    ├─ [dim]{branch['root_checkpoint']}[/dim] [root] ← Rewind point")

            if branch.get("execution_path") and len(branch["execution_path"]) > 2:
                for checkpoint in branch["execution_path"][1:-1]:
                    console.print(f"    ├─ [dim]{checkpoint}[/dim]")

            console.print(f"    └─ [dim]{branch['failure_checkpoint']}[/dim] [failure]FAILED")


def render_dot_tree(tree: dict[str, Any]) -> None:
    """Render DOT (Graphviz) tree visualization."""
    dot_content = ["digraph checkpoint_tree {", "  rankdir=TB;"]

    # Main execution line
    dot_content.append("  subgraph main_line {")

    main_line = tree.get("main_line", [])
    for iteration in main_line:
        iter_num = iteration["iteration"]
        start_node = f"iter{iter_num}_start"
        end_node = f"iter{iter_num}_end"

        dot_content.append(f'    {start_node} [label="iteration {iter_num}\\nstart" shape=box];')
        dot_content.append(
            f'    {end_node} [label="iteration {iter_num}\\nend ✓" shape=box style=filled fillcolor=lightgreen];'
        )
        dot_content.append(f"    {start_node} -> {end_node};")

        if iter_num > 0:
            prev_end_node = f"iter{iter_num - 1}_end"
            dot_content.append(f"    {prev_end_node} -> {start_node};")

    dot_content.append("  }")

    # Failed branches
    branches = tree.get("failed_branches", [])
    if branches:
        dot_content.append("  subgraph failed_branches {")

        for branch in branches:
            branch_node = f"branch_{branch['branch_id'].replace('branch_', '')}"
            dot_content.append(
                f'    {branch_node}_root [label="{branch["branch_id"]}\\nroot" shape=diamond style=filled fillcolor=red];'
            )
            dot_content.append(
                f'    {branch_node}_failure [label="FAILURE\\n{branch["failure_reason"]}" shape=diamond style=filled fillcolor=red];'
            )
            dot_content.append(f"    {branch_node}_root -> {branch_node}_failure;")

        dot_content.append("  }")

    # Connections
    if branches:
        for branch in branches:
            iter_num = branch["iteration"] - 1
            root_node = f"branch_{branch['branch_id'].replace('branch_', '')}_root"
            dot_content.append(
                f'  iter{iter_num}_end -> {root_node} [style=dashed label="failure"];'
            )

    dot_content.append("}")

    console.print("\n[bold]DOT Format (Graphviz):[/bold]")
    console.print("[dim]" + "\n".join(dot_content) + "[/dim]")
    console.print("\n[cyan]To render: save to file and run `dot -Tpng tree.dot -o tree.png`[/cyan]")


@loop_app.command("continue")
def continue_loop(
    loop_id: Annotated[str | None, typer.Argument(help="Loop identifier to continue.")] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Optional prompt to send after continuing."),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Resume from the daemon's last execution step index.",
        ),
    ] = False,
) -> None:
    """Continue execution on an existing loop.

    Behavior:
    - Resolve target loop (explicit `LOOP_ID` or most-recent loop)
    - When resuming, fetch execution state (iteration/step/status) from daemon
    - Launch TUI on that loop
    - Optionally submit initial prompt in the resumed session

    Example:
        soothe loop continue
        soothe loop continue loop_abc123
        soothe loop continue loop_abc123 --prompt "translate to chinese"
        soothe loop continue loop_abc123 --resume
    """
    config = load_config()
    ws_url = websocket_url_from_config(config)
    _require_daemon(ws_url)
    resolved_loop_id = _resolve_continue_loop_id(ws_url, loop_id)

    # Show explicit message when user specified a loop_id
    if loop_id:
        console.print(f"[info]Continuing loop: {resolved_loop_id}[/info]")

    # Fetch execution state to show where the loop will pick up.
    # Best-effort: non-fatal if the daemon cannot answer (older daemon, etc.)
    if resume:
        try:
            state = asyncio.run(
                protocol1_rpc(
                    ws_url,
                    "loop_execution_state_fetch",
                    {"loop_id": resolved_loop_id},
                )
            )
            if "error" not in state:
                step_index = state.get("step_index", 0)
                iteration = state.get("iteration", 0)
                status = state.get("status", "unknown")
                plan = state.get("plan")
                console.print(
                    f"[info]Resuming from iteration {iteration}, "
                    f"step {step_index} ({status})[/info]"
                )
                if plan:
                    console.print(f"[dim]  Plan: {plan}[/dim]")
        except Exception:
            logger.warning("Failed to fetch execution state for loop %s", resolved_loop_id[:16])

    from soothe_cli.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        resume_loop_id=resolved_loop_id,
        no_tui=False,
        autonomous=False,
        max_iterations=None,
    )


@loop_app.command("resume")
def resume_loop(
    loop_id: Annotated[str | None, typer.Argument(help="Loop identifier to continue.")] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Optional prompt to send after continuing."),
    ] = None,
) -> None:
    """Alias for continue --resume — resume from the daemon's last step index."""
    continue_loop(loop_id, prompt, resume=True)


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
            f"Goals: {loop.get('total_goals_completed', 0)} completed\n"
            f"Internal contexts: {len(loop.get('thread_ids', []))}",
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
    "visualize_loop_tree",
    "prune_loop_branches",
    "delete_loop",
    "continue_loop",
    "resume_loop",
    "detach_loop",
    "attach_loop",
    "new_loop",
]
