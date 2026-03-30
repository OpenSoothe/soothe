"""Daemon commands for Soothe CLI."""

import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SOOTHE_HOME
from soothe.ux.core import load_config, setup_logging


def _get_websocket_url(cfg: object) -> str:
    """Get WebSocket URL from configuration."""
    host = cfg.daemon.transports.websocket.host
    port = cfg.daemon.transports.websocket.port
    return f"ws://{host}:{port}"


def _wait_for_daemon_ready(cfg: object, timeout: float = 20.0) -> bool:
    """Wait for protocol-level daemon readiness via WebSocket."""
    from soothe.daemon import WebSocketClient
    from soothe.ux.cli.execution.daemon import _connect_with_retries

    async def _wait() -> bool:
        ws_url = _get_websocket_url(cfg)
        client = WebSocketClient(url=ws_url)
        try:
            await _connect_with_retries(client)
            await client.request_daemon_ready()
            await client.wait_for_daemon_ready(ready_timeout_s=timeout)
        except Exception:
            logger = logging.getLogger(__name__)
            logger.debug("Daemon readiness check failed", exc_info=True)
            return False
        finally:
            await client.close()
        return True

    return asyncio.run(_wait())


def daemon_start(
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
        cmd = [sys.executable, "-m", "soothe.daemon", "--detached"]
        if config:
            cmd.extend(["--config", config])
        log_file = Path(SOOTHE_HOME) / "logs" / "daemon.stderr"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a") as stderr_file:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                start_new_session=True,
            )
        # Wait briefly for daemon to acquire PID lock and write PID file
        for _ in range(30):
            if pid_path().exists():
                break
            time.sleep(0.2)
        # Wait for WebSocket server to be fully ready with retries
        # The daemon needs time to initialize transports after writing PID
        ready = False
        for _attempt in range(10):
            time.sleep(0.5)
            if SootheDaemon.is_running() and _wait_for_daemon_ready(cfg):
                ready = True
                break
        if ready:
            # Use find_pid() which tries multiple methods (PID file, port scan, pgrep)
            pid = SootheDaemon.find_pid() or "?"
            typer.echo(f"Soothe daemon started (PID: {pid})")
        elif SootheDaemon.is_running():
            typer.echo("Soothe daemon started but protocol readiness check failed.", err=True)
        else:
            typer.echo("Soothe daemon failed to start.", err=True)


def daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe.daemon import SootheDaemon

    if SootheDaemon.stop_running():
        typer.echo("Soothe daemon stopped.")
    else:
        typer.echo("No Soothe daemon is running.")


def daemon_status() -> None:
    """Show Soothe daemon status."""
    from soothe.daemon import SootheDaemon, pid_path

    if SootheDaemon.is_running():
        pf = pid_path()
        pid = pf.read_text().strip() if pf.exists() else (SootheDaemon.find_pid() or "?")
        typer.echo(f"Soothe daemon is running (PID: {pid})")
    else:
        typer.echo("Soothe daemon is not running.")


def daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon.

    Stops the running daemon (if any) and starts a new one.

    Examples:
        soothe daemon restart
        soothe daemon restart --config my_config.yml
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
    daemon_start(config=config, foreground=False)


# NOTE: daemon_attach() removed in RFC-0017
# Use 'soothe thread continue --daemon' instead
