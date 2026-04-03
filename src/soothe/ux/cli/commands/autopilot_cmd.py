"""Autopilot CLI subcommands for RFC-204.

CLI is a control surface — no streaming output. Users submit tasks
and check status; real-time monitoring is via TUI/daemon.
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="Autopilot mode — long-running autonomous agent control.")


@app.command("run")
def run(
    prompt: str = typer.Argument(..., help="Task for autonomous execution."),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to configuration file."),
    max_iterations: int | None = typer.Option(None, "--max-iterations", help="Maximum autonomous iterations."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or jsonl."),
) -> None:
    """Run autonomous agent loop for complex tasks.

    Autopilot mode executes tasks autonomously without requiring user interaction.
    The agent operates in headless mode (no TUI) and outputs progress to stdout.
    """
    from soothe.ux.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        config=config,
        thread_id=None,
        no_tui=True,
        autonomous=True,
        max_iterations=max_iterations,
        output_format=output_format,
        verbosity=None,
    )


@app.command("submit")
def submit(
    task: str = typer.Argument(..., help="Task description."),
    priority: int = typer.Option(50, "--priority", "-p", help="Goal priority (0-100)."),
) -> None:
    """Submit a new task to autopilot.

    Writes a markdown task file to the autopilot inbox.
    """
    from datetime import UTC, datetime

    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"TASK-{timestamp}.md"
    fpath = inbox_dir / filename

    fpath.write_text(f"---\ntype: task_submit\npriority: {priority}\n---\n\n{task}\n")
    typer.echo(f"Task submitted: {fpath}")
    typer.echo(f"  Priority: {priority}")


@app.command("status")
def status() -> None:
    """Show overall autopilot state."""
    from soothe.config import SOOTHE_HOME

    autopilot_dir = SOOTHE_HOME / "autopilot"
    state_file = autopilot_dir / "status.json"

    if not autopilot_dir.exists():
        typer.echo("Autopilot not configured. Run 'soothe autopilot submit' to start.")
        return

    if state_file.exists():
        import json

        data = json.loads(state_file.read_text())
        state = data.get("state", "unknown")
        typer.echo(f"Autopilot state: {state}")

        if "active_goals" in data:
            typer.echo(f"Active goals: {len(data['active_goals'])}")
    else:
        typer.echo("Autopilot: idle (no status file)")

    # Check inbox for pending tasks
    inbox_dir = autopilot_dir / "inbox"
    if inbox_dir.exists():
        pending = list(inbox_dir.glob("*.md"))
        if pending:
            typer.echo(f"Pending inbox tasks: {len(pending)}")


@app.command("list")
def list_goals(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List all goals."""
    from soothe.config import SOOTHE_HOME

    autopilot_dir = SOOTHE_HOME / "autopilot"
    goals = _discover_goals(autopilot_dir)

    if not goals:
        typer.echo("No goals found.")
        return

    for g in goals:
        if status_filter and g.get("status", "") != status_filter:
            continue
        sid = g.get("id", "?")[:8]
        sdesc = g.get("description", "")[:60]
        sstat = g.get("status", "pending")
        spri = g.get("priority", 50)
        typer.echo(f"  [{sid}] {sstat:10s} pri={spri:3d}  {sdesc}")


