"""Cron CLI subcommands for RFC-229.

Daemon-backed control surface: manage scheduled jobs via WebSocket.
Requires ``soothed start``.

Commands:
    soothe cron add <text>        # Add scheduled job (natural language)
    soothe cron list              # List scheduled jobs
    soothe cron show <job_id>     # Show job details
    soothe cron cancel <job_id>   # Cancel a job
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from soothe_sdk.client import (
    is_daemon_live,
    websocket_url_from_config,
    ws_command_client_from_config,
)

from soothe_cli.runtime import load_config

console = Console()

app = typer.Typer(help="Manage scheduled cron jobs — natural language scheduled tasks.")


def _require_cron_client():
    """Return a live WebSocket command client or exit."""
    cfg = load_config()
    ws_url = websocket_url_from_config(cfg)
    if not asyncio.run(is_daemon_live(ws_url, timeout=5.0)):
        typer.echo(
            "Error: Daemon not running. Start with 'soothed start'.",
            err=True,
        )
        sys.exit(1)
    return ws_command_client_from_config(cfg)


def _format_next_run(next_run: str) -> str:
    if not next_run:
        return "-"
    try:
        dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        delta = dt - now
        if delta.total_seconds() < 0:
            return "due now"
        if delta.total_seconds() < 3600:
            return f"in {int(delta.total_seconds() / 60)}m"
        if delta.total_seconds() < 86400:
            return f"in {int(delta.total_seconds() / 3600)}h"
        return f"in {int(delta.total_seconds() / 86400)}d"
    except ValueError:
        return next_run[:19]


@app.command("add")
def add_job(
    text: Annotated[str, typer.Argument(help="Natural language schedule and task.")],
    priority: Annotated[
        int | None,
        typer.Option("--priority", "-p", help="Job priority (0-100)."),
    ] = None,
) -> None:
    """Add a scheduled cron job via natural language.

    The daemon extracts schedule semantics via LLM and persists the job.

    Example:
        soothe cron add "in 1 hour remind me to check the deploy"
        soothe cron add "every weekday at 9am send status report" --priority 70
    """
    client = _require_cron_client()
    try:
        result = client.cron_add(text, priority=priority)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    job = result.get("job") or {}
    job_id = job.get("id", "?")
    console.print(
        Panel(
            "\n".join(
                [
                    f"[bold]ID:[/bold] {job_id}",
                    f"[bold]Description:[/bold] {job.get('description', '-')}",
                    f"[bold]Schedule:[/bold] {job.get('schedule_kind', '?')} = {job.get('schedule_value', '?')}",
                    f"[bold]Next Run:[/bold] [yellow]{str(job.get('next_run', ''))[:19]}[/yellow]",
                    f"[bold]Status:[/bold] [green]{job.get('status', 'pending')}[/green]",
                ]
            ),
            title="Scheduled Job Created",
            border_style="green",
        )
    )


@app.command("list")
def list_jobs(
    status: Annotated[
        str | None,
        typer.Option(
            "--status",
            "-s",
            help="Filter by status (pending, running, completed, failed, cancelled).",
        ),
    ] = None,
) -> None:
    """List scheduled cron jobs.

    Shows jobs with their ID, description, status, next run time, and run count.

    Example:
        soothe cron list
        soothe cron list --status pending
    """
    client = _require_cron_client()
    try:
        result = client.cron_list_jobs(status=status)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    jobs = result.get("jobs", [])
    if not jobs:
        console.print("[info]No scheduled jobs found.[/info]")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("Job ID", style="cyan", width=12)
    table.add_column("Description", width=40)
    table.add_column("Status", style="green", width=10)
    table.add_column("Next Run", style="yellow", width=20)
    table.add_column("Runs", justify="right", width=6)

    for job in jobs:
        desc = job.get("description", "")
        if len(desc) > 40:
            desc = desc[:37] + "..."
        table.add_row(
            job.get("id", "?")[:12],
            desc,
            job.get("status", "pending"),
            _format_next_run(job.get("next_run", "")),
            str(job.get("run_count", 0)),
        )

    console.print(table)


@app.command("show")
def show_job(
    job_id: Annotated[str, typer.Argument(help="Job ID to show details for.")],
) -> None:
    """Show details of a scheduled cron job.

    Displays full job information including schedule kind, schedule value,
    end condition, timestamps, and execution history.

    Example:
        soothe cron show abc123def456
    """
    client = _require_cron_client()
    try:
        result = client.cron_show(job_id)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    job = result.get("job")
    if not job:
        typer.echo(f"Error: Job '{job_id}' not found.", err=True)
        sys.exit(1)

    details = [
        f"[bold]ID:[/bold] {job.get('id', '?')}",
        f"[bold]Description:[/bold] {job.get('description', '-')}",
        f"[bold]Status:[/bold] [green]{job.get('status', 'pending')}[/green]",
        f"[bold]Priority:[/bold] {job.get('priority', 50)}",
        f"[bold]Schedule:[/bold] {job.get('schedule_kind', 'once')} = {job.get('schedule_value', '')}",
    ]
    if job.get("end_condition"):
        details.append(f"[bold]End Condition:[/bold] {job['end_condition']}")
    next_run = job.get("next_run", "")
    if next_run:
        details.append(f"[bold]Next Run:[/bold] [yellow]{next_run[:19]}[/yellow]")
    last_run = job.get("last_run")
    if last_run:
        details.append(f"[bold]Last Run:[/bold] {last_run[:19]}")
    details.append(f"[bold]Run Count:[/bold] {job.get('run_count', 0)}")
    created = job.get("created_at", "")
    if created:
        details.append(f"[bold]Created:[/bold] [dim]{created[:19]}[/dim]")

    console.print(Panel("\n".join(details), title=f"Cron Job: {job_id[:12]}", border_style="cyan"))


@app.command("cancel")
def cancel_job(
    job_id: Annotated[str, typer.Argument(help="Job ID to cancel.")],
) -> None:
    """Cancel a scheduled cron job.

    Marks the job as cancelled. Only pending jobs can be cancelled.

    Example:
        soothe cron cancel abc123def456
    """
    client = _require_cron_client()
    try:
        result = client.cron_cancel(job_id)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if result.get("cancelled"):
        console.print(f"[success]Cancelled job: {job_id[:12]}[/success]")
    else:
        typer.echo(f"Error: Could not cancel job '{job_id}'.", err=True)
        sys.exit(1)


__all__ = [
    "app",
    "add_job",
    "list_jobs",
    "show_job",
    "cancel_job",
]
