"""Autopilot CLI subcommands for RFC-204.

Daemon-backed control surface: submit tasks and manage goals via WebSocket.
Requires ``soothed start``. Live forest dashboard: ``soothe autopilot top``.
"""

from __future__ import annotations

import asyncio
import os
import select
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.text import Text
from soothe_client import (
    command_client_from_config,
    is_daemon_live,
    websocket_url_from_config,
)
from soothe_sdk.wire.protocol import preview_first

_TOP_INTERVAL_MIN = 0.2
_TOP_INTERVAL_MAX = 10.0
_TOP_HELP_LINES = (
    "Keys:",
    "  q Quit          h/? Help          Space Refresh",
    "  a All/active    s Steps           l Loops       d Density",
    "  +/- Delay       j/k/^E/^Y line    ^D/^U half    ^F/^B page",
    "  g/G or Home/End Top/bottom        PgUp/PgDn page",
    "",
    "mode=active hides completed/failed/cancelled goals;",
    "steps=on lists the StepDAG under remaining live goals.",
    "mode=all shows the full forest including terminal goals.",
)

# Concept colors for autopilot top (jobs / goals / steps / loops).
_STYLE_JOB = "bold bright_cyan"
_STYLE_GOAL = "bold bright_white"
_STYLE_STEP = "yellow"
_STYLE_LOOP = "bold bright_magenta"
_STYLE_TREE = "bright_black"
_STYLE_META = "cyan"
_STYLE_HEADER = "bold"
_STYLE_DIM = "dim"
_STATUS_STYLE: dict[str, str] = {
    "active": "bold bright_green",
    "pending": "yellow",
    "completed": "dim green",
    "failed": "bold bright_red",
    "cancelled": "dim red",
    "suspended": "bright_yellow",
    "blocked": "bright_yellow",
    "awaiting_clarification": "bright_yellow",
    "skipped": "dim",
    "running": "bold bright_green",
    "stopped": "dim red",
}

app = typer.Typer(help="Autopilot — autonomous goal control.")

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "suspended"})
_WAIT_TIMEOUT_S = 600.0


def _preview_desc(text: object, max_chars: int) -> str:
    """Collapse whitespace/newlines and truncate for a single-line preview."""
    raw = text if isinstance(text, str) else str(text or "")
    compact = " ".join(raw.split())
    return preview_first(compact, max_chars)


def _resolve_submit_workspace(explicit: str | None) -> str:
    """Resolve workspace for autopilot submit (IG-344 aligned with headless/TUI)."""
    raw = (
        explicit.strip()
        if explicit and explicit.strip()
        else os.environ.get("SOOTHE_CLI_WORKSPACE", "").strip() or os.getcwd()
    )
    return str(Path(raw).expanduser().resolve())


def _require_daemon_ws():
    """Return a live WebSocket command client or exit."""
    from soothe_cli.runtime import load_config

    cfg = load_config()
    ws_url = websocket_url_from_config(cfg)
    if not asyncio.run(is_daemon_live(ws_url, timeout=5.0)):
        typer.echo(
            "Error: Daemon not running. Start with 'soothed start'.",
            err=True,
        )
        sys.exit(1)
    return command_client_from_config(cfg)


