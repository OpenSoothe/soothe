"""Headless execution orchestration."""

import sys
import time
from pathlib import Path

import typer

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon, resolve_socket_path

_DAEMON_FALLBACK_EXIT_CODE = 42
_DAEMON_START_TIMEOUT_S = 10.0
_DAEMON_START_CHECK_INTERVAL_S = 0.2


def _wait_for_daemon_ready(cfg: SootheConfig, *, timeout_s: float = _DAEMON_START_TIMEOUT_S) -> bool:
    """Wait until the daemon's effective Unix socket is accepting connections."""
    sock = resolve_socket_path(cfg)
    start_time = time.time()
    while time.time() - start_time < timeout_s:
        time.sleep(_DAEMON_START_CHECK_INTERVAL_S)
        if _is_socket_ready(sock):
            return True
    return False


def _is_socket_ready(sock: Path) -> bool:
    """Return whether the Unix socket is connectable."""
    return sock.exists() and SootheDaemon._is_socket_live(sock)


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
    if not _is_socket_ready(resolve_socket_path(cfg)):
        typer.echo("[lifecycle] Starting daemon...", err=True)
        from soothe.ux.cli.commands.daemon_cmd import daemon_start

        daemon_start(config=None, foreground=False)

        if not _wait_for_daemon_ready(cfg):
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
