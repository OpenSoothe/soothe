"""Autopilot CLI subcommands for RFC-204.

Daemon-backed control surface: submit tasks and manage goals via WebSocket.
Requires ``soothed start``. Real-time monitoring is via TUI ``/autopilot``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from soothe_client import (
    command_client_from_config,
    is_daemon_live,
    websocket_url_from_config,
)
from soothe_sdk.wire.protocol import preview_first

app = typer.Typer(help="Autopilot — autonomous goal control.")

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "suspended"})
_WAIT_TIMEOUT_S = 600.0


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


def _submit_impl(
    task: str,
    *,
    priority: int = 50,
    workspace: str | None = None,
    rail: str | None = None,
    wait: bool = False,
) -> None:
    """Submit a task; optionally wait for completion."""
    client = _require_daemon_ws()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.autopilot_submit(
        task, priority=priority, workspace=submit_workspace, rail_id=rail
    )
    goal_id = str(result.get("goal_id") or "")
    typer.echo(f"Submitted goal: {goal_id or '?'}")
    if result.get("rail_id"):
        typer.echo(f"  Rail: {result['rail_id']}")
    if wait and goal_id:
        _wait_for_goal(client, goal_id)


@app.command("submit")
def submit(
    task: str = typer.Argument(..., help="Task description."),
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
    _submit_impl(task, priority=priority, workspace=workspace, rail=rail, wait=wait)


@app.command("run")
def run(
    prompt: str = typer.Argument(..., help="Task description."),
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
    _submit_impl(prompt, priority=priority, workspace=workspace, rail=rail, wait=True)


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
            sdesc = preview_first(j.get("description", ""), 50)
            typer.echo(f"  [{sid}] {sstat:10s}  {sdesc}")


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
        sdesc = preview_first(j.get("description", ""), 60)
        sstat = j.get("status", "pending")
        spri = j.get("priority", 50)
        typer.echo(f"  [{sid}] {sstat:10s} pri={spri:3d}  {sdesc}")


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
        desc = preview_first(g.get("description", ""), 50)
        stat = g.get("status", "pending")
        typer.echo(f"  [{gid}] {stat:10s}{parent_s}  {desc}")


def _render_dag_tree(dag: dict, root_id: str) -> None:
    """Render DAG as ASCII tree for job visualization."""
    nodes = {n["id"]: n for n in dag.get("nodes", [])}
    edges = dag.get("edges", [])

    children: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            children.setdefault(src, []).append(tgt)

    def render_node(goal_id: str, indent: str = "", is_last: bool = True) -> None:
        node = nodes.get(goal_id)
        if not node:
            return

        if indent:
            prefix = indent + ("└─ " if is_last else "├─ ")
        else:
            prefix = ""

        status = node.get("status", "pending")
        desc = preview_first(node.get("description", ""), 50)
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


def _format_top_header(snapshot: dict, *, interval: float, width: int = 72) -> list[str]:
    """Build header lines for autopilot top."""
    from datetime import datetime

    del interval  # reserved for footer; header shows live clock instead
    running = "running" if snapshot.get("running") else "stopped"
    dreaming = " · dreaming" if snapshot.get("dreaming") else ""
    pool = snapshot.get("loop_pool") if isinstance(snapshot.get("loop_pool"), dict) else {}
    active = pool.get("active", 0)
    idle = pool.get("idle", 0)
    max_loops = pool.get("max", "?")
    jobs = snapshot.get("jobs") or []
    clock = datetime.now().strftime("%H:%M:%S")
    rule = "─" * max(8, width)
    return [
        (
            f"Autopilot top · {running}{dreaming} · "
            f"pool {active}/{idle}/{max_loops} (active/idle/max) · "
            f"{len(jobs)} job(s) · {clock}"
        ),
        rule,
    ]


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


def _format_step_forest(
    steps: dict,
    *,
    indent: str,
    lines: list[str],
    trailing_siblings: int,
) -> None:
    """Append nested planned step DAG lines under a goal."""
    step_nodes = {
        str(n["id"]): n for n in (steps.get("nodes") or []) if isinstance(n, dict) and n.get("id")
    }
    if not step_nodes:
        return
    step_edges = steps.get("edges") or []
    step_children = _children_from_edges(list(step_edges))
    targets = {str(e.get("target")) for e in step_edges if isinstance(e, dict)}
    roots = [sid for sid in step_nodes if sid not in targets] or list(step_nodes.keys())
    rendered: set[str] = set()

    def render_step(step_id: str, step_indent: str, is_last: bool, *, more_after: int) -> None:
        node = step_nodes.get(step_id)
        if not node or step_id in rendered:
            return
        rendered.add(step_id)
        kids = [c for c in step_children.get(step_id, []) if c in step_nodes]
        # last among steps only when no more loops/goal-children after the whole step tree
        last_among_steps = is_last and more_after == 0 and not kids
        branch = "└─ " if last_among_steps else "├─ "
        # Keep vertical rails while later siblings (loops / child goals) remain
        child_indent = step_indent + ("    " if is_last and more_after == 0 else "│   ")
        status = str(node.get("status", "pending"))
        desc = preview_first(node.get("description", ""), 40)
        sid = step_id if len(step_id) <= 12 else step_id[:12] + "…"
        lines.append(f'{step_indent}{branch}[{sid}] {status:10s} "{desc}"')
        for i, kid in enumerate(kids):
            render_step(kid, child_indent, i == len(kids) - 1, more_after=more_after)

    for i, sid in enumerate(roots):
        render_step(sid, indent, i == len(roots) - 1, more_after=trailing_siblings)

    orphans = [sid for sid in step_nodes if sid not in rendered]
    for i, sid in enumerate(orphans):
        render_step(sid, indent, i == len(orphans) - 1, more_after=trailing_siblings)


def _format_top_forest(snapshot: dict) -> list[str]:
    """Render jobs → goal DAG → step DAG → loops as ASCII tree lines."""
    jobs = snapshot.get("jobs") or []
    if not jobs:
        return ["No active jobs."]

    lines: list[str] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id", "?"))
        jstat = str(job.get("status", "pending"))
        jpri = job.get("priority", 50)
        jdesc = preview_first(job.get("description", ""), 50)
        jelapsed = format_elapsed(job.get("created_at"))
        jelapsed_s = f"  {jelapsed}" if jelapsed else ""
        lines.append(f'[{jid[:8]}] {jstat:10s} pri={jpri}{jelapsed_s}  "{jdesc}"')

        dag = job.get("dag") if isinstance(job.get("dag"), dict) else {}
        nodes = {
            str(n["id"]): n for n in (dag.get("nodes") or []) if isinstance(n, dict) and n.get("id")
        }
        edges = dag.get("edges") or []
        children = _children_from_edges(list(edges))

        loops = [L for L in (job.get("loops") or []) if isinstance(L, dict)]
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
            desc = preview_first(node.get("description", ""), 50)
            steps_c = node.get("steps_completed", 0) or 0
            steps_t = node.get("steps_total", 0) or 0
            steps_s = f"  steps {steps_c}/{steps_t}" if steps_t else ""
            lines.append(f'{indent}{branch}[{goal_id[:8]}] {status:10s} "{desc}"{steps_s}')

            goal_loops = loops_by_goal.get(goal_id, [])
            child_ids = children.get(goal_id, [])
            steps_blob = node.get("steps") if isinstance(node.get("steps"), dict) else None
            trailing = len(goal_loops) + len(child_ids)
            if steps_blob:
                _format_step_forest(
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
                lstat = entry.get("status", "active")
                elapsed = format_elapsed(entry.get("started_at"))
                elapsed_s = f"  {elapsed}" if elapsed else ""
                lines.append(f"{child_indent}{lb}loop {lid}  {lstat}  #{seq}{elapsed_s}")
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
            elapsed = format_elapsed(entry.get("started_at"))
            elapsed_s = f"  {elapsed}" if elapsed else ""
            lines.append(
                f"{branch}loop {lid}  {entry.get('status', 'active')}  "
                f"#{seq}{elapsed_s}  ?goal={gid}"
            )

        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()
    return lines


def render_top_snapshot(
    snapshot: dict,
    *,
    interval: float,
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Render a full autopilot top screen as plain text.

    When ``height`` is set, pad so the footer sits on the last terminal row
    (linux-``top`` style viewport).
    """
    cols = max(40, width or 72)
    header = _format_top_header(snapshot, interval=interval, width=cols)
    body = _format_top_forest(snapshot)
    rule = "─" * cols
    footer = [rule, f"Ctrl+C quit · refresh {interval:g}s"]
    if height is not None and height > 0:
        max_body = max(1, height - len(header) - len(footer))
        if len(body) > max_body:
            body = body[: max(0, max_body - 1)] + ["… (truncated)"]
        pad = height - len(header) - len(body) - len(footer)
        if pad > 0:
            body = body + [""] * pad
    return "\n".join(header + body + footer)


@app.command("top")
def top(
    interval: float = typer.Option(
        1.0,
        "--interval",
        "-n",
        help="Refresh interval in seconds (must be > 0).",
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

    def _fetch() -> str:
        data = client.autopilot_top()
        size = console.size
        return render_top_snapshot(
            data if isinstance(data, dict) else {},
            interval=interval,
            width=size.width,
            height=size.height,
        )

    try:
        with Live(
            console=console,
            refresh_per_second=max(1, int(1 / interval)),
            screen=True,
            transient=True,
        ) as live:
            while True:
                live.update(_fetch())
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
