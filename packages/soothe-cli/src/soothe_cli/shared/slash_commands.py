"""Slash command handlers for CLI and TUI (RFC-404).

Unified command registry with metadata-based routing:
- CLI-only commands: handled locally
- Daemon RPC commands: structured data rendering
- Daemon routing commands: behavior indicators

This module provides the COMMANDS registry and rendering functions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

# ---------------------------------------------------------------------------
# Rendering Functions (must be defined before COMMANDS registry)
# ---------------------------------------------------------------------------


def show_commands(console: Console) -> None:
    """Show available slash commands (CLI-only)."""
    table = Table(title="Available Commands", show_lines=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")

    # Import COMMANDS here to avoid circular reference at module load
    from soothe_cli.shared.slash_commands import COMMANDS

    for cmd, entry in COMMANDS.items():
        table.add_row(cmd, entry.get("description", ""))

    console.print(table)


def show_keymaps(console: Console) -> None:
    """Show keyboard shortcuts (CLI-only)."""
    table = Table(title="Keyboard Shortcuts", show_lines=False)
    table.add_column("Shortcut", style="bold cyan")
    table.add_column("Action")

    for k, v in KEYBOARD_SHORTCUTS.items():
        table.add_row(k, v)

    console.print(table)


def show_memory(console: Console, data: dict[str, Any]) -> None:
    """Render memory stats from daemon RPC response."""
    stats = data.get("memory_stats", {})
    console.print(
        Panel(
            json.dumps(stats, indent=2, default=str),
            title="Memory Stats",
            border_style="cyan",
        )
    )


def show_policy(console: Console, data: dict[str, Any]) -> None:
    """Render policy profile from daemon RPC response."""
    policy = data.get("policy", {})
    console.print(f"[dim]Policy profile: {policy.get('profile', 'unknown')}[/dim]")
    console.print(f"[dim]Planner routing: {policy.get('planner_routing', 'unknown')}[/dim]")
    console.print(f"[dim]Memory backend: {policy.get('memory_backend', 'unknown')}[/dim]")


def show_history(console: Console, data: dict[str, Any]) -> None:
    """Render input history from daemon RPC response."""
    history = data.get("history", [])
    if not history:
        console.print("[dim]No recent history.[/dim]")
        return

    table = Table(title="Recent Input History", show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Input", style="cyan")

    for item in history[:10]:  # Show last 10
        timestamp = item.get("timestamp", "")
        text = item.get("text", "")
        if len(text) > 50:
            text = text[:47] + "..."
        table.add_row(timestamp, text)

    console.print(table)


def show_config(console: Console, data: dict[str, Any]) -> None:
    """Render configuration summary from daemon RPC response."""
    config = data.get("config", {})
    console.print(
        Panel(
            json.dumps(config, indent=2, default=str),
            title="Configuration Summary",
            border_style="cyan",
        )
    )


def show_review(console: Console, data: dict[str, Any]) -> None:
    """Render conversation/action history from daemon RPC response."""
    history = data.get("review", [])
    if not history:
        console.print("[dim]No conversation history.[/dim]")
        return

    table = Table(title="Conversation Review", show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Content", style="white")

    for item in history[:20]:
        timestamp = item.get("timestamp", "")
        item_type = item.get("type", "unknown")
        content = item.get("content", "")
        if len(content) > 60:
            content = content[:57] + "..."
        table.add_row(timestamp, item_type, content)

    console.print(table)


def show_autopilot_dashboard(console: Console, data: dict[str, Any]) -> None:
    """Render autopilot dashboard from daemon RPC response."""
    dashboard = data.get("autopilot_dashboard", {})

    table = Table(title="Autopilot Dashboard", show_lines=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")

    # Display key metrics
    table.add_row("Status", dashboard.get("status", "idle"))
    table.add_row("Iterations", str(dashboard.get("iterations", 0)))
    table.add_row("Goals Completed", str(dashboard.get("goals_completed", 0)))
    table.add_row("Goals Active", str(dashboard.get("goals_active", 0)))

    console.print(table)

    # Display active goals if present
    active_goals = dashboard.get("active_goals", [])
    if active_goals:
        console.print("\n[bold cyan]Active Goals:[/bold cyan]")
        for goal in active_goals:
            console.print(f"  • {goal.get('description', 'unknown')}")


# ---------------------------------------------------------------------------
# Keyboard Shortcuts
# ---------------------------------------------------------------------------

KEYBOARD_SHORTCUTS: dict[str, str] = {
    "Ctrl+Q": "Quit TUI: Stop thread (confirm) and exit client",
    "Ctrl+D": "Detach TUI: Leave thread running (confirm) and exit client",
    "Ctrl+C": "Cancel running job, press twice within 1s to quit",
    "Ctrl+E": "Focus chat input",
    "Ctrl+Y": "Copy last message to clipboard",
}


# ---------------------------------------------------------------------------
# Unified Command Registry (RFC-404)
# ---------------------------------------------------------------------------

COMMANDS: dict[str, dict[str, Any]] = {
    # CLI-only commands (2)
    "/help": {
        "location": "cli",
        "handler": show_commands,
        "description": "Show available commands",
    },
    "/keymaps": {
        "location": "cli",
        "handler": show_keymaps,
        "description": "Show keyboard shortcuts",
    },
    # Daemon RPC commands (12)
    "/clear": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "clear",
        "description": "Clear thread history",
        "requires_thread": True,
    },
    "/exit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "exit",
        "description": "Stop thread and exit client",
    },
    "/quit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "quit",
        "description": "Stop thread and exit client",
    },
    "/detach": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "detach",
        "description": "Leave thread running and exit client",
    },
    "/cancel": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "cancel",
        "description": "Cancel the current running job",
        "requires_thread": True,
    },
    "/memory": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "memory",
        "description": "Show memory stats",
        "requires_thread": True,
        "handler": show_memory,
    },
    "/policy": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "policy",
        "description": "Show active policy profile",
        "handler": show_policy,
    },
    "/history": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "history",
        "description": "Show recent prompt history",
        "requires_thread": True,
        "handler": show_history,
    },
    "/config": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "config",
        "description": "Show active configuration summary",
        "handler": show_config,
    },
    "/review": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "review",
        "description": "Review recent conversation and action history",
        "requires_thread": True,
        "handler": show_review,
    },
    "/thread": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "thread",
        "description": "Thread operations (archive <id>)",
        "params_schema": {
            "action": {"type": "string", "required": True},
            "id": {"type": "string", "required": False},
        },
    },
    "/resume": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "resume",
        "description": "Resume a recent thread",
        "params_schema": {"thread_id": {"type": "string", "required": True}},
    },
    "/autopilot": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "autopilot_dashboard",
        "description": "Show autopilot dashboard",
        "requires_thread": True,
        "handler": show_autopilot_dashboard,
    },
    # Daemon routing commands (5)
    "/plan": {"location": "daemon", "type": "routing", "description": "Trigger plan mode"},
    "/browser": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Browser subagent",
        "requires_query": True,
    },
    "/claude": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Claude subagent",
        "requires_query": True,
    },
    "/research": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Research subagent",
        "requires_query": True,
    },
    "/explore": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Explore subagent",
        "requires_query": True,
    },
}


# Legacy compatibility (used by tests/old code)
SLASH_COMMANDS: dict[str, str] = {
    cmd: entry.get("description", "") for cmd, entry in COMMANDS.items()
}


# ---------------------------------------------------------------------------
# Legacy helper (used by tests/old code)
# ---------------------------------------------------------------------------


def parse_autonomous_command(cmd: str) -> tuple[int | None, str] | None:
    """Parse `/autopilot` command payload (legacy helper)."""
    stripped = cmd.strip()
    if not stripped.startswith("/autopilot"):
        return None

    parts = stripped.split(maxsplit=2)
    if len(parts) == 1:
        return None

    if len(parts) == 2:
        single = parts[1].strip()
        if not single or single.isdigit():
            return None
        return (None, single)

    maybe_num = parts[1].strip()
    if maybe_num.isdigit():
        prompt = parts[2].strip()
        if not prompt:
            return None
        max_iterations = int(maybe_num)
        return (max_iterations if max_iterations > 0 else None, prompt)

    prompt = f"{parts[1]} {parts[2]}".strip()
    return (None, prompt) if prompt else None


__all__ = [
    "COMMANDS",
    "SLASH_COMMANDS",
    "KEYBOARD_SHORTCUTS",
    "parse_autonomous_command",
    "show_commands",
    "show_keymaps",
    "show_memory",
    "show_policy",
    "show_history",
    "show_config",
    "show_review",
    "show_autopilot_dashboard",
]
