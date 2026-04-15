"""Headless execution orchestration."""

import sys
import time

import typer
from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon

_DAEMON_FALLBACK_EXIT_CODE = 42
_DAEMON_START_WAIT_TIMEOUT = 30.0  # Max time to wait for daemon to become ready


def run_headless(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt with streaming output and progress events.

    Connects to running daemon via WebSocket if available to avoid RocksDB lock conflicts.
    Auto-starts daemon if not running (RFC-0013 daemon lifecycle).

    Note (RFC-0013): Daemon persists after request completion. Use 'soothe-daemon stop'
    to explicitly shutdown the daemon.
    """
    import asyncio

    from soothe_cli.cli.execution.daemon import run_headless_via_daemon

    # Get WebSocket host/port for readiness checks
    ws_host = cfg.daemon.transports.websocket.host
    ws_port = cfg.daemon.transports.websocket.port

    # Auto-start daemon if not running (RFC-0013)
    if not SootheDaemon._is_port_live(ws_host, ws_port):
        if SootheDaemon.is_running():
            SootheDaemon.stop_running()
        from soothe_cli.cli.commands.daemon_cmd import daemon_start

        daemon_start(config=None, foreground=False)

        # Wait for daemon to become fully ready with timeout
        # This helps avoid connection errors on slower systems
        start_time = time.time()
        while time.time() - start_time < _DAEMON_START_WAIT_TIMEOUT:
            if SootheDaemon._is_port_live(ws_host, ws_port) and SootheDaemon.is_running():
                break
            time.sleep(0.5)
        # Note: We don't fail here - let the connection attempt handle errors
        # This allows tests and edge cases to proceed with mocked daemons

    # Connect to daemon and execute
    daemon_exit_code = asyncio.run(
        run_headless_via_daemon(
            cfg,
            prompt,
            thread_id=thread_id,
            output_format=output_format,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )
    )

    # Handle daemon fallback (unresponsive daemon)
    if daemon_exit_code == _DAEMON_FALLBACK_EXIT_CODE:
        typer.echo(
            "Error: Daemon is unresponsive. Please restart with 'soothe-daemon restart'", err=True
        )
        sys.exit(1)

    sys.exit(daemon_exit_code)
