"""Headless execution orchestration."""

import asyncio
import sys
import time

import typer
from soothe_sdk.client import (
    WebSocketClient,
    is_daemon_live,
    request_daemon_shutdown,
    websocket_url_from_config,
)

from soothe_cli.config import CLIConfig

_DAEMON_FALLBACK_EXIT_CODE = 42
_DAEMON_START_WAIT_TIMEOUT = 30.0  # Max time to wait for daemon to become ready


def run_headless(
    cfg: CLIConfig,
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
    from soothe_cli.cli.execution.daemon import run_headless_via_daemon

    # Get WebSocket URL for daemon checks
    ws_url = websocket_url_from_config(cfg)

    # Auto-start daemon if not running (RFC-0013) - WebSocket RPC checks (IG-174 Phase 1)
    async def _check_and_ensure_daemon() -> None:
        """Check daemon status and auto-start if needed."""
        daemon_live = await is_daemon_live(ws_url, timeout=5.0)

        if not daemon_live:
            # Attempt cleanup if stale daemon (connection exists but daemon not responsive)
            try:
                client = WebSocketClient(url=ws_url)
                await client.connect()
                await request_daemon_shutdown(client, timeout=10.0)
                await client.close()
            except Exception:
                pass  # No daemon running or already stopped

            # Start daemon via subprocess (daemon manages its own lifecycle)
            # Invoke daemon entry point without importing daemon modules
            import subprocess

            subprocess.Popen(
                [sys.executable, "-m", "soothe.cli.daemon_main", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for daemon to become fully ready with timeout
            start_time = time.time()
            while time.time() - start_time < _DAEMON_START_WAIT_TIMEOUT:
                daemon_live = await is_daemon_live(ws_url, timeout=2.0)
                if daemon_live:
                    break
                await asyncio.sleep(0.5)
            # Note: We don't fail here - let the connection attempt handle errors
            # This allows tests and edge cases to proceed with mocked daemons

    asyncio.run(_check_and_ensure_daemon())

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
