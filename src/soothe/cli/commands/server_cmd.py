"""Server commands for Soothe CLI."""

import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from soothe.cli.core import load_config, setup_logging
from soothe.config import SOOTHE_HOME


def server_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon, pid_path, run_daemon

    if SootheDaemon.is_running():
        typer.echo("Soothe daemon is already running.")
        return

    cfg = load_config(config)
    setup_logging(cfg)

    if foreground:
        run_daemon(cfg)
    else:
        cmd = [sys.executable, "-m", "soothe.cli.daemon"]
        if config:
            cmd.extend(["--config", config])
        log_file = Path(SOOTHE_HOME) / "logs" / "daemon.stderr"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a") as stderr_file:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                start_new_session=True,
            )
        # Wait briefly for daemon to acquire PID lock and write PID file
        for _ in range(30):
            if pid_path().exists():
                break
            time.sleep(0.2)
        if SootheDaemon.is_running():
            pid = pid_path().read_text().strip()
            typer.echo(f"Soothe daemon started in background (PID: {pid}).")
        else:
            typer.echo("Soothe daemon started in background.")


def server_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon

    if SootheDaemon.stop_running():
        typer.echo("Soothe daemon stopped.")
    else:
        typer.echo("No Soothe daemon is running.")


def server_status() -> None:
    """Show Soothe daemon status."""
    from soothe.cli.daemon import SootheDaemon, pid_path

    if SootheDaemon.is_running():
        pf = pid_path()
        pid = pf.read_text().strip() if pf.exists() else "?"
        typer.echo(f"Soothe daemon is running (PID: {pid})")
    else:
        typer.echo("Soothe daemon is not running.")


def server_attach(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="Thread ID to resume."),
    ] = None,
    progress_verbosity: Annotated[
        str | None,
        typer.Option("--progress-verbosity", help="Progress detail level."),
    ] = None,
) -> None:
    """Attach TUI to running daemon.

    Examples:
        soothe server attach
        soothe server attach --thread-id abc123
    """
    from soothe.cli.core import load_config
    from soothe.cli.daemon import SootheDaemon

    if not SootheDaemon.is_running():
        typer.echo("Error: No daemon running. Use 'soothe server start'.", err=True)
        sys.exit(1)

    cfg = load_config(config)
    if progress_verbosity is not None:
        logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
        cfg = cfg.model_copy(update={"logging": logging_config})

    try:
        from soothe.cli.tui import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id, config_path=config)
    except ImportError:
        typer.echo("Error: Textual is required for TUI. Install: pip install 'textual>=0.40.0'", err=True)
        sys.exit(1)
