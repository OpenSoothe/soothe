"""Server commands for Soothe CLI."""

import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SOOTHE_HOME
from soothe.ux.core import load_config, setup_logging


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
    from soothe.daemon import SootheDaemon, pid_path, run_daemon

    if SootheDaemon.is_running():
        typer.echo("Soothe daemon is already running.")
        return

    cfg = load_config(config)
    setup_logging(cfg)

    if foreground:
        run_daemon(cfg)
    else:
        cmd = [sys.executable, "-m", "soothe.daemon"]
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
    from soothe.daemon import SootheDaemon

    if SootheDaemon.stop_running():
        typer.echo("Soothe daemon stopped.")
    else:
        typer.echo("No Soothe daemon is running.")


def server_status() -> None:
    """Show Soothe daemon status."""
    from soothe.daemon import SootheDaemon, pid_path

    if SootheDaemon.is_running():
        pf = pid_path()
        pid = pf.read_text().strip() if pf.exists() else "?"
        typer.echo(f"Soothe daemon is running (PID: {pid})")
    else:
        typer.echo("Soothe daemon is not running.")


def server_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon.

    Stops the running daemon (if any) and starts a new one.

    Examples:
        soothe server restart
        soothe server restart --config my_config.yml
    """
    from soothe.daemon import SootheDaemon

    # Stop the daemon if running
    if SootheDaemon.is_running():
        typer.echo("Stopping Soothe daemon...")
        SootheDaemon.stop_running()
        # Wait briefly for the daemon to fully stop
        time.sleep(0.5)

    # Start a new daemon
    typer.echo("Starting Soothe daemon...")
    server_start(config=config, foreground=False)


# NOTE: server_attach() removed in RFC-0017
# Use 'soothe thread continue --daemon' instead
