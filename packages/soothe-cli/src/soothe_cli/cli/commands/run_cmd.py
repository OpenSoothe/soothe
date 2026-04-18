"""Run command for Soothe CLI."""

import logging
import sys
import time
from pathlib import Path

import typer
from soothe_sdk.client.config import SOOTHE_HOME
from soothe_sdk.utils.logging import resolve_cli_log_level

from soothe_cli.cli.execution import run_headless, run_tui
from soothe_cli.shared import load_config, setup_logging

logger = logging.getLogger(__name__)


def run_impl(
    prompt: str | None,
    config: str | None,
    thread_id: str | None,
    no_tui: bool,  # noqa: FBT001
    autonomous: bool,  # noqa: FBT001
    max_iterations: int | None,
    output_format: str,
) -> None:
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional prompt for headless mode
        config: Deprecated; passed through for ``--config`` compatibility (ignored for
            client settings; see ``load_config``).
        thread_id: Thread ID to resume
        no_tui: Force headless mode
        autonomous: Enable autonomous iteration mode
        max_iterations: Max iterations for autonomous mode
        output_format: Output format (text or jsonl)
    """
    startup_start = time.perf_counter()

    try:
        cfg = load_config(config)
        log_level = resolve_cli_log_level(cfg.verbosity, logging_level=cfg.logging_level)
        log_file = Path(SOOTHE_HOME) / "logs" / "soothe-cli.log"
        setup_logging(log_level, log_file=log_file)

        # PostgreSQL availability check (requires daemon-side config)
        if hasattr(cfg, "protocols") and hasattr(cfg.protocols, "durability"):
            checkpointer = getattr(cfg.protocols.durability, "checkpointer", None)
            if checkpointer == "postgresql":
                logger.info("PostgreSQL checkpointer configured; ensure server is running.")

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("[Startup] ✓ Ready (%.1fms)", startup_elapsed_ms)

        run_start = time.perf_counter()

        if no_tui:
            # Headless mode (force no TUI)
            run_headless(
                cfg,
                prompt or "",
                thread_id=thread_id,
                output_format=output_format,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            # TUI mode (with optional initial prompt)
            run_tui(cfg, thread_id=thread_id, initial_prompt=prompt)

        run_elapsed_s = time.perf_counter() - run_start
        typer.echo(f"Total running time: {run_elapsed_s:.2f}s", err=True)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe_sdk.utils import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
