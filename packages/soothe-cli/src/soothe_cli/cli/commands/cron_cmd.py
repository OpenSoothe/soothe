"""Cron CLI subcommands for RFC-229.

Daemon-backed control surface: manage scheduled jobs via HTTP REST.
Requires ``soothed start``.

Commands:
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
)

from soothe_cli.runtime import load_config

console = Console()

app = typer.Typer(help="Manage scheduled cron jobs — natural language scheduled tasks.")


def _require_daemon_http() -> tuple[str, str]:
    """Return WebSocket URL and HTTP base URL, or exit if daemon not running."""
    cfg = load_config()
    ws_url = websocket_url_from_config(cfg)
    if not asyncio.run(is_daemon_live(ws_url, timeout=5.0)):
        typer.echo(
            "Error: Daemon not running. Start with 'soothed start'.",
            err=True,
        )
        sys.exit(1)

    # Derive HTTP URL from WebSocket URL
    if ws_url.startswith("wss://"):
        http_url = "https://" + ws_url[len("wss://") :]
    elif ws_url.startswith("ws://"):
        http_url = "http://" + ws_url[len("ws://") :]
    else:
        http_url = ws_url

    return ws_url, http_url


def _http_request(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Make HTTP request to daemon REST API."""
    import json
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        typer.echo(f"Error: HTTP {exc.code} - {detail}", err=True)
        sys.exit(1)
    except urllib.error.URLError as exc:
        typer.echo(f"Error: Cannot reach daemon - {exc.reason}", err=True)
        sys.exit(1)


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
    ws_url, http_url = _require_daemon_http()

    params = {}
    if status:
        params["status"] = status

    query = "&".join(f"{k}={v}" for k, v in params.items())
    path = f"/api/v1/cron/jobs?{query}" if query else "/api/v1/cron/jobs"

    result = _http_request(http_url, "GET", path)
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

        next_run = job.get("next_run", "")
        if next_run:
            # Parse ISO datetime and format relative
            try:
                dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
                now = datetime.now(dt.tzinfo)
                delta = dt - now
                if delta.total_seconds() < 0:
                    next_run_str = "due now"
                elif delta.total_seconds() < 3600:
                    mins = int(delta.total_seconds() / 60)
                    next_run_str = f"in {mins}m"
                elif delta.total_seconds() < 86400:
                    hrs = int(delta.total_seconds() / 3600)
                    next_run_str = f"in {hrs}h"
                else:
                    days = int(delta.total_seconds() / 86400)
                    next_run_str = f"in {days}d"
            except ValueError:
                next_run_str = next_run[:19]
        else:
            next_run_str = "-"

        table.add_row(
            job.get("id", "?")[:12],
            desc,
            job.get("status", "pending"),
            next_run_str,
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
    ws_url, http_url = _require_daemon_http()

    result = _http_request(http_url, "GET", f"/api/v1/cron/jobs/{job_id}")
    job = result.get("job")

    if not job:
        typer.echo(f"Error: Job '{job_id}' not found.", err=True)
        sys.exit(1)

    # Build details panel
    details = []
    details.append(f"[bold]ID:[/bold] {job.get('id', '?')}")
    details.append(f"[bold]Description:[/bold] {job.get('description', '-')}")
    details.append(f"[bold]Status:[/bold] [green]{job.get('status', 'pending')}[/green]")
    details.append(f"[bold]Priority:[/bold] {job.get('priority', 50)}")

    # Schedule info
    schedule_kind = job.get("schedule_kind", "once")
    schedule_value = job.get("schedule_value", "")
    details.append(f"[bold]Schedule:[/bold] {schedule_kind} = {schedule_value}")

    if job.get("end_condition"):
        details.append(f"[bold]End Condition:[/bold] {job['end_condition']}")

    # Timestamps
    next_run = job.get("next_run", "")
    if next_run:
        details.append(f"[bold]Next Run:[/bold] [yellow]{next_run[:19]}[/yellow]")

    last_run = job.get("last_run")
    if last_run:
        details.append(f"[bold]Last Run:[/bold] {last_run[:19]}")

    details.append(f"[bold]Run Count:[/bold] {job.get('run_count', 0)}")

    # Created/Updated
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
    ws_url, http_url = _require_daemon_http()

    result = _http_request(http_url, "DELETE", f"/api/v1/cron/jobs/{job_id}")

    if result.get("cancelled"):
        console.print(f"[success]Cancelled job: {job_id[:12]}[/success]")
    else:
        typer.echo(f"Error: Could not cancel job '{job_id}'.", err=True)
        sys.exit(1)


__all__ = [
    "app",
    "list_jobs",
    "show_job",
    "cancel_job",
]