def _wait_for_goal(client: Any, goal_id: str, *, timeout_s: float = _WAIT_TIMEOUT_S) -> None:
    """Poll until the goal reaches a terminal status or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        detail = client.autopilot_get_goal(goal_id)
        goal = detail.get("goal") or {}
        status = goal.get("status", "unknown")
        if status in _TERMINAL_STATUSES:
            typer.echo(f"Goal {goal_id[:8]}: {status}")
            if status == "failed":
                sys.exit(1)
            return
        time.sleep(1.0)
    typer.echo(f"Timed out waiting for goal {goal_id}", err=True)
    sys.exit(1)


def _resolve_submit_task(task: str | None, file: str | None) -> str:
    """Resolve task text from an inline argument or ``--file``.

    Args:
        task: Optional inline task description.
        file: Optional path to a UTF-8 file (or ``-`` for stdin).

    Returns:
        Non-empty task description.

    Raises:
        typer.Exit: When neither/both sources are set, the file is missing,
            unreadable, or empty.
    """
    has_task = bool(task and task.strip())
    has_file = bool(file and file.strip())
    if has_task == has_file:
        typer.echo(
            "Specify exactly one of: TASK or --file <path>.",
            err=True,
        )
        raise typer.Exit(1)

    if has_task:
        assert task is not None
        return task

    assert file is not None
    path = file.strip()
    try:
        if path == "-":
            content = sys.stdin.read()
        else:
            content = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Error reading task file: {exc}", err=True)
        raise typer.Exit(1) from exc

    text = content.strip()
    if not text:
        typer.echo("Error: task file is empty.", err=True)
        raise typer.Exit(1)
    return text


def _submit_impl(
    task: str | None,
    *,
    file: str | None = None,
    priority: int = 50,
    workspace: str | None = None,
    rail: str | None = None,
    wait: bool = False,
) -> None:
    """Submit a task; optionally wait for completion."""
    resolved = _resolve_submit_task(task, file)
    client = _require_daemon_ws()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.autopilot_submit(
        resolved, priority=priority, workspace=submit_workspace, rail_id=rail
    )
    goal_id = str(result.get("goal_id") or "")
    typer.echo(f"Submitted goal: {goal_id or '?'}")
    if result.get("rail_id"):
        typer.echo(f"  Rail: {result['rail_id']}")
    if wait and goal_id:
        _wait_for_goal(client, goal_id)


@app.command("submit")
def submit(
    task: str | None = typer.Argument(
        None,
        help="Task description (omit when using --file).",
    ),
    file: str | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Read task description from a UTF-8 file (use - for stdin).",
    ),
    priority: int = typer.Option(50, "--priority", "-p", help="Goal priority (0-100)."),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace directory (default: current directory).",
    ),
    rail: str | None = typer.Option(
        None,
        "--rail",
        help="LoopRail id (e.g. feature-dev, greenfield-system, spike).",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Wait until the goal completes (sync).",
    ),
) -> None:
    """Submit a task (async unless --wait)."""
    _submit_impl(task, file=file, priority=priority, workspace=workspace, rail=rail, wait=wait)


@app.command("run")
def run(
    prompt: str | None = typer.Argument(
        None,
        help="Task description (omit when using --file).",
    ),
    file: str | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Read task description from a UTF-8 file (use - for stdin).",
    ),
    priority: int = typer.Option(50, "--priority", "-p", help="Goal priority (0-100)."),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace directory (default: current directory).",
    ),
    rail: str | None = typer.Option(
        None,
        "--rail",
        help="LoopRail id (e.g. feature-dev, greenfield-system, spike).",
    ),
) -> None:
    """Alias for submit --wait (sync)."""
    _submit_impl(prompt, file=file, priority=priority, workspace=workspace, rail=rail, wait=True)


@app.command("status")
def status() -> None:
    """Show autopilot state and job summary."""
    client = _require_daemon_ws()
    data = client.autopilot_status()
    state = data.get("state", data.get("status", "unknown"))
    running = data.get("running", False)
    dreaming = data.get("dreaming", False)
    typer.echo(f"Autopilot state: {state}")
    typer.echo(f"Scheduling loop: {'running' if running else 'stopped'}")
    if dreaming:
        typer.echo("Dreaming: yes")
    loop_pool = data.get("loop_pool")
    if isinstance(loop_pool, dict) and loop_pool:
        active = loop_pool.get("active", 0)
        idle = loop_pool.get("idle", 0)
        max_loops = loop_pool.get("max", "?")
        typer.echo(f"Worker pool: {active}/{idle}/{max_loops} (active/idle/max)")

    jobs = client.autopilot_list_jobs().get("jobs") or []
    goals = client.autopilot_list_goals().get("goals") or []
    typer.echo(f"\nJobs (root goals): {len(jobs)}")
    if goals:
        counts = Counter(str(g.get("status", "pending")) for g in goals)
        typer.echo(f"Goals in DAG: {len(goals)}")
        for stat, count in sorted(counts.items()):
            typer.echo(f"  {stat}: {count}")
    elif not jobs:
        typer.echo("Goals in DAG: 0")

    if jobs:
        typer.echo("\nJobs:")
        for j in jobs:
            jid = str(j.get("id", "?"))
            sid = jid[:8]
            sstat = j.get("status", "pending")
            sdesc = _preview_desc(j.get("description", ""), 50)
            stok = format_tokens(j.get("total_tokens_used", 0))
            typer.echo(f"  [{sid}] {sstat:10s}  tok={stok:>5s}  {sdesc}")


@app.command("jobs")
def list_jobs(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List root jobs."""
    client = _require_daemon_ws()
    payload = client.autopilot_list_jobs()
    jobs = payload.get("jobs") or []
    if not jobs:
        typer.echo("No jobs found.")
        return

    for j in jobs:
        if status_filter and j.get("status", "") != status_filter:
            continue
        sid = j.get("id", "?")[:8]
        sdesc = _preview_desc(j.get("description", ""), 60)
        sstat = j.get("status", "pending")
        spri = j.get("priority", 50)
        stok = format_tokens(j.get("total_tokens_used", 0))
        typer.echo(f"  [{sid}] {sstat:10s} pri={spri:3d}  tok={stok:>5s}  {sdesc}")


