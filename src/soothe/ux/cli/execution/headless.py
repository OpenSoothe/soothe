"""Headless execution orchestration."""

import sys
import time

import typer

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon

_DAEMON_FALLBACK_EXIT_CODE = 42
_DAEMON_START_TIMEOUT_S = 10.0
_DAEMON_START_CHECK_INTERVAL_S = 0.2


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

    Connects to running daemon if available to avoid RocksDB lock conflicts.
    Auto-starts daemon if not running (RFC-0013 daemon lifecycle).

    Note (RFC-0013): Daemon persists after request completion. Use 'soothe daemon stop'
    to explicitly shutdown the daemon.
    """
    import asyncio

    from soothe.ux.cli.execution.daemon import run_headless_via_daemon

    # Auto-start daemon if not running (RFC-0013)
    if not SootheDaemon.is_running():
        typer.echo("[lifecycle] Starting daemon...", err=True)
        from soothe.ux.cli.commands.daemon_cmd import daemon_start

        daemon_start(config=None, foreground=False)

        # Wait for daemon to initialize
        start_time = time.time()
        while time.time() - start_time < _DAEMON_START_TIMEOUT_S:
            time.sleep(_DAEMON_START_CHECK_INTERVAL_S)
            if SootheDaemon.is_running():
                break
        else:
            typer.echo("Error: Failed to start daemon within timeout", err=True)
            sys.exit(1)

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
        typer.echo("Error: Daemon is unresponsive. Please restart with 'soothe daemon restart'", err=True)
        sys.exit(1)

    sys.exit(daemon_exit_code)
