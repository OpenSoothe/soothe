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

import typer
from soothe_sdk.client import (
    is_daemon_live,
    websocket_url_from_config,
    ws_command_client_from_config,
)
from soothe_sdk.client.protocol import preview_first

app = typer.Typer(help="Autopilot mode — long-running autonomous agent control.")


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
    return ws_command_client_from_config(cfg)


@app.command("run")
def run(
    prompt: str = typer.Argument(..., help="Task for autonomous execution."),
    max_iterations: int | None = typer.Option(
        None,
        "--max-iterations",
        help="Ignored — use daemon config agent.autopilot.max_iterations.",
    ),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Filesystem workspace for the goal (default: current directory).",
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll until the goal completes."),
) -> None:
    """Submit a task to the daemon autopilot and optionally wait for completion.

    Requires the daemon (``soothed start``). This is the production autopilot
    path — distinct from a one-shot agentic query via ``soothe -p``.
    """
    del max_iterations  # daemon owns config for autopilot dispatch
    client = _require_daemon_ws()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.autopilot_submit(prompt, workspace=submit_workspace)
    goal_id = result.get("goal_id", "")
    typer.echo(f"Submitted goal: {goal_id}")
    if not wait or not goal_id:
        return

    deadline = time.time() + 600
    while time.time() < deadline:
        detail = client.autopilot_get_goal(goal_id)
        goal = detail.get("goal") or {}
        status = goal.get("status", "unknown")
        if status in ("completed", "failed", "cancelled", "suspended"):
            typer.echo(f"Goal {goal_id[:8]}: {status}")
            if status == "failed":
                sys.exit(1)
            return
        time.sleep(1.0)
    typer.echo(f"Timed out waiting for goal {goal_id}", err=True)
    sys.exit(1)


@app.command("submit")
def submit(
    task: str = typer.Argument(..., help="Task description."),
    priority: int = typer.Option(50, "--priority", "-p", help="Goal priority (0-100)."),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Filesystem workspace for the goal (default: current directory).",
    ),
) -> None:
    """Submit a new task to the daemon autopilot."""
    client = _require_daemon_ws()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.autopilot_submit(task, priority=priority, workspace=submit_workspace)
    goal_id = result.get("goal_id", "?")
    typer.echo(f"Task submitted (goal_id={goal_id})")
    typer.echo(f"  Priority: {priority}")
    typer.echo(f"  Workspace: {submit_workspace}")


@app.command("status")
def status() -> None:
    """Show overall autopilot state and goal DAG summary."""
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
        typer.echo(f"Worker pool: {loop_pool}")

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
        typer.echo("\nFull DAG for a job: soothe autopilot job <job_id>")


@app.command("list")
def list_jobs(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List jobs (root goals) from the daemon autopilot.

    Jobs are user-submitted tasks. Subgoals created during autonomous
    execution are not shown here; use ``goals`` or ``goal <id>`` for details.
    """
    _list_jobs_impl(status_filter)


@app.command("jobs")
def list_jobs_alias(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """Alias for ``list`` — list root autopilot jobs."""
    _list_jobs_impl(status_filter)


def _list_jobs_impl(status_filter: str) -> None:
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
    """List all goals in the daemon autopilot DAG (including subgoals)."""
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

    # Build children map from edges
    children: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            if src not in children:
                children[src] = []
            children[src].append(tgt)

    def render_node(goal_id: str, indent: str = "", is_last: bool = True) -> None:
        node = nodes.get(goal_id)
        if not node:
            return

        # Prefix for this level
        if indent:
            prefix = indent + ("└─ " if is_last else "├─ ")
        else:
            prefix = ""

        status = node.get("status", "pending")
        desc = preview_first(node.get("description", ""), 50)
        typer.echo(f'{prefix}{goal_id[:8]} ({status}) "{desc}"')

        # Render children
        child_ids = children.get(goal_id, [])
        for i, child_id in enumerate(child_ids):
            child_indent = indent + ("    " if is_last else "│   ")
            render_node(child_id, child_indent, i == len(child_ids) - 1)

    render_node(root_id)


@app.command("job")
def show_job(
    job_id: str = typer.Argument(..., help="Job ID to show details and goal DAG."),
) -> None:
    """Show job status and goal DAG tree visualization.

    A job is a root goal submitted by the user. This command shows
    the job's details and the complete goal DAG under it.
    """
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

    # Job header
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
    goal_id: str = typer.Argument(..., help="Goal ID to show details for."),
) -> None:
    """Show details for a specific goal."""
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
    goal_id: str = typer.Argument(..., help="Goal ID to cancel."),
) -> None:
    """Cancel a goal via the daemon."""
    client = _require_daemon_ws()
    result = client.autopilot_cancel_goal(goal_id)
    typer.echo(f"Cancel result: {result.get('status', result)}")


@app.command("resume")
def resume_goal(
    goal_id: str = typer.Argument(..., help="Goal ID to resume."),
) -> None:
    """Resume a suspended or blocked goal.

    Reactivates a paused goal back to pending status so the scheduler
    can pick it up for execution. Use 'jobs' to list goals and their status.
    """
    client = _require_daemon_ws()
    try:
        result = client.autopilot_resume(goal_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Goal resumed: {result.get('goal_id', goal_id)} → {result.get('new_status', 'pending')}"
    )


@app.command("wake")
def wake() -> None:
    """Exit dreaming mode — resume active execution."""
    client = _require_daemon_ws()
    client.autopilot_wake()
    typer.echo("Wake signal sent.")


@app.command("dream")
def dream() -> None:
    """Force enter dreaming mode."""
    client = _require_daemon_ws()
    client.autopilot_dream()
    typer.echo("Dream signal sent.")