@app.command("goal")
def show_goal(
    goal_id: str = typer.Argument(..., help="Goal ID to show details for."),
) -> None:
    """Show details for a specific goal."""
    from soothe.config import SOOTHE_HOME

    autopilot_dir = SOOTHE_HOME / "autopilot"
    goals = _discover_goals(autopilot_dir)

    found = None
    for g in goals:
        if g.get("id", "").startswith(goal_id) or goal_id in g.get("id", ""):
            found = g
            break

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
    """Cancel a goal (remove from inbox if pending)."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    if not inbox_dir.exists():
        typer.echo("No inbox to cancel from.")
        return

    # Remove matching inbox file
    removed = 0
    for f in inbox_dir.glob("*.md"):
        if goal_id in f.stem:
            f.unlink()
            removed += 1
            typer.echo(f"Removed: {f.name}")

    if removed == 0:
        typer.echo(f"No matching inbox tasks for '{goal_id}'.")
    else:
        typer.echo(f"Cancelled {removed} task(s).")


@app.command("approve")
def approve_goal(
    goal_id: str = typer.Argument(..., help="Goal ID to approve."),
) -> None:
    """Approve a MUST-confirmation goal."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Create approval marker
    approval = inbox_dir / f"APPROVE-{goal_id}.md"
    approval.write_text(f"---\ntype: approve\ngoal_id: {goal_id}\n---\n\nApproved.\n")
    typer.echo(f"Goal {goal_id} approved.")


@app.command("reject")
def reject_goal(
    goal_id: str = typer.Argument(..., help="Goal ID to reject."),
) -> None:
    """Reject a proposed goal."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    rejection = inbox_dir / f"REJECT-{goal_id}.md"
    rejection.write_text(f"---\ntype: reject\ngoal_id: {goal_id}\n---\n\nRejected.\n")
    typer.echo(f"Goal {goal_id} rejected.")


@app.command("wake")
def wake() -> None:
    """Exit dreaming mode — resume active execution."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    signal = inbox_dir / "WAKE.md"
    signal.write_text("---\ntype: signal_resume\n---\n\nWake signal.\n")
    typer.echo("Wake signal sent. Autopilot will exit dreaming mode.")


@app.command("dream")
def dream() -> None:
    """Force enter dreaming mode."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    signal = inbox_dir / "DREAM.md"
    signal.write_text("---\ntype: signal_interrupt\n---\n\nDream signal.\n")
    typer.echo("Dream signal sent. Autopilot will enter dreaming mode.")


@app.command("inbox")
def view_inbox(
    limit: int = typer.Option(10, "--limit", "-n", help="Max tasks to show."),
) -> None:
    """View pending inbox tasks."""
    from soothe.config import SOOTHE_HOME

    inbox_dir = SOOTHE_HOME / "autopilot" / "inbox"
    if not inbox_dir.exists():
        typer.echo("Inbox is empty.")
        return

    tasks = sorted(inbox_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not tasks:
        typer.echo("Inbox is empty.")
        return

    typer.echo(f"Pending tasks ({len(tasks)}):")
    for f in tasks[:limit]:
        content = f.read_text()
        # Extract description from body
        desc = ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                desc = stripped[2:]
                break
            if stripped.startswith(("--", "type:", "priority:")):
                continue
            if stripped:
                desc = stripped[:80]
                break
        if not desc:
            desc = "(no description)"
        typer.echo(f"  {f.name:30s}  {desc}")

    if len(tasks) > limit:
        typer.echo(f"  ... and {len(tasks) - limit} more")


def _discover_goals(autopilot_dir: Path) -> list[dict]:
    """Parse goals from GOAL.md/GOALS.md files for CLI display.

    This is a simple parser for CLI use — not the full engine.
    """
    import re

    goals = []

    # Check GOAL.md
    goal_file = autopilot_dir / "GOAL.md"
    if goal_file.exists():
        g = _parse_single_goal(goal_file.read_text(), str(goal_file))
        if g:
            return [g]

    # Check GOALS.md
    goals_file = autopilot_dir / "GOALS.md"
    if goals_file.exists():
        text = goals_file.read_text()
        for section in re.split(r"## Goal:", text)[1:]:
            g = _parse_goals_section(section.strip(), str(goals_file))
            if g:
                goals.append(g)

    # Check goals/ subdirectories
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
        "description": desc or body[:100],
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
                metadata["depends_on"] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []

    return {
        "id": metadata.get("id", name.lower().replace(" ", "-")),
        "description": name,
        "priority": metadata.get("priority", 50),
        "status": "pending",
        "depends_on": metadata.get("depends_on", []),
        "source_file": source,
    }
