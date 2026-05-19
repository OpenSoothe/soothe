"""Daemon management CLI - manage Soothe daemon server."""

from __future__ import annotations

from soothe_daemon.bootstrap_env import bootstrap_dotenv, load_dotenv_adjacent_to_yaml

bootstrap_dotenv()

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe_daemon.config import SootheDaemonConfig, default_daemon_config_path
from soothe_daemon.entrypoint import run_daemon
from soothe_daemon.health.checker import HealthChecker
from soothe_daemon.health.formatters import format_json, format_markdown, format_text
from soothe_daemon.health.models import CheckStatus
from soothe_daemon.paths import pid_path
from soothe_daemon.server import SootheDaemon

app = typer.Typer(
    name="soothed",
    help="Soothe daemon management - start/stop/status/doctor/warmup",
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
    daemon_cfg = _load_daemon_config(config)
    _apply_dotenv_for_daemon_paths(daemon_cfg, config)
    cfg = daemon_cfg.load_soothe_config()

    if SootheDaemon.is_running():
        pid = SootheDaemon.find_pid()
        pid_info = f" (PID: {pid})" if pid else ""
        typer.echo(f"Daemon is already running{pid_info}.")
        raise typer.Exit(code=1)

    if foreground:
        from soothe.logging import setup_logging

        from soothe_daemon.logging import _daemon_log_level_from_soothe_config, setup_daemon_logging

        typer.echo("Starting daemon in foreground...")
        setup_logging(cfg, foreground=True)
        setup_daemon_logging(level=_daemon_log_level_from_soothe_config(cfg), foreground=True)
        run_daemon(cfg, daemon_config=daemon_cfg, detached=False)
        return

    command = [sys.executable, "-m", "soothe_daemon", "--detached"]
    if config:
        command.extend(["--config", config])

    try:
        subprocess.Popen(  # noqa: S603
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(SOOTHE_HOME).expanduser()),
        )
    except Exception as exc:
        typer.echo(f"Failed to start daemon: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Starting daemon...")
    # Daemon initialization can take several seconds (runner + transport startup).
    for _ in range(120):
        if SootheDaemon.is_running():
            pid = SootheDaemon.find_pid()

            pid_str = f"PID: {pid}" if pid else "PID: unknown"
            typer.echo(f"Daemon started successfully ({pid_str}, ws://127.0.0.1:8765)")
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

    typer.echo("Daemon status: running")

    # Read PID file directly first (fast), fall back to find_pid() only if needed
    pf = pid_path()
    pid: int | None = None
    if pf.exists():
        import os

        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            pid = SootheDaemon.find_pid()
    else:
        pid = SootheDaemon.find_pid()

    if pid:
        typer.echo(f"PID: {pid}")

    # Resolve WebSocket address from daemon config
    try:
        cfg = SootheDaemonConfig()
        ws_host = cfg.transports.websocket.host
        ws_port = cfg.transports.websocket.port
    except Exception:
        ws_host, ws_port = "127.0.0.1", 8765
    typer.echo(f"WebSocket: ws://{ws_host}:{ws_port}")


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

    daemon_cfg: SootheDaemonConfig | None = None
    cfg: SootheConfig | None = None
    try:
        daemon_cfg = _load_daemon_config(config)
        _apply_dotenv_for_daemon_paths(daemon_cfg, config)
        cfg = daemon_cfg.load_soothe_config()
    except Exception as exc:
        if config:
            typer.echo(f"Failed to load daemon config '{config}': {exc}", err=True)
            raise typer.Exit(code=1) from exc

    if daemon_cfg is None:
        try:
            daemon_cfg = SootheDaemonConfig()
        except Exception:
            daemon_cfg = None
    if cfg is None:
        try:
            cfg = SootheConfig()
        except Exception:
            # Keep doctor usable for baseline checks even when config parsing fails.
            cfg = None

    checker = HealthChecker(cfg, daemon_config=daemon_cfg)
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


@app.command("warmup")
def warmup_cache(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed progress."),
    ] = False,
) -> None:
    """Pre-download embedding model cache for faster startup.

    Downloads the sentence_transformers embedding model to
    ~/.cache/soothe/models/huggingface/ for sharing across main daemon
    and worker processes.

    Run this before starting the daemon for faster first-query response.
    """
    from soothe.utils.similarity import async_warmup_embedding_model, hf_embedding_cache_dir

    cache_dir = hf_embedding_cache_dir()
    typer.echo(f"Warming up embedding model cache at {cache_dir}...")

    async def _warmup() -> bool:
        return await async_warmup_embedding_model()

    success = asyncio.run(_warmup())

    if success:
        typer.echo("Model cache warmed up successfully.")
        if verbose:
            typer.echo(f"Cache directory: {cache_dir}")
    else:
        typer.echo(
            "Model cache warmup failed (sentence_transformers may not be installed).",
            err=True,
        )
        typer.echo(
            "Install with: pip install 'soothe[semantic_similarity]'",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    parent_ctx = ctx.parent if ctx.parent is not None else ctx
    typer.echo(parent_ctx.get_help())


def _apply_dotenv_for_daemon_paths(
    daemon_cfg: SootheDaemonConfig, explicit_daemon_yaml: str | None
) -> None:
    """Load ``.env`` beside daemon YAML and beside ``soothe_config_path`` before parsing agent config."""
    paths: list[str | Path | None] = [explicit_daemon_yaml]
    if explicit_daemon_yaml is None:
        dp = default_daemon_config_path()
        if dp.is_file():
            paths.append(dp)
    load_dotenv_adjacent_to_yaml(*paths, daemon_cfg.soothe_config_path)


def _load_daemon_config(config_path: str | None) -> SootheDaemonConfig:
    """Load ``SootheDaemonConfig`` from explicit path or default location.

    Args:
        config_path: Optional path passed from CLI (``daemon_config.yml``).

    Returns:
        Parsed ``SootheDaemonConfig`` (defaults if no file found).
    """
    if config_path:
        return SootheDaemonConfig.from_yaml_file(config_path)

    default_config = default_daemon_config_path()
    if default_config.exists():
        return SootheDaemonConfig.from_yaml_file(default_config)
    return SootheDaemonConfig()


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
