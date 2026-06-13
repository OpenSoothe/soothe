"""Headless execution orchestration."""

import asyncio
import sys

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
    resume_loop_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt with streaming output and progress events.

    Connects to running daemon via WebSocket if available to avoid database lock conflicts.
    Auto-starts daemon if not running (RFC-0013 daemon lifecycle).

    Note (RFC-0013): Daemon persists after request completion. Use 'soothed stop'
    to explicitly shutdown the daemon.
    """
    from soothe_cli.cli.execution.daemon import run_headless_via_daemon

    # Get WebSocket URL for daemon checks
    ws_url = websocket_url_from_config(cfg)

    # Auto-start daemon if not running (RFC-0013) - WebSocket RPC checks (IG-174 Phase 1)
    async def _run_headless_pipeline() -> int:
        """Ensure daemon is reachable, then run the headless daemon session."""
        # Check if daemon is live and ready (IG-489: wait for readiness, not just port-live)
        daemon_live = await is_daemon_live(
            ws_url, timeout=5.0, wait_for_ready=True, ready_timeout=30.0
        )

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
                [sys.executable, "-m", "soothe_daemon", "--detached"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for daemon to become fully ready with timeout (IG-489)
            daemon_live = await is_daemon_live(
                ws_url, timeout=2.0, wait_for_ready=True, ready_timeout=_DAEMON_START_WAIT_TIMEOUT
            )
            # Note: We don't fail here - let the connection attempt handle errors
            # This allows tests and edge cases to proceed with mocked daemons

        return await run_headless_via_daemon(
            cfg,
            prompt,
            resume_loop_id=resume_loop_id,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )

    daemon_exit_code = asyncio.run(_run_headless_pipeline())

    # Handle daemon fallback (unresponsive daemon)
    if daemon_exit_code == _DAEMON_FALLBACK_EXIT_CODE:
        typer.echo("Error: Daemon is unresponsive. Please restart with 'soothed restart'", err=True)
        sys.exit(1)

    sys.exit(daemon_exit_code)
