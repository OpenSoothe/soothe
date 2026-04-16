"""Run command for Soothe CLI."""

import logging
import sys
import time
from pathlib import Path
from typing import Literal

import typer
from soothe_sdk import SOOTHE_HOME, VERBOSITY_TO_LOG_LEVEL

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
    verbosity: Literal["quiet", "minimal", "normal", "detailed", "debug"] | None,
) -> None:
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional prompt for headless mode
        config: Path to config file
        thread_id: Thread ID to resume
        no_tui: Force headless mode
        autonomous: Enable autonomous iteration mode
        max_iterations: Max iterations for autonomous mode
        output_format: Output format (text or jsonl)
        verbosity: Verbosity level
    """
    startup_start = time.perf_counter()

    try:
        cfg = load_config(config)
        if verbosity is not None:
            logging_config = cfg.logging.model_copy(update={"verbosity": verbosity})
            cfg = cfg.model_copy(update={"logging": logging_config})
        log_level = VERBOSITY_TO_LOG_LEVEL.get(cfg.logging.verbosity, "INFO")
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
            run_tui(cfg, thread_id=thread_id, config_path=config, initial_prompt=prompt)

        run_elapsed_s = time.perf_counter() - run_start
        typer.echo(f"Total running time: {run_elapsed_s:.2f}s", err=True)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe_sdk import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
