"""Headless execution orchestration."""

import sys

import typer

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon

_DAEMON_FALLBACK_EXIT_CODE = 42


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
    Falls back to standalone mode if no daemon is running.
    """
    import asyncio

    from soothe.ux.cli.execution.daemon_runner import run_headless_via_daemon
    from soothe.ux.cli.execution.standalone_runner import run_headless_standalone

    if SootheDaemon.is_running():
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
        if daemon_exit_code != _DAEMON_FALLBACK_EXIT_CODE:
            sys.exit(daemon_exit_code)
        # Daemon unresponsive -- stop it to release locks, then run standalone
        typer.echo("Daemon is unresponsive, stopping it and running standalone...", err=True)
        SootheDaemon.stop_running(timeout=5.0)

    exit_code = asyncio.run(
        run_headless_standalone(
            cfg,
            prompt,
            thread_id=thread_id,
            output_format=output_format,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )
    )
    sys.exit(exit_code)