@app.command("goals")
def list_goals(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List all goals (including subgoals)."""
    client = _require_daemon_ws()
    payload = client.autopilot_list_goals()
    goals = payload.get("goals") or []
    if not goals:
        typer.echo("No goals found.")
        return

    for g in goals:
        if status_filter and g.get("status", "") != status_filter:
            continue
        gid = str(g.get("id", "?"))[:8]
        parent = g.get("parent_id")
        parent_s = f" parent={str(parent)[:8]}" if parent else ""
        desc = _preview_desc(g.get("description", ""), 50)
        stat = g.get("status", "pending")
        typer.echo(f"  [{gid}] {stat:10s}{parent_s}  {desc}")


def _children_from_edges(edges: list[Any]) -> dict[str, list[str]]:
    """Build adjacency from ``source`` → ``target`` edge list."""
    children: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, tgt = edge.get("source"), edge.get("target")
        if src and tgt:
            children.setdefault(str(src), []).append(str(tgt))
    return children


def _render_dag_tree(dag: dict, root_id: str) -> None:
    """Render DAG as ASCII tree for job visualization."""
    nodes = {n["id"]: n for n in dag.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    children = _children_from_edges(list(dag.get("edges") or []))

    def render_node(goal_id: str, indent: str = "", is_last: bool = True) -> None:
        node = nodes.get(goal_id)
        if not node:
            return

        if indent:
            prefix = indent + ("└─ " if is_last else "├─ ")
        else:
            prefix = ""

        status = node.get("status", "pending")
        desc = _preview_desc(node.get("description", ""), 50)
        typer.echo(f'{prefix}{goal_id[:8]} ({status}) "{desc}"')

        child_ids = children.get(goal_id, [])
        for i, child_id in enumerate(child_ids):
            child_indent = indent + ("    " if is_last else "│   ")
            render_node(child_id, child_indent, i == len(child_ids) - 1)

    render_node(root_id)


@app.command("job")
def show_job(
    job_id: str = typer.Argument(..., help="Job ID."),
) -> None:
    """Show job and goal DAG."""
    client = _require_daemon_ws()
    try:
        payload = client.autopilot_get_job(job_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    job = payload.get("job")
    dag = payload.get("dag")

    if not job:
        typer.echo(f"Job '{job_id}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Job ID:          {job.get('id')}")
    typer.echo(f"Status:          {job.get('status', 'pending')}")
    typer.echo(f"Priority:        {job.get('priority', 50)}")
    tokens = payload.get("total_tokens_used", job.get("total_tokens_used", 0))
    typer.echo(f"Tokens used:     {format_tokens(tokens)}")
    if job.get("workspace"):
        typer.echo(f"Workspace:       {job['workspace']}")
    created = job.get("created_at", "")
    if created:
        created_short = created[:19] if len(created) > 19 else created
        typer.echo(f"Created:         {created_short}")

    active = payload.get("active_goals", 0)
    completed = payload.get("completed_goals", 0)
    total = payload.get("total_goals", 0)
    typer.echo(f"Active goals:    {active}")
    typer.echo(f"Completed goals: {completed}")
    typer.echo(f"Total goals:     {total}")

    typer.echo("\nGoal DAG:")
    if dag:
        _render_dag_tree(dag, str(job.get("id") or job_id))
    else:
        typer.echo("  (no subgoals)")


@app.command("goal")
def show_goal(
    goal_id: str = typer.Argument(..., help="Goal ID."),
) -> None:
    """Show goal details."""
    client = _require_daemon_ws()
    payload = client.autopilot_get_goal(goal_id)
    found = payload.get("goal")
    if not found:
        typer.echo(f"Goal '{goal_id}' not found.")
        raise typer.Exit(1)

    typer.echo(f"ID:          {found.get('id')}")
    typer.echo(f"Description: {found.get('description')}")
    typer.echo(f"Status:      {found.get('status', 'pending')}")
    typer.echo(f"Priority:    {found.get('priority', 50)}")
    if found.get("depends_on"):
        typer.echo(f"Depends On:  {', '.join(found['depends_on'])}")
    if found.get("source_file"):
        typer.echo(f"Source File: {found['source_file']}")


@app.command("cancel")
def cancel_goal(
    goal_id: str | None = typer.Argument(
        None,
        help="Goal ID (omit with --all or --job).",
    ),
    cancel_all: bool = typer.Option(
        False,
        "--all",
        help="Cancel all open goals.",
    ),
    job_id: str | None = typer.Option(
        None,
        "--job",
        help="Cancel a job and its descendants.",
    ),
) -> None:
    """Cancel a goal, job subtree, or all open goals."""
    modes = sum(1 for flag in (bool(goal_id), cancel_all, bool(job_id)) if flag)
    if modes != 1:
        typer.echo(
            "Specify exactly one of: GOAL_ID, --all, or --job <id>.",
            err=True,
        )
        raise typer.Exit(1)

    client = _require_daemon_ws()
    if cancel_all:
        result = client.autopilot_cancel_all()
        count = result.get("cancelled_count", 0)
        typer.echo(f"Cancelled {count} open goal(s).")
        return
    if job_id:
        result = client.job_cancel(job_id)
        typer.echo(f"Cancel job result: {result.get('status', result)}")
        return
    assert goal_id is not None
    result = client.autopilot_cancel_goal(goal_id)
    typer.echo(f"Cancel result: {result.get('status', result)}")


@app.command("resume")
def resume_goal(
    goal_id: str = typer.Argument(..., help="Goal ID."),
) -> None:
    """Resume a suspended or blocked goal."""
    client = _require_daemon_ws()
    try:
        result = client.autopilot_resume(goal_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Goal resumed: {result.get('goal_id', goal_id)} → {result.get('new_status', 'pending')}"
    )


def _short_loop_id(loop_id: str, *, keep: int = 8) -> str:
    """Shorten assignment loop ids for display."""
    if len(loop_id) <= keep + 12:
        return loop_id
    # Prefer suffix after last __ for uuid distinction
    if "__" in loop_id:
        prefix, _, suffix = loop_id.rpartition("__")
        short_suffix = suffix[:keep] if len(suffix) > keep else suffix
        return f"{prefix}__{short_suffix}…"
    return loop_id[:keep] + "…"


def format_tokens(tokens: Any) -> str:
    """Format a token count for autopilot job UI (e.g. ``12K``)."""
    try:
        n = int(tokens or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n // 1000}K"
    return f"{n // 1_000_000}M"


def format_elapsed(started_at: Any, *, now: Any | None = None) -> str:
    """Format execution elapsed time as ``HH:MM:SS``.

    Args:
        started_at: ISO timestamp string or datetime.
        now: Optional clock override (datetime).

    Returns:
        Elapsed string, or empty when ``started_at`` is missing/invalid.
    """
    from datetime import UTC, datetime

    if started_at is None or started_at == "":
        return ""
    if isinstance(started_at, datetime):
        start = started_at
    else:
        try:
            start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return ""
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    clock = now if isinstance(now, datetime) else datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    secs = max(0, int((clock - start).total_seconds()))
    hours, rem = divmod(secs, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _created_at_timestamp(raw: Any) -> float | None:
    """Parse a job ``created_at`` to epoch seconds, or ``None`` if invalid."""
    from datetime import UTC, datetime

    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        start = raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
        return start.timestamp()
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return start.timestamp()


def _job_created_sort_key(job: dict) -> tuple[float, str]:
    """Newest ``created_at`` first; missing timestamps sort last."""
    ts = _created_at_timestamp(job.get("created_at"))
    if ts is None:
        ts = float("-inf")
    return (-ts, str(job.get("id") or ""))


def _sort_jobs_newest_first(jobs: list[dict]) -> list[dict]:
    """Order jobs for top forest: most recently created at the top."""
    return sorted(jobs, key=_job_created_sort_key)


@dataclass
class TopViewState:
    """Interactive view flags for autopilot top (IG-688 / IG-694 / IG-698)."""

    include_terminal: bool = False
    show_steps: bool = True
    show_loops: bool = True
    interval: float = 2.0
    scroll: int = 0
    page_size: int = 1
    help_open: bool = False
    quit: bool = False
    force_refresh: bool = False
    body_line_count: int = 0


def _page_delta(state: TopViewState, *, half: bool = False) -> int:
    """Lines to jump for page / half-page scroll."""
    size = max(1, state.page_size)
    return max(1, size // 2) if half else size


def apply_top_key(state: TopViewState, key: str) -> None:
    """Apply a single-char (or special) key to view state.

    Args:
        state: Mutable view state.
        key: Key string — single char, named specials (``up``, ``page_down``,
            ``ctrl_d``, …), or ``space``.
    """
    if state.help_open:
        state.help_open = False
        return

    if key in {"q", "Q"}:
        state.quit = True
        return
    if key in {"h", "?"}:
        state.help_open = True
        return
    if key == "a":
        state.include_terminal = not state.include_terminal
        state.force_refresh = True
        state.scroll = 0
        return
    if key == "s":
        state.show_steps = not state.show_steps
        return
    if key == "l":
        state.show_loops = not state.show_loops
        return
    if key == "d":
        # full → compact → steps → full (default is full)
        if state.show_steps and state.show_loops:
            state.show_steps = False
            state.show_loops = False
        elif not state.show_steps and not state.show_loops:
            state.show_steps = True
            state.show_loops = False
        else:
            state.show_steps = True
            state.show_loops = True
        return
    if key in {"+", "="}:
        state.interval = max(_TOP_INTERVAL_MIN, round(state.interval - 0.5, 1))
        return
    if key in {"-", "_"}:
        state.interval = min(_TOP_INTERVAL_MAX, round(state.interval + 0.5, 1))
        return
    if key == "space":
        state.force_refresh = True
        return
    if key in {"j", "down", "ctrl_e"}:
        state.scroll += 1
        return
    if key in {"k", "up", "ctrl_y"}:
        state.scroll = max(0, state.scroll - 1)
        return
    if key in {"ctrl_d"}:
        state.scroll += _page_delta(state, half=True)
        return
    if key in {"ctrl_u"}:
        state.scroll = max(0, state.scroll - _page_delta(state, half=True))
        return
    if key in {"ctrl_f", "page_down"}:
        state.scroll += _page_delta(state)
        return
    if key in {"ctrl_b", "page_up"}:
        state.scroll = max(0, state.scroll - _page_delta(state))
        return
    if key in {"g", "home"}:
        state.scroll = 0
        return
    if key in {"G", "end"}:
        state.scroll = max(0, state.body_line_count)
        return


@contextmanager
def _cbreak_stdin() -> Iterator[bool]:
    """Put stdin in cbreak for single-key reads; yields whether active."""
    if not sys.stdin.isatty():
        yield False
        return
    try:
        import termios
        import tty
    except ImportError:
        yield False
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def decode_top_csi(seq: str) -> str | None:
    """Map a CSI/SS3 tail (bytes after ESC) to a named key, if recognized.

    Args:
        seq: Escape tail such as ``[A``, ``[5~``, or ``OH``.

    Returns:
        Named key (``up``, ``page_down``, ``home``, …) or None.
    """
    mapping = {
        "[A": "up",
        "[B": "down",
        "[H": "home",
        "[F": "end",
        "[1~": "home",
        "[4~": "end",
        "[7~": "home",
        "[8~": "end",
        "[5~": "page_up",
        "[6~": "page_down",
        "OH": "home",
        "OF": "end",
    }
    return mapping.get(seq)


def _drain_escape_tail() -> str:
    """Read CSI/SS3 bytes after ESC until a final byte or short idle."""
    chunks: list[str] = []
    # First byte after ESC (usually '[' or 'O')
    more, _, _ = select.select([sys.stdin], [], [], 0.02)
    if not more:
        return ""
    chunks.append(sys.stdin.read(1))
    # Continue until final CSI byte (~ or A–Z) or idle
    while True:
        more, _, _ = select.select([sys.stdin], [], [], 0.02)
        if not more:
            break
        ch = sys.stdin.read(1)
        chunks.append(ch)
        if ch == "~" or (len(ch) == 1 and ch.isalpha()):
            break
        if len(chunks) >= 8:
            break
    return "".join(chunks)


def _read_top_key(timeout: float, *, cbreak_active: bool) -> str | None:
    """Non-blocking single key from stdin. Returns None on timeout."""
    if not cbreak_active or not sys.stdin.isatty():
        time.sleep(min(timeout, 0.05))
        return None
    ready, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout))
    if not ready:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        seq = _drain_escape_tail()
        if not seq:
            return None
        return decode_top_csi(seq)
    if ch == " ":
        return "space"
    # Vim view-mode Ctrl chords (cbreak delivers the control byte).
    ctrl_map = {
        "\x02": "ctrl_b",  # Ctrl-b
        "\x04": "ctrl_d",  # Ctrl-d
        "\x05": "ctrl_e",  # Ctrl-e
        "\x06": "ctrl_f",  # Ctrl-f
        "\x15": "ctrl_u",  # Ctrl-u
        "\x19": "ctrl_y",  # Ctrl-y
    }
    if ch in ctrl_map:
        return ctrl_map[ch]
    return ch


def _status_style(status: str) -> str:
    """Rich style name for a goal/job/loop/step status."""
    return _STATUS_STYLE.get(str(status).lower(), "white")


def _text_line(*parts: tuple[str, str | None]) -> Text:
    """Build a single Rich Text line from (segment, style) parts."""
    line = Text()
    for text, style in parts:
        line.append(text, style=style)
    return line


# Preferred status order in htop-style count breakdowns.
_TOP_STATUS_ORDER: tuple[str, ...] = (
    "active",
    "pending",
    "blocked",
    "awaiting_clarification",
    "suspended",
    "completed",
    "failed",
    "cancelled",
    "skipped",
)
_TOP_STATUS_SHORT: dict[str, str] = {
    "awaiting_clarification": "await",
    "completed": "done",
}


def _meter_fill_style(ratio: float) -> str:
    """htop-like meter color by utilization ratio."""
    if ratio >= 0.85:
        return "bold bright_red"
    if ratio >= 0.55:
        return "bold bright_yellow"
    return "bold bright_green"


def _meter_bar(used: int | float, total: int | float, *, width: int = 10) -> Text:
    """Render a compact ``[████░░░░░░]`` utilization meter."""
    bar_w = max(4, width)
    tot = float(total) if total else 0.0
    use = max(0.0, float(used))
    ratio = min(1.0, use / tot) if tot > 0 else 0.0
    filled = int(round(ratio * bar_w))
    filled = min(bar_w, max(0, filled))
    style = _meter_fill_style(ratio)
    out = Text()
    out.append("[", style=_STYLE_DIM)
    if filled:
        out.append("█" * filled, style=style)
    empty = bar_w - filled
    if empty:
        out.append("░" * empty, style=_STYLE_DIM)
    out.append("]", style=_STYLE_DIM)
    return out


def _short_status_label(status: str) -> str:
    """Compact status label for header count rows."""
    key = str(status).lower()
    return _TOP_STATUS_SHORT.get(key, key)


def _append_status_counts(line: Text, counts: Counter[str]) -> None:
    """Append ``status=N`` segments in preferred order, then leftovers."""
    seen: set[str] = set()
    for key in _TOP_STATUS_ORDER:
        n = int(counts.get(key, 0))
        if n <= 0:
            continue
        seen.add(key)
        line.append("  ")
        line.append(f"{_short_status_label(key)}=", style=_STYLE_DIM)
        line.append(str(n), style=_status_style(key))
    for key, n in sorted(counts.items()):
        if key in seen or int(n) <= 0:
            continue
        line.append("  ")
        line.append(f"{_short_status_label(key)}=", style=_STYLE_DIM)
        line.append(str(n), style=_status_style(key))


def aggregate_top_stats(snapshot: dict) -> dict[str, Any]:
    """Aggregate Jobs/Goals/Loops/Steps counts from an ``autopilot_top`` snapshot.

    Counts reflect the forest currently in the payload (filtered when
    ``mode=active``). Pool fields come from ``loop_pool``.
    """
    jobs_raw = [j for j in (snapshot.get("jobs") or []) if isinstance(j, dict)]
    job_counts: Counter[str] = Counter()
    goal_counts: Counter[str] = Counter()
    loop_assigned = 0
    steps_completed = 0
    steps_total = 0
    oldest_created: Any = None
    oldest_ts: float | None = None

    for job in jobs_raw:
        jstat = str(job.get("status") or "pending").lower()
        job_counts[jstat] += 1
        created = job.get("created_at")
        ts = _created_at_timestamp(created)
        if ts is not None and (oldest_ts is None or ts < oldest_ts):
            oldest_ts = ts
            oldest_created = created

        dag = job.get("dag") if isinstance(job.get("dag"), dict) else {}
        for node in dag.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            goal_counts[str(node.get("status") or "pending").lower()] += 1
            steps_completed += int(node.get("steps_completed") or 0)
            steps_total += int(node.get("steps_total") or 0)

        for entry in job.get("loops") or []:
            if isinstance(entry, dict):
                loop_assigned += 1

    pool = snapshot.get("loop_pool") if isinstance(snapshot.get("loop_pool"), dict) else {}
    return {
        "jobs_total": sum(job_counts.values()),
        "jobs_by_status": job_counts,
        "jobs_active": int(job_counts.get("active", 0)),
        "goals_total": sum(goal_counts.values()),
        "goals_by_status": goal_counts,
        "goals_active": int(goal_counts.get("active", 0)),
        "goals_completed": int(goal_counts.get("completed", 0)),
        "loop_pool_active": int(pool.get("active") or 0),
        "loop_pool_idle": int(pool.get("idle") or 0),
        "loop_pool_max": pool.get("max", "?"),
        "loops_assigned": loop_assigned,
        "steps_completed": steps_completed,
        "steps_total": steps_total,
        "oldest_created_at": oldest_created,
    }


def _format_top_header(
    snapshot: dict,
    *,
    state: TopViewState,
    width: int = 72,
) -> list[Text]:
    """Build htop-style header lines for autopilot top (Rich Text rows)."""
    from datetime import datetime

    stats = aggregate_top_stats(snapshot)
    running = "running" if snapshot.get("running") else "stopped"
    dreaming = bool(snapshot.get("dreaming"))
    clock = datetime.now().strftime("%H:%M:%S")
    uptime = format_elapsed(stats.get("oldest_created_at"))
    mode = "all" if state.include_terminal else "active"
    mode_style = _STYLE_META if state.include_terminal else "bold bright_green"
    steps_flag = "on" if state.show_steps else "off"
    loops_flag = "on" if state.show_loops else "off"
    rule = "─" * max(8, width)
    meter_w = 10 if width >= 60 else 6

    title = Text()
    title.append("Autopilot top", style=_STYLE_HEADER)
    title.append(" · ", style=_STYLE_TREE)
    title.append(running, style=_status_style(running))
    if dreaming:
        title.append(" · ", style=_STYLE_TREE)
        title.append("dreaming", style="bright_yellow")
    title.append(f" · {clock}", style=_STYLE_TREE)
    if uptime:
        title.append(" · up ", style=_STYLE_TREE)
        title.append(uptime, style=_STYLE_META)

    jobs_line = Text()
    jobs_line.append("Jobs   ", style=_STYLE_JOB)
    jobs_line.append_text(
        _meter_bar(stats["jobs_active"], max(stats["jobs_total"], 1), width=meter_w)
    )
    jobs_line.append(f"  {stats['jobs_total']} total", style=_STYLE_META)
    _append_status_counts(jobs_line, stats["jobs_by_status"])

    goals_line = Text()
    goals_line.append("Goals  ", style=_STYLE_GOAL)
    # Prefer completion progress when any done; else active utilization.
    g_total = max(int(stats["goals_total"]), 1)
    g_meter_used = (
        stats["goals_completed"] if stats["goals_completed"] > 0 else stats["goals_active"]
    )
    goals_line.append_text(_meter_bar(g_meter_used, g_total, width=meter_w))
    goals_line.append(f"  {stats['goals_total']} total", style=_STYLE_META)
    _append_status_counts(goals_line, stats["goals_by_status"])

    pool_active = int(stats["loop_pool_active"])
    pool_idle = int(stats["loop_pool_idle"])
    pool_max = stats["loop_pool_max"]
    try:
        pool_max_n = int(pool_max)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pool_max_n = 0
    loops_line = Text()
    loops_line.append("Loops  ", style=_STYLE_LOOP)
    loops_line.append_text(_meter_bar(pool_active, max(pool_max_n, 1), width=meter_w))
    loops_line.append(
        f"  {pool_active}/{pool_idle}/{pool_max}",
        style=_STYLE_META,
    )
    loops_line.append(" (active/idle/max)", style=_STYLE_DIM)
    loops_line.append(f"  · {stats['loops_assigned']} assigned", style=_STYLE_META)

    lines: list[Text] = [title, jobs_line, goals_line, loops_line]

    steps_c = int(stats["steps_completed"])
    steps_t = int(stats["steps_total"])
    if steps_t > 0:
        steps_line = Text()
        steps_line.append("Steps  ", style=_STYLE_STEP)
        steps_line.append_text(_meter_bar(steps_c, steps_t, width=meter_w))
        steps_line.append(f"  {steps_c}/{steps_t} done", style=_STYLE_META)
        lines.append(steps_line)

    flags = Text()
    flags.append("mode=", style=_STYLE_DIM)
    flags.append(mode, style=mode_style)
    if not state.include_terminal:
        flags.append(" (live)", style="dim green")
    flags.append("  ")
    flags.append("steps=", style=_STYLE_DIM)
    flags.append(steps_flag, style=_STYLE_STEP if state.show_steps else _STYLE_DIM)
    flags.append("  ")
    flags.append("loops=", style=_STYLE_DIM)
    flags.append(loops_flag, style=_STYLE_LOOP if state.show_loops else _STYLE_DIM)
    flags.append("  ")
    flags.append("delay=", style=_STYLE_DIM)
    flags.append(f"{state.interval:g}s", style=_STYLE_META)
    lines.append(flags)
    lines.append(Text(rule, style=_STYLE_TREE))
    return lines


def _format_step_list(
    steps: dict,
    *,
    indent: str,
    lines: list[Text],
    trailing_siblings: int,
) -> None:
    """Append planned steps as a flat list under a goal (space-efficient vs tree).

    Renders the full StepDAG for goals already present in the forest. Goal
    filtering (mode=active) happens upstream; do not drop completed steps here
    or live goals with finished plan waves look empty when ``steps=on``.
    """
    ordered_nodes: list[dict] = []
    seen: set[str] = set()
    for raw in steps.get("nodes") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        sid = str(raw["id"])
        if sid in seen:
            continue
        seen.add(sid)
        ordered_nodes.append(raw)

    for i, node in enumerate(ordered_nodes):
        is_last = (i == len(ordered_nodes) - 1) and trailing_siblings == 0
        branch = "└─ " if is_last else "├─ "
        status = str(node.get("status", "pending"))
        desc = _preview_desc(node.get("description", ""), 40)
        step_id = str(node["id"])
        sid = step_id if len(step_id) <= 12 else step_id[:12] + "…"
        deps = [str(d) for d in (node.get("dependencies") or []) if d]
        parts: list[tuple[str, str | None]] = [
            (indent, _STYLE_TREE),
            (branch, _STYLE_TREE),
            ("STEP ", _STYLE_STEP),
            (f"[{sid}] ", _STYLE_STEP),
            (f"{status:10s}", _status_style(status)),
            (f'  "{desc}"', _STYLE_DIM),
        ]
        if deps:
            parts.append((f"  ←{','.join(deps[:3])}", _STYLE_META))
        lines.append(_text_line(*parts))


def _format_top_forest(
    snapshot: dict,
    *,
    show_steps: bool = True,
    show_loops: bool = True,
    include_terminal: bool = False,
) -> list[Text]:
    """Render jobs → goal DAG → step DAG → loops as colored Rich Text rows.

    Jobs are shown newest-first (by ``created_at``) so the latest job sits at
    the top of the forest. When ``show_steps`` is on, each goal's StepDAG is
    listed in full (server already filtered which goals appear in mode=active).
    """
    raw_jobs = [j for j in (snapshot.get("jobs") or []) if isinstance(j, dict)]
    jobs = _sort_jobs_newest_first(raw_jobs)
    if not jobs:
        msg = "No jobs." if include_terminal else "No active jobs."
        return [Text(msg, style="dim italic")]

    lines: list[Text] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id", "?"))
        jstat = str(job.get("status", "pending"))
        jpri = job.get("priority", 50)
        jdesc = _preview_desc(job.get("description", ""), 50)
        jelapsed = format_elapsed(job.get("created_at"))
        jelapsed_s = f"  {jelapsed}" if jelapsed else ""
        jtok = format_tokens(job.get("total_tokens_used", 0))
        lines.append(
            _text_line(
                ("JOB  ", _STYLE_JOB),
                (f"[{jid[:8]}] ", _STYLE_JOB),
                (f"{jstat:10s}", _status_style(jstat)),
                (f"  pri={jpri}{jelapsed_s}  tok={jtok}", _STYLE_META),
                (f'  "{jdesc}"', _STYLE_DIM),
            )
        )

        dag = job.get("dag") if isinstance(job.get("dag"), dict) else {}
        nodes = {
            str(n["id"]): n for n in (dag.get("nodes") or []) if isinstance(n, dict) and n.get("id")
        }
        edges = dag.get("edges") or []
        children = _children_from_edges(list(edges))

        loops = [L for L in (job.get("loops") or []) if isinstance(L, dict)] if show_loops else []
        loops_by_goal: dict[str, list[dict]] = {}
        for entry in loops:
            gid = str(entry.get("goal_id") or "")
            loops_by_goal.setdefault(gid, []).append(entry)

        root_id = str(dag.get("root_id") or jid)
        rendered_goals: set[str] = set()

        def render_goal(goal_id: str, indent: str, is_last: bool) -> None:
            node = nodes.get(goal_id)
            if not node:
                return
            rendered_goals.add(goal_id)
            branch = "└─ " if is_last else "├─ "
            child_indent = indent + ("    " if is_last else "│   ")
            status = str(node.get("status", "pending"))
            desc = _preview_desc(node.get("description", ""), 50)
            steps_c = node.get("steps_completed", 0) or 0
            steps_t = node.get("steps_total", 0) or 0
            steps_s = f"  steps {steps_c}/{steps_t}" if steps_t else ""
            gtok = int(node.get("total_tokens_used") or 0)
            tok_s = f"  tok={format_tokens(gtok)}" if gtok else ""
            goal_line = _text_line(
                (indent, _STYLE_TREE),
                (branch, _STYLE_TREE),
                ("GOAL ", _STYLE_GOAL),
                (f"[{goal_id[:8]}] ", _STYLE_GOAL),
                (f"{status:10s}", _status_style(status)),
                (f'  "{desc}"', _STYLE_DIM),
            )
            if steps_s:
                goal_line.append(steps_s, style=_STYLE_STEP)
            if tok_s:
                goal_line.append(tok_s, style=_STYLE_META)
            lines.append(goal_line)

            goal_loops = loops_by_goal.get(goal_id, [])
            child_ids = children.get(goal_id, [])
            steps_blob = (
                node.get("steps") if show_steps and isinstance(node.get("steps"), dict) else None
            )
            trailing = len(goal_loops) + len(child_ids)
            if steps_blob:
                _format_step_list(
                    steps_blob,
                    indent=child_indent,
                    lines=lines,
                    trailing_siblings=trailing,
                )

            for i, entry in enumerate(goal_loops):
                last_sub = (i == len(goal_loops) - 1) and not child_ids
                lb = "└─ " if last_sub else "├─ "
                lid = _short_loop_id(str(entry.get("loop_id", "?")))
                seq = entry.get("seq", "?")
                lstat = str(entry.get("status", "active"))
                elapsed = format_elapsed(entry.get("started_at"))
                elapsed_s = f"  {elapsed}" if elapsed else ""
                lines.append(
                    _text_line(
                        (child_indent, _STYLE_TREE),
                        (lb, _STYLE_TREE),
                        ("LOOP ", _STYLE_LOOP),
                        (f"{lid}  ", _STYLE_LOOP),
                        (lstat, _status_style(lstat)),
                        (f"  #{seq}{elapsed_s}", _STYLE_META),
                    )
                )
            for i, child_id in enumerate(child_ids):
                render_goal(child_id, child_indent, i == len(child_ids) - 1)

        if root_id in nodes:
            tops = [root_id]
        else:
            targets = {str(e.get("target")) for e in edges if isinstance(e, dict)}
            tops = [nid for nid in nodes if nid not in targets] or list(nodes.keys())

        for i, nid in enumerate(tops):
            render_goal(nid, "", i == len(tops) - 1)

        orphans = [
            entry for entry in loops if str(entry.get("goal_id") or "") not in rendered_goals
        ]
        for i, entry in enumerate(orphans):
            branch = "└─ " if i == len(orphans) - 1 else "├─ "
            lid = _short_loop_id(str(entry.get("loop_id", "?")))
            seq = entry.get("seq", "?")
            gid = str(entry.get("goal_id") or "?")[:8]
            lstat = str(entry.get("status", "active"))
            elapsed = format_elapsed(entry.get("started_at"))
            elapsed_s = f"  {elapsed}" if elapsed else ""
            lines.append(
                _text_line(
                    (branch, _STYLE_TREE),
                    ("LOOP ", _STYLE_LOOP),
                    (f"{lid}  ", _STYLE_LOOP),
                    (lstat, _status_style(lstat)),
                    (f"  #{seq}{elapsed_s}", _STYLE_META),
                    (f"  ?goal={gid}", "bright_yellow"),
                )
            )

        lines.append(Text(""))

    if lines and not lines[-1].plain:
        lines.pop()
    return lines


def render_top_snapshot(
    snapshot: dict,
    *,
    interval: float | None = None,
    width: int | None = None,
    height: int | None = None,
    state: TopViewState | None = None,
) -> Text:
    """Render a full autopilot top screen as Rich ``Text``.

    When ``height`` is set, pad so the footer sits on the last terminal row
    (linux-``top`` style viewport). Use ``.plain`` for unstyled assertions.
    """
    view = state or TopViewState(interval=interval if interval is not None else 2.0)
    if interval is not None:
        view.interval = interval
    cols = max(40, width or 72)
    header = _format_top_header(snapshot, state=view, width=cols)
    if view.help_open:
        body: list[Text] = [Text(line, style=_STYLE_META) for line in _TOP_HELP_LINES]
    else:
        body = _format_top_forest(
            snapshot,
            show_steps=view.show_steps,
            show_loops=view.show_loops,
            include_terminal=view.include_terminal,
        )
    view.body_line_count = len(body)
    rule = "─" * cols
    footer = [
        Text(rule, style=_STYLE_TREE),
        _text_line(
            ("q Quit", _STYLE_DIM),
            (" · ", _STYLE_TREE),
            ("h Help", _STYLE_DIM),
            (" · ", _STYLE_TREE),
            ("a ", _STYLE_DIM),
            (
                "All" if not view.include_terminal else "Active",
                "bold bright_green" if view.include_terminal else _STYLE_META,
            ),
            (" · ", _STYLE_TREE),
            ("s Steps", _STYLE_STEP if view.show_steps else _STYLE_DIM),
            (" · ", _STYLE_TREE),
            ("l Loops", _STYLE_LOOP if view.show_loops else _STYLE_DIM),
            (" · ", _STYLE_TREE),
            ("d Density", _STYLE_DIM),
            (" · ", _STYLE_TREE),
            ("+/- Delay", _STYLE_DIM),
            (" · ", _STYLE_TREE),
            (f"refresh {view.interval:g}s", _STYLE_META),
        ),
    ]
    if height is not None and height > 0:
        max_body = max(1, height - len(header) - len(footer))
        # Page jumps use the visible body rows (leave one for “… (truncated)”).
        view.page_size = max(1, max_body - 1)
        if len(body) > max_body:
            max_scroll = max(0, len(body) - (max_body - 1))
            start = min(max(0, view.scroll), max_scroll)
            view.scroll = start
            chunk = body[start : start + max_body - 1]
            body = chunk + [Text("… (truncated)", style="dim italic")]
        pad = height - len(header) - len(body) - len(footer)
        if pad > 0:
            body = body + [Text("")] * pad
    else:
        view.page_size = max(1, view.page_size)

    out = Text()
    for i, row in enumerate(header + body + footer):
        if i:
            out.append("\n")
        out.append_text(row)
    return out


@app.command("top")
def top(
    interval: float = typer.Option(
        2.0,
        "--interval",
        "-n",
        help="Refresh interval in seconds (must be > 0).",
    ),
    show_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include completed/failed/cancelled goals (toggle with 'a').",
    ),
) -> None:
    """Live full-screen jobs/goals/steps/loops dashboard (linux-top style)."""
    if interval <= 0:
        typer.echo("Error: --interval must be > 0.", err=True)
        raise typer.Exit(1)

    from rich.console import Console
    from rich.live import Live

    client = _require_daemon_ws()
    console = Console()
    state = TopViewState(
        include_terminal=show_all,
        interval=max(_TOP_INTERVAL_MIN, min(_TOP_INTERVAL_MAX, interval)),
    )
    snapshot: dict[str, Any] = {}

    def _render() -> Text:
        size = console.size
        return render_top_snapshot(
            snapshot,
            width=size.width,
            height=size.height,
            state=state,
        )

    def _fetch() -> None:
        nonlocal snapshot
        data = client.autopilot_top(include_terminal=state.include_terminal)
        snapshot = data if isinstance(data, dict) else {}
        state.force_refresh = False

    try:
        with (
            _cbreak_stdin() as cbreak_active,
            Live(
                console=console,
                refresh_per_second=max(4, int(1 / max(state.interval, 0.25))),
                screen=True,
                transient=True,
            ) as live,
        ):
            _fetch()
            live.update(_render())
            while not state.quit:
                deadline = time.monotonic() + state.interval
                while time.monotonic() < deadline and not state.quit:
                    remaining = deadline - time.monotonic()
                    key = _read_top_key(
                        min(0.05, max(0.0, remaining)),
                        cbreak_active=bool(cbreak_active),
                    )
                    if key is None:
                        continue
                    apply_top_key(state, key)
                    live.update(_render())
                    if state.force_refresh or state.quit:
                        break
                if state.quit:
                    break
                _fetch()
                live.update(_render())
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
