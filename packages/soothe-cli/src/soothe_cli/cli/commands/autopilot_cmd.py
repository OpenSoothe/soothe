"""Autopilot CLI subcommands for RFC-204.

Daemon-backed control surface: submit tasks and manage goals via HTTP REST.
Requires ``soothed start``. Real-time monitoring is via TUI ``/autopilot``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import typer
from soothe_sdk.client import (
    AutopilotHttpClient,
    ensure_http_rest_available,
    http_rest_url_from_config,
    is_daemon_live,
    websocket_url_from_config,
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


def _require_daemon_http() -> AutopilotHttpClient:
    """Return a live HTTP client or exit."""
    from soothe_cli.runtime import load_config

    cfg = load_config()
    ws_url = websocket_url_from_config(cfg)
    if not asyncio.run(is_daemon_live(ws_url, timeout=5.0)):
        typer.echo(
            "Error: Daemon not running. Start with 'soothed start'.",
            err=True,
        )
        sys.exit(1)
    base_url = http_rest_url_from_config(cfg)
    try:
        ensure_http_rest_available(base_url)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    return AutopilotHttpClient(base_url)


@app.command("run")
def run(
    prompt: str = typer.Argument(..., help="Task for autonomous execution."),
    max_iterations: int | None = typer.Option(
        None,
        "--max-iterations",
        help="Ignored — use daemon config agent.autonomous.max_iterations.",
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
    client = _require_daemon_http()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.submit(prompt, workspace=submit_workspace)
    goal_id = result.get("goal_id", "")
    typer.echo(f"Submitted goal: {goal_id}")
    if not wait or not goal_id:
        return

    deadline = time.time() + 600
    while time.time() < deadline:
        detail = client.get_goal(goal_id)
        goal = detail.get("goal") or {}
        status = goal.get("status", "unknown")
        if status in ("completed", "failed", "suspended"):
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
    client = _require_daemon_http()
    submit_workspace = _resolve_submit_workspace(workspace)
    result = client.submit(task, priority=priority, workspace=submit_workspace)
    goal_id = result.get("goal_id", "?")
    typer.echo(f"Task submitted (goal_id={goal_id})")
    typer.echo(f"  Priority: {priority}")
    typer.echo(f"  Workspace: {submit_workspace}")


@app.command("status")
def status() -> None:
    """Show overall autopilot state from the daemon."""
    client = _require_daemon_http()
    data = client.status()
    typer.echo(f"Autopilot state: {data.get('state', data.get('status', 'unknown'))}")
    if "active_goals" in data:
        typer.echo(f"Active goals: {len(data['active_goals'])}")


@app.command("list")
def list_goals(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List goals from the live daemon autopilot DAG."""
    client = _require_daemon_http()
    payload = client.list_goals()
    goals = payload.get("goals") or []
    if not goals:
        typer.echo("No goals found.")
        return

    for g in goals:
        if status_filter and g.get("status", "") != status_filter:
            continue
        sid = g.get("id", "?")[:8]
        sdesc = preview_first(g.get("description", ""), 60)
        sstat = g.get("status", "pending")
        spri = g.get("priority", 50)
        typer.echo(f"  [{sid}] {sstat:10s} pri={spri:3d}  {sdesc}")


@app.command("goal")
def show_goal(
    goal_id: str = typer.Argument(..., help="Goal ID to show details for."),
) -> None:
    """Show details for a specific goal."""
    client = _require_daemon_http()
    payload = client.get_goal(goal_id)
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
    client = _require_daemon_http()
    result = client.cancel_goal(goal_id)
    typer.echo(f"Cancel result: {result.get('status', result)}")


@app.command("approve")
def approve_goal(
    goal_id: str = typer.Argument(
        ..., help="Confirmation ID to approve (use 'inbox' to list pending)."
    ),
) -> None:
    """Approve a MUST-confirmation goal."""
    client = _require_daemon_http()
    try:
        result = client.approve(goal_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Confirmation approved: {result.get('goal_id', goal_id)}")


@app.command("reject")
def reject_goal(
    goal_id: str = typer.Argument(..., help="Confirmation ID to reject."),
) -> None:
    """Reject a proposed goal."""
    client = _require_daemon_http()
    try:
        result = client.reject(goal_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Confirmation rejected: {result.get('goal_id', goal_id)}")


@app.command("wake")
def wake() -> None:
    """Exit dreaming mode — resume active execution."""
    client = _require_daemon_http()
    client.wake()
    typer.echo("Wake signal sent.")


@app.command("dream")
def dream() -> None:
    """Force enter dreaming mode."""
    client = _require_daemon_http()
    client.dream()
    typer.echo("Dream signal sent.")


def _discover_goals(autopilot_dir: Path) -> list[dict]:
    """Parse goals from GOAL.md/GOALS.md files for offline CLI display."""
    import re

    goals: list[dict] = []

    goal_file = autopilot_dir / "GOAL.md"
    if goal_file.exists():
        g = _parse_single_goal(goal_file.read_text(), str(goal_file))
        if g:
            return [g]

    goals_file = autopilot_dir / "GOALS.md"
    if goals_file.exists():
        text = goals_file.read_text()
        for section in re.split(r"## Goal:", text)[1:]:
            g = _parse_goals_section(section.strip(), str(goals_file))
            if g:
                goals.append(g)

    goals_dir = autopilot_dir / "goals"
    if goals_dir.exists():
        for subdir in sorted(goals_dir.iterdir()):
            gfile = subdir / "GOAL.md"
            if gfile.exists():
                g = _parse_single_goal(gfile.read_text(), str(gfile))
                if g:
                    goals.append(g)

    return goals


def _parse_single_goal(text: str, source: str) -> dict | None:
    """Parse a single GOAL.md file."""
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:  # noqa: PLR2004
        return None

    import yaml

    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    desc = ""
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            desc = s[2:]
            break

    return {
        "id": fm.get("id", source.split("/")[-2]),
        "description": desc or preview_first(body, 100),
        "priority": int(fm.get("priority", 50)),
        "status": fm.get("status", "pending"),
        "depends_on": fm.get("depends_on", []),
        "source_file": source,
    }


def _parse_goals_section(text: str, source: str) -> dict | None:
    """Parse a single goal section from GOALS.md."""
    lines = text.splitlines()
    name = lines[0].strip() if lines else ""
    metadata: dict = {}

    for line in lines[1:]:
        s = line.strip()
        if s.startswith("- id:"):
            metadata["id"] = s.split(":", 1)[1].strip()
        elif s.startswith("- priority:"):
            metadata["priority"] = int(s.split(":", 1)[1].strip())
        elif s.startswith("- depends_on:"):
            raw = s.split(":", 1)[1].strip()
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                metadata["depends_on"] = (
                    [x.strip() for x in inner.split(",") if x.strip()] if inner else []
                )

    return {
        "id": metadata.get("id", name.lower().replace(" ", "-")),
        "description": name,
        "priority": metadata.get("priority", 50),
        "status": "pending",
        "depends_on": metadata.get("depends_on", []),
        "source_file": source,
    }
