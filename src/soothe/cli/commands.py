"""Slash commands, subagent routing, and display helpers for the Soothe TUI."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from soothe.cli.thread_logger import InputHistory, ThreadLogger
    from soothe.core.runner import SootheRunner
    from soothe.protocols.planner import Plan

# ---------------------------------------------------------------------------
# Subagent display names and routing
# ---------------------------------------------------------------------------

SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Planner",
    "scout": "Scout",
    "research": "Research",
    "browser": "Browser",
    "claude": "Claude",
    "skillify": "Skillify",
    "weaver": "Weaver",
}

BUILTIN_SUBAGENT_NAMES: list[str] = list(SUBAGENT_DISPLAY_NAMES.keys())

_FIRST_SUBAGENT_INDEX = 2


def get_subagent_display_name(technical_name: str) -> str:
    """Get display name for a subagent.

    Args:
        technical_name: Internal subagent name.

    Returns:
        PascalCase display name.
    """
    return SUBAGENT_DISPLAY_NAMES.get(
        technical_name,
        technical_name.replace("_", " ").title().replace(" ", ""),
    )


def parse_subagent_prefix_from_input(user_input: str) -> tuple[list[str], str]:
    """Parse leading numeric selector from input.

    .. deprecated::
        Numeric prefix routing is deprecated and not used in Soothe.
        The LLM naturally routes to appropriate subagents via the `task` tool.
        This function is retained for backward compatibility with external code
        but should not be used in new implementations.

    Numeric prefixes select subagents:
    ``1`` = Main, ``2`` = Planner, ``3`` = Scout, ``4`` = Research,
    ``5`` = Browser, ``6`` = Claude.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_names, message)``.  Empty list means main agent.

    Examples:
        ``"4 quantum papers"`` -> ``(["research"], "quantum papers")``
        ``"hello world"`` -> ``([], "hello world")``
    """
    tokens = user_input.strip().split()
    i = 0
    while i < len(tokens) and tokens[i].replace(",", "").strip().isdigit():
        i += 1
    if i == 0:
        return ([], user_input.strip())

    prefix_str = " ".join(tokens[:i])
    message = " ".join(tokens[i:]).strip()
    names: list[str] = []
    for token in prefix_str.replace(",", " ").split():
        cleaned = token.strip()
        if not cleaned.isdigit():
            continue
        idx = int(cleaned)
        if idx == 1:
            continue
        if _FIRST_SUBAGENT_INDEX <= idx <= len(BUILTIN_SUBAGENT_NAMES) + 1:
            name = BUILTIN_SUBAGENT_NAMES[idx - _FIRST_SUBAGENT_INDEX]
            if name not in names:
                names.append(name)
    return (names, message)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/exit": "Stop daemon and exit",
    "/quit": "Stop daemon and exit",
    "/detach": "Detach TUI; daemon keeps running (reconnect with 'soothe attach')",
    "/auto <prompt>": "Run prompt in autonomous mode",
    "/auto <max_iterations> <prompt>": "Run prompt in autonomous mode with iteration limit",
    "/plan": "Show current task plan",
    "/memory": "Show memory stats",
    "/context": "Show context stats",
    "/policy": "Show active policy profile",
    "/history": "Show recent prompt history",
    "/review": "Review recent conversation and action history",
    "/thread list": "List active threads",
    "/thread resume <id>": "Resume a thread",
    "/thread archive <id>": "Archive a thread",
    "/clear": "Clear the screen",
    "/config": "Show active configuration summary",
    "/help": "Show available commands",
}


_AUTO_MAX_SPLIT = 2
_AUTO_MIN_PARTS = 1
_AUTO_TWO_PARTS = 2


def parse_autonomous_command(cmd: str) -> tuple[int | None, str] | None:
    """Parse `/auto` command payload.

    Args:
        cmd: Raw slash command, e.g. ``/auto 20 Crawl all skills``.

    Returns:
        ``(max_iterations, prompt)`` for valid input, otherwise ``None``.
    """
    stripped = cmd.strip()
    if not stripped.startswith("/auto"):
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

    # `/auto <prompt...>` with first token non-numeric.
    prompt = f"{parts[1]} {parts[2]}".strip()
    return (None, prompt) if prompt else None


async def handle_slash_command(
    cmd: str,
    runner: SootheRunner,
    console: Console,
    *,
    current_plan: Plan | None = None,
    thread_logger: ThreadLogger | None = None,
    input_history: InputHistory | None = None,
) -> bool:
    """Handle a slash command.

    Args:
        cmd: The slash command string.
        runner: The SootheRunner instance.
        console: Rich console for output.
        current_plan: Current plan (if any).
        thread_logger: Active thread logger.
        input_history: Stored prompt history for `/history`.

    Returns:
        ``True`` if the TUI should exit.
    """
    parts = cmd.strip().split(maxsplit=2)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    arg2 = parts[2].strip() if len(parts) > _FIRST_SUBAGENT_INDEX else ""

    if command in ("/exit", "/quit"):
        console.print("[dim]Goodbye.[/dim]")
        return True

    if command == "/help":
        _show_help(console)
        return False

    if command == "/plan":
        _show_plan(console, current_plan)
        return False

    if command == "/memory":
        _show_memory(console, runner)
        return False

    if command == "/context":
        _show_context(console, runner)
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

    if command == "/thread":
        await _handle_thread_command(arg, arg2, console, runner)
        return False

    if command == "/config":
        _show_config(console, runner)
        return False

    if command == "/clear":
        console.clear()
        return False

    console.print(f"[yellow]Unknown command: {command}. Type /help for help.[/yellow]")
    return False


# ---------------------------------------------------------------------------
# Slash command helpers
# ---------------------------------------------------------------------------


def _show_help(console: Console) -> None:
    table = Table(title="Slash Commands", show_lines=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    for k, v in SLASH_COMMANDS.items():
        table.add_row(k, v)
    console.print(table)


def _show_plan(console: Console, plan: Plan | None) -> None:
    if not plan:
        console.print("[dim]No active plan.[/dim]")
        return
    from soothe.cli.tui_shared import render_plan_tree

    console.print(render_plan_tree(plan))


def _show_memory(console: Console, runner: SootheRunner) -> None:
    loop = asyncio.get_event_loop()
    try:
        stats = loop.run_until_complete(runner.memory_stats())
        console.print(
            Panel(
                json.dumps(stats, indent=2, default=str),
                title="Memory Stats",
                border_style="cyan",
            )
        )
    except Exception as exc:
        console.print(f"[red]Memory stats error: {exc}[/red]")


def _show_context(console: Console, runner: SootheRunner) -> None:
    loop = asyncio.get_event_loop()
    try:
        stats = loop.run_until_complete(runner.context_stats())
        console.print(
            Panel(
                json.dumps(stats, indent=2, default=str),
                title="Context Stats",
                border_style="cyan",
            )
        )
    except Exception as exc:
        console.print(f"[red]Context stats error: {exc}[/red]")


def _show_policy(console: Console, runner: SootheRunner) -> None:
    console.print(f"[dim]Policy profile: {runner.config.protocols.policy.profile}[/dim]")
    console.print(f"[dim]Planner routing: {runner.config.protocols.planner.routing}[/dim]")


def _show_input_history(console: Console, history: InputHistory | None) -> None:
    if not history or not history.history:
        console.print("[dim]No prompt history yet.[/dim]")
        return

    table = Table(title="Recent Prompts", show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Prompt", style="cyan")
    for idx, entry in enumerate(history.history[-10:], start=max(len(history.history) - 9, 1)):
        table.add_row(str(idx), entry)
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
                table.add_row(source, event_type, str(summary)[:100])
            console.print(table)
        elif normalized == "actions":
            console.print("[dim]No action records in this thread yet.[/dim]")


async def _handle_thread_command(
    sub_cmd: str,
    arg: str,
    console: Console,
    runner: SootheRunner,
) -> None:
    if sub_cmd == "list":
        try:
            threads = await runner.list_threads()
            if not threads:
                console.print("[dim]No threads.[/dim]")
                return
            table = Table(title="Threads", show_lines=False)
            table.add_column("ID", style="cyan")
            table.add_column("Status")
            table.add_column("Created")
            for t in threads:
                table.add_row(
                    t.get("thread_id", "?"),
                    t.get("status", "?"),
                    str(t.get("created_at", "?"))[:19],
                )
            console.print(table)
        except Exception as exc:
            console.print(f"[red]Thread list error: {exc}[/red]")
    elif sub_cmd == "resume" and arg:
        console.print(f"[dim]Resuming thread {arg}...[/dim]")
        runner.set_current_thread_id(arg)
    elif sub_cmd == "archive" and arg:
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(runner._durability.archive_thread(arg))
            console.print(f"[dim]Archived thread {arg}.[/dim]")
        except Exception as exc:
            console.print(f"[red]Archive error: {exc}[/red]")
    else:
        console.print("[yellow]Usage: /thread list | /thread resume <id> | /thread archive <id>[/yellow]")


def _show_config(console: Console, runner: SootheRunner) -> None:
    cfg = runner.config
    lines = [
        f"Model (default): {cfg.resolve_model('default')}",
        f"Planner routing: {cfg.planner_routing}",
        f"Context backend: {cfg.context_backend}",
        f"Memory backend: {cfg.memory_backend}",
        f"Policy profile: {cfg.policy_profile}",
    ]
    enabled = [n for n, s in cfg.subagents.items() if s.enabled]
    lines.append(f"Subagents: {', '.join(enabled) if enabled else '(none)'}")
    if cfg.tools:
        lines.append(f"Tools: {', '.join(cfg.tools)}")
    console.print(Panel("\n".join(lines), title="Soothe Config", border_style="cyan"))
