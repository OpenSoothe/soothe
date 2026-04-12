"""Slash command handlers for daemon and TUI (Rich console output).

Daemon broadcasts ``command_response`` events; the TUI may also call these
helpers directly. No dependency on ``soothe.ux``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

from soothe.plan.rich_tree import render_plan_tree
from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from rich.console import Console

    from soothe.core.runner import SootheRunner
    from soothe.logging import GlobalInputHistory, ThreadLogger
    from soothe.protocols.planner import Plan

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


async def handle_slash_command(
    cmd: str,
    runner: SootheRunner,
    console: Console,
    *,
    current_plan: Plan | None = None,
    thread_logger: ThreadLogger | None = None,
    input_history: GlobalInputHistory | None = None,
) -> bool:
    """Handle a slash command."""
    parts = cmd.strip().split(maxsplit=2)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command in ("/exit", "/quit"):
        console.print("[dim]Stopping thread and exiting TUI. Daemon keeps running.[/dim]")
        return False

    if command == "/help":
        _show_help(console)
        return False

    if command == "/keymaps":
        _show_keymaps(console)
        return False

    if command == "/plan":
        _show_plan(console, current_plan)
        return False

    if command == "/memory":
        await _show_memory(console, runner)
        return False

    if command == "/context":
        console.print("[dim]Context protocol removed. Use /memory for knowledge management.[/dim]")
        return False

    if command == "/policy":
        _show_policy(console, runner)
        return False

    if command == "/history":
        _show_input_history(console, input_history)
        return False

    if command == "/review":
        _show_review(console, thread_logger, arg)
        return False

    if command == "/resume":
        return False

    if command == "/config":
        _show_config(console, runner)
        return False

    if command == "/clear":
        return False

    if command == "/cancel":
        return False

    if command == "/thread":
        await _handle_thread_command(console, runner, arg, parts)
        return False

    console.print(f"[yellow]Unknown command: {command}. Type /help for help.[/yellow]")
    return False


def _show_help(console: Console) -> None:
    table = Table(title="Slash Commands", show_lines=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    for k, v in SLASH_COMMANDS.items():
        table.add_row(k, v)
    console.print(table)


def _show_keymaps(console: Console) -> None:
    table = Table(title="Keyboard Shortcuts", show_lines=False)
    table.add_column("Shortcut", style="bold cyan")
    table.add_column("Action")
    for k, v in KEYBOARD_SHORTCUTS.items():
        table.add_row(k, v)
    console.print(table)


def _show_plan(console: Console, plan: Plan | None) -> None:
    if not plan:
        console.print("[dim]No active plan.[/dim]")
        return
    console.print(render_plan_tree(plan))


async def _show_memory(console: Console, runner: SootheRunner) -> None:
    try:
        stats = await runner.memory_stats()
        console.print(
            Panel(
                json.dumps(stats, indent=2, default=str),
                title="Memory Stats",
                border_style="cyan",
            )
        )
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Memory stats error")
        from soothe.utils.error_format import format_cli_error

        console.print(f"[red]{format_cli_error(exc, context='Memory stats')}[/red]")


def _show_policy(console: Console, runner: SootheRunner) -> None:
    console.print(f"[dim]Policy profile: {runner.config.protocols.policy.profile}[/dim]")
    console.print(f"[dim]Planner routing: {runner.config.protocols.planner.routing}[/dim]")
    console.print(f"[dim]Memory backend: {runner.config.protocols.memory.backend}[/dim]")


def _show_input_history(console: Console, history: Any | None) -> None:
    """Show recent input history from GlobalInputHistory.

    Args:
        console: Rich console for output.
        history: GlobalInputHistory instance or None.
    """
    if not history:
        console.print("[dim]No prompt history yet.[/dim]")
        return

    recent_entries = history.get_recent(limit=10)
    if not recent_entries:
        console.print("[dim]No prompt history yet.[/dim]")
        return

    table = Table(title="Recent Prompts", show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Prompt", style="cyan")
    # Get full entries for indexing
    full_entries = history.get_entries(limit=10)
    start_idx = max(len(history.get_entries(limit=0)) - 9, 1) if full_entries else 1
    for idx, entry in enumerate(full_entries, start=start_idx):
        table.add_row(str(idx), entry.get("text", ""))
    console.print(table)


def _show_review(console: Console, thread_logger: ThreadLogger | None, scope: str) -> None:
    if not thread_logger:
        console.print("[dim]No thread logger active.[/dim]")
        return

    normalized = (scope or "all").lower()
    if normalized not in {"all", "conversation", "actions"}:
        console.print("[yellow]Usage: /review [conversation|actions][/yellow]")
        return

    if normalized in {"all", "conversation"}:
        conversation = thread_logger.recent_conversation()
        if conversation:
            table = Table(title="Recent Conversation", show_lines=False)
            table.add_column("Role", style="bold cyan")
            table.add_column("Text")
            for record in conversation:
                role = str(record.get("role", "unknown")).title()
                text = str(record.get("text", "")).strip()
                table.add_row(role, text)
            console.print(table)
        else:
            console.print("[dim]No conversation records in this thread yet.[/dim]")

    if normalized in {"all", "actions"}:
        actions = thread_logger.recent_actions()
        if actions:
            table = Table(title="Recent Actions", show_lines=False)
            table.add_column("Source", style="magenta")
            table.add_column("Event", style="cyan")
            table.add_column("Summary")
            for record in actions:
                namespace = record.get("namespace", [])
                source = ":".join(namespace) if isinstance(namespace, list) and namespace else "main"
                data = record.get("data", {})
                event_type = data.get("type", "?") if isinstance(data, dict) else "?"
                summary = (
                    (
                        data.get("assessment")
                        or data.get("reason")
                        or data.get("content_preview")
                        or data.get("query")
                        or data.get("thread_id")
                        or ""
                    )
                    if isinstance(data, dict)
                    else ""
                )
                table.add_row(source, event_type, preview_first(str(summary), 100))
            console.print(table)
        elif normalized == "actions":
            console.print("[dim]No action records in this thread yet.[/dim]")


def _show_config(console: Console, runner: SootheRunner) -> None:
    cfg = runner.config
    lines = [
        f"Model (default): {cfg.resolve_model('default')}",
        f"Planner routing: {cfg.protocols.planner.routing}",
        f"Context backend: {cfg.protocols.context.backend}",
        f"Memory provider: {cfg.protocols.memory.database_provider}",
        f"Policy profile: {cfg.protocols.policy.profile}",
    ]
    enabled = [n for n, s in cfg.subagents.items() if s.enabled]
    lines.append(f"Subagents: {', '.join(enabled) if enabled else '(none)'}")
    if cfg.tools:
        lines.append(f"Tools: {', '.join(cfg.tools)}")
    console.print(Panel("\n".join(lines), title="Soothe Config", border_style="cyan"))


async def _handle_thread_command(console: Console, runner: SootheRunner, subcommand: str, parts: list[str]) -> None:
    if not subcommand:
        console.print("[yellow]Usage: /thread <command> [args][/yellow]")
        console.print("[dim]Commands: list, archive <thread_id>[/dim]")
        return

    if subcommand == "list":
        from soothe.core.thread import ThreadContextManager

        try:
            manager = ThreadContextManager(runner._durability, runner._config)
            threads = await manager.list_threads(include_last_message=True)
            if not threads:
                console.print("[dim]No threads.[/dim]")
                return

            threads.sort(key=lambda x: x.updated_at, reverse=True)

            table = Table(title="Threads", show_lines=False)
            table.add_column("ID", style="dim", no_wrap=True, min_width=12, max_width=20)
            table.add_column("Status")
            table.add_column("Created")
            table.add_column("Last Message")
            table.add_column("Topic")

            for t in threads:
                tid = (
                    t.thread_id
                    if len(t.thread_id) <= _THREAD_ID_DISPLAY_WIDTH
                    else t.thread_id[:_THREAD_ID_TRUNCATE_KEEP] + "..."
                )
                created = preview_first(str(t.created_at), 19)
                last_msg = preview_first(str(t.updated_at), 19)
                topic = (
                    (t.last_human_message or "")[:_TOPIC_TRUNCATE_KEEP] + "..."
                    if t.last_human_message and len(t.last_human_message) > _TOPIC_DISPLAY_LIMIT
                    else (t.last_human_message or "")
                )
                table.add_row(tid, t.status, created, last_msg, topic)

            console.print(table)
        except Exception as exc:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Thread list error")
            from soothe.utils.error_format import format_cli_error

            console.print(f"[red]{format_cli_error(exc, context='Thread list')}[/red]")
    elif subcommand == "archive":
        if len(parts) < _THREAD_ARCHIVE_MIN_PARTS:
            console.print("[yellow]Usage: /thread archive <thread_id>[/yellow]")
            return

        thread_id = parts[2].strip()
        if not thread_id:
            console.print("[yellow]Usage: /thread archive <thread_id>[/yellow]")
            return

        try:
            if hasattr(runner, "_config"):
                from soothe.core.thread import ThreadContextManager

                manager = ThreadContextManager(
                    runner._durability,
                    runner._config,
                    getattr(runner, "_context", None),
                )
                await manager.archive_thread(thread_id)
            else:
                await runner._durability.archive_thread(thread_id)
            console.print(f"[green]Archived thread {thread_id}[/green]")
        except Exception as exc:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Thread archive error")
            from soothe.utils.error_format import format_cli_error

            console.print(f"[red]{format_cli_error(exc, context='Thread archive')}[/red]")
    else:
        console.print(f"[yellow]Unknown /thread subcommand: {subcommand}[/yellow]")
        console.print("[dim]Commands: list, archive <thread_id>[/dim]")


__all__ = [
    "KEYBOARD_SHORTCUTS",
    "SLASH_COMMANDS",
    "handle_slash_command",
    "parse_autonomous_command",
]
