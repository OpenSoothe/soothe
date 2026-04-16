"""Slash command handlers for CLI and TUI (Rich console output).

This module handles slash commands locally in CLI/TUI, rendering structured
data from daemon events with Rich widgets.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

from soothe_cli.plan.rich_tree import render_plan_tree

if TYPE_CHECKING:
    from rich.console import Console
    from soothe_sdk.protocol_schemas import Plan

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/exit": "Stop running thread (confirm) and exit TUI; daemon keeps running (RFC-0013)",
    "/quit": "Stop running thread (confirm) and exit TUI; daemon keeps running (RFC-0013)",
    "/detach": "Leave thread running (confirm) and exit TUI; daemon keeps running (RFC-0013)",
    "/autopilot <prompt>": "Run prompt in autonomous mode",
    "/cancel": "Cancel the current running job",
    "/plan": "Show current task plan",
    "/memory": "Show memory stats",
    "/context": "Removed (use /memory instead)",
    "/policy": "Show active policy profile",
    "/history": "Show recent prompt history",
    "/review": "Review recent conversation and action history",
    "/resume": "Resume a recent thread (interactive selection)",
    "/thread": "Thread operations (archive <id>)",
    "/clear": "Clear the screen",
    "/config": "Show active configuration summary",
    "/keymaps": "Show keyboard shortcuts",
    "/help": "Show available commands",
    "/browser <query>": "Route query to Browser subagent",
    "/claude <query>": "Route query to Claude subagent",
    "/research <query>": "Route query to Research subagent",
}

KEYBOARD_SHORTCUTS: dict[str, str] = {
    "Ctrl+Q": "Quit TUI: Stop thread (confirm) and exit client",
    "Ctrl+D": "Detach TUI: Leave thread running (confirm) and exit client",
    "Ctrl+C": "Cancel running job, press twice within 1s to quit",
    "Ctrl+E": "Focus chat input",
    "Ctrl+Y": "Copy last message to clipboard",
}


_AUTO_MAX_SPLIT = 2
_AUTO_MIN_PARTS = 1
_AUTO_TWO_PARTS = 2
_THREAD_ARCHIVE_MIN_PARTS = 3

_TOPIC_DISPLAY_LIMIT = 30
_TOPIC_TRUNCATE_KEEP = 27
_THREAD_ID_DISPLAY_WIDTH = 20
_THREAD_ID_TRUNCATE_KEEP = 17


def parse_autonomous_command(cmd: str) -> tuple[int | None, str] | None:
    """Parse `/autopilot` command payload."""
    stripped = cmd.strip()
    if not stripped.startswith("/autopilot"):
        return None

    parts = stripped.split(maxsplit=_AUTO_MAX_SPLIT)
    if len(parts) == _AUTO_MIN_PARTS:
        return None

    if len(parts) == _AUTO_TWO_PARTS:
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


def show_commands(console: Console) -> None:
    """Show available slash commands."""
    table = Table(title="Available Commands", show_lines=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    for cmd, desc in SLASH_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


def show_keymaps(console: Console) -> None:
    """Show keyboard shortcuts."""
    table = Table(title="Keyboard Shortcuts", show_lines=False)
    table.add_column("Shortcut", style="bold cyan")
    table.add_column("Action")
    for k, v in KEYBOARD_SHORTCUTS.items():
        table.add_row(k, v)
    console.print(table)


def show_plan(console: Console, plan: Plan | None) -> None:
    """Render plan data with Rich Tree."""
    if not plan:
        console.print("[dim]No active plan.[/dim]")
        return
    console.print(render_plan_tree(plan))


def show_memory(console: Console, stats: dict[str, Any]) -> None:
    """Render memory stats with Rich Panel."""
    console.print(
        Panel(
            json.dumps(stats, indent=2, default=str),
            title="Memory Stats",
            border_style="cyan",
        )
    )


def show_policy(console: Console, policy_data: dict[str, Any]) -> None:
    """Render policy profile."""
    console.print(f"[dim]Policy profile: {policy_data.get('profile', 'unknown')}[/dim]")
    console.print(f"[dim]Planner routing: {policy_data.get('planner_routing', 'unknown')}[/dim]")
    console.print(f"[dim]Memory backend: {policy_data.get('memory_backend', 'unknown')}[/dim]")


def show_history(console: Console, history_data: list[dict[str, Any]]) -> None:
    """Render input history."""
    if not history_data:
        console.print("[dim]No recent history.[/dim]")
        return

    table = Table(title="Recent Input History", show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Input", style="cyan")

    for item in history_data[:10]:  # Show last 10
        timestamp = item.get("timestamp", "")
        text = item.get("text", "")
        if len(text) > 50:
            text = text[:47] + "..."
        table.add_row(timestamp, text)

    console.print(table)


def show_config(console: Console, config_data: dict[str, Any]) -> None:
    """Render configuration summary."""
    console.print(
        Panel(
            json.dumps(config_data, indent=2, default=str),
            title="Configuration Summary",
            border_style="cyan",
        )
    )


__all__ = [
    "SLASH_COMMANDS",
    "KEYBOARD_SHORTCUTS",
    "parse_autonomous_command",
    "show_commands",
    "show_keymaps",
    "show_plan",
    "show_memory",
    "show_policy",
    "show_history",
    "show_config",
]
