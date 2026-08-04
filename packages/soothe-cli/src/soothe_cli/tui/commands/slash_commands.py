"""Slash command handlers for CLI and TUI (RFC-454).

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
    from soothe_cli.tui.commands.slash_commands import COMMANDS

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


def show_cron_add(console: Console, data: dict[str, Any]) -> None:
    """Render cron job creation response from daemon RPC (RFC-229)."""
    job = data.get("cron_add", {})
    if not job:
        console.print("[dim]No job created.[/dim]")
        return

    console.print(
        Panel(
            f"[cyan]Job ID:[/] {job.get('id', 'N/A')}\n"
            f"[cyan]Description:[/] {job.get('description', 'N/A')}\n"
            f"[cyan]Schedule:[/] {job.get('schedule_kind', 'N/A')} = {job.get('schedule_value', 'N/A')}\n"
            f"[cyan]Next Run:[/] {job.get('next_run', 'N/A')}\n"
            f"[cyan]Status:[/] {job.get('status', 'N/A')}\n"
            f"[cyan]Priority:[/] {job.get('priority', 50)}",
            title="Cron Job Created",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# Keyboard Shortcuts
# ---------------------------------------------------------------------------

KEYBOARD_SHORTCUTS: dict[str, str] = {
    "Esc": "Dismiss modal, plan overlay, or autocomplete",
    "Ctrl+D": "Type exit, quit, or /quit to exit the TUI",
    "Ctrl+C": "Clear input or interrupt running agent/shell",
    "Ctrl+X": "Open prompt in external editor ($VISUAL/$EDITOR)",
    "Ctrl+Y": "Copy selected text to clipboard (or show hint if none)",
    "Ctrl+V": "Paste image from clipboard as [image N] attachment",
    "Ctrl+T": "Toggle plan panel above thinking row",
    "Ctrl+O": "Toggle expand/collapse of the most recent skill or tool card",
    "Shift+Tab": "Cycle composer mode (Auto → Manual → Plan)",
}


# ---------------------------------------------------------------------------
# Unified Command Registry (RFC-454)
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
    # Daemon RPC commands (11)
    "/clear": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "clear",
        "description": "Clear conversation on the active loop",
        "requires_loop": True,
    },
    "/exit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "exit",
        "description": "Stop the loop and exit client",
    },
    "/quit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "quit",
        "description": "Stop the loop and exit client",
    },
    "/detach": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "detach",
        "description": "Leave the loop running and exit client",
    },
    "/cancel": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "cancel",
        "description": "Cancel the current running job",
        "requires_loop": True,
    },
    "/memory": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "memory",
        "description": "Show memory stats",
        "requires_loop": True,
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
        "requires_loop": True,
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
        "requires_loop": True,
        "handler": show_review,
    },
    "/resume": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "resume",
        "description": "Resume a loop by id",
        "params_schema": {"loop_id": {"type": "string", "required": True}},
    },
    "/autopilot": {
        "location": "daemon",
        "type": "routing",
        "description": "Submit autopilot job (usage: /autopilot <task>)",
        "requires_query": True,
    },
    "/cron": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "cron_add",
        "description": "Schedule a job via natural language (usage: /cron <schedule>)",
        "requires_query": True,
        "handler": show_cron_add,
    },
    # Daemon routing commands
    "/plan": {"location": "daemon", "type": "routing", "description": "Trigger plan mode"},
    "/deep_research": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Deep Research subagent",
        "requires_query": True,
    },
    "/academic_research": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Academic Research subagent",
        "requires_query": True,
    },
    "/browser_use": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Browser Use subagent",
        "requires_query": True,
    },
}


__all__ = [
    "COMMANDS",
    "KEYBOARD_SHORTCUTS",
    "show_commands",
    "show_keymaps",
    "show_memory",
    "show_policy",
    "show_history",
    "show_config",
    "show_review",
    "show_cron_add",
]
