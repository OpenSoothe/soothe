"""Daemon management CLI - manage Soothe daemon server."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.daemon.entrypoint import run_daemon
from soothe.daemon.health.checker import HealthChecker
from soothe.daemon.health.formatters import format_json, format_markdown, format_text
from soothe.daemon.health.models import CheckStatus
from soothe.daemon.server import SootheDaemon

app = typer.Typer(
    name="soothed",
    help="Soothe daemon management - start/stop/status/doctor",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Soothe daemon server - agent runtime with WebSocket/HTTP transport."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("start")
def daemon_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon server."""
    cfg = _load_config(config)

    if SootheDaemon.is_running():
        pid = SootheDaemon.find_pid()
        pid_info = f" (PID: {pid})" if pid else ""
        typer.echo(f"Daemon is already running{pid_info}.")
        raise typer.Exit(code=1)

    if foreground:
        from soothe.logging import setup_logging

        typer.echo("Starting daemon in foreground...")
        setup_logging(cfg, foreground=True)
        run_daemon(cfg, detached=False)
        return

    command = [sys.executable, "-m", "soothe.daemon", "--detached"]
    if config:
        command.extend(["--config", config])

    try:
        subprocess.Popen(  # noqa: S603
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=Path.cwd(),
        )
    except Exception as exc:
        typer.echo(f"Failed to start daemon: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Starting daemon...")
    # Daemon initialization can take several seconds (runner + transport startup).
    for _ in range(120):
        if SootheDaemon.is_running():
            pid = SootheDaemon.find_pid()
            typer.echo("Daemon started successfully")
            if pid:
                typer.echo(f"PID: {pid}")
            typer.echo(f"Socket: {Path(SOOTHE_HOME).expanduser() / 'soothe.sock'}")
            typer.echo("Status: running")
            return
        time.sleep(0.1)

    typer.echo("Daemon process was launched but did not become ready in time.", err=True)
    raise typer.Exit(code=1)


@app.command("stop")
def daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    pid = SootheDaemon.find_pid()
    if pid:
        typer.echo(f"Stopping daemon (PID: {pid})...")
    else:
        typer.echo("Stopping daemon...")

    if not SootheDaemon.stop_running():
        typer.echo("No running daemon found.")
        raise typer.Exit(code=1)

    typer.echo("Daemon stopped successfully")


@app.command("status")
def daemon_status() -> None:
    """Show soothed status."""
    running = SootheDaemon.is_running()
    if not running:
        typer.echo("Daemon status: stopped")
        return

    pid = SootheDaemon.find_pid()
    typer.echo("Daemon status: running")
    if pid:
        typer.echo(f"PID: {pid}")
    typer.echo(f"Socket: {Path(SOOTHE_HOME).expanduser() / 'soothe.sock'}")


@app.command("restart")
def daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon."""
    if SootheDaemon.is_running():
        typer.echo("Stopping existing daemon...")
        if not SootheDaemon.stop_running():
            typer.echo("Failed to stop running daemon.", err=True)
            raise typer.Exit(code=1)

    daemon_start(config=config, foreground=False)


@app.command("doctor")
def doctor(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
    categories: Annotated[
        list[str] | None,
        typer.Option(
            "--category",
            help="Health check category to include. Repeat to include multiple.",
        ),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            help="Health check category to skip. Repeat to exclude multiple.",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Report output format: text, json, or markdown.",
            case_sensitive=False,
        ),
    ] = "text",
    output_path: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write report to file instead of stdout."),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable ANSI color in text output."),
    ] = False,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help="Exit non-zero on threshold: never, warning, or error.",
            case_sensitive=False,
        ),
    ] = "error",
) -> None:
    """Run comprehensive health checks."""
    format_key = output_format.lower()
    fail_key = fail_on.lower()
    if format_key not in {"text", "json", "markdown"}:
        typer.echo(
            f"Invalid format '{output_format}'. Expected one of: text, json, markdown.",
            err=True,
        )
        raise typer.Exit(code=2)
    if fail_key not in {"never", "warning", "error"}:
        typer.echo(
            f"Invalid fail-on '{fail_on}'. Expected one of: never, warning, error.",
            err=True,
        )
        raise typer.Exit(code=2)

    cfg: SootheConfig | None = None
    try:
        cfg = _load_config(config) if config else _load_config(None)
    except Exception as exc:
        if config:
            typer.echo(f"Failed to load config '{config}': {exc}", err=True)
            raise typer.Exit(code=1) from exc
    if cfg is None and not config:
        try:
            cfg = SootheConfig()
        except Exception:
            # Keep doctor usable for baseline checks even when config parsing fails.
            cfg = None
    checker = HealthChecker(cfg)
    report = asyncio.run(checker.run_all_checks(categories=categories, exclude=exclude))

    if format_key == "json":
        rendered = format_json(report)
    elif format_key == "markdown":
        rendered = format_markdown(report)
    else:
        rendered = format_text(report, use_color=not no_color)

    if output_path:
        output_file = Path(output_path).expanduser()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(rendered)
        typer.echo(f"Health report written to {output_file}")
    else:
        typer.echo(rendered)

    if fail_key == "warning" and _status_meets_or_exceeds(
        report.overall_status, CheckStatus.WARNING
    ):
        raise typer.Exit(code=1)
    if fail_key == "error" and _status_meets_or_exceeds(report.overall_status, CheckStatus.ERROR):
        raise typer.Exit(code=1)


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    parent_ctx = ctx.parent if ctx.parent is not None else ctx
    typer.echo(parent_ctx.get_help())


def _load_config(config_path: str | None) -> SootheConfig | None:
    """Load daemon config from explicit path or default location.

    Args:
        config_path: Optional path passed from CLI.

    Returns:
        Parsed `SootheConfig` if found, otherwise None.
    """
    if config_path:
        return SootheConfig.from_yaml_file(config_path)

    default_config = Path(SOOTHE_HOME) / "config" / "config.yml"
    if default_config.exists():
        return SootheConfig.from_yaml_file(str(default_config))
    return None


def _status_meets_or_exceeds(status: CheckStatus, threshold: CheckStatus) -> bool:
    """Return True when status severity is at or above the threshold."""
    severity = {
        CheckStatus.OK: 0,
        CheckStatus.INFO: 1,
        CheckStatus.SKIPPED: 2,
        CheckStatus.WARNING: 3,
        CheckStatus.ERROR: 4,
    }
    return severity[status] >= severity[threshold]


if __name__ == "__main__":
    app()
