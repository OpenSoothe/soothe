"""Run command for Soothe CLI."""

import logging
import sys
import time
from typing import Literal

import typer

from soothe.utils.postgres import check_postgres_available
from soothe.ux.cli.execution import run_headless, run_tui
from soothe.ux.core import load_config, setup_logging

logger = logging.getLogger(__name__)


def run_impl(
    prompt: str | None,
    config: str | None,
    thread_id: str | None,
    no_tui: bool,  # noqa: FBT001
    autonomous: bool,  # noqa: FBT001
    max_iterations: int | None,
    output_format: str,
    verbosity: Literal["minimal", "normal", "detailed", "debug"] | None,
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
        setup_logging(cfg)

        # Check PostgreSQL availability if checkpointer is postgresql
        if cfg.protocols.durability.checkpointer == "postgresql" and not check_postgres_available():
            logger.warning(
                "PostgreSQL checkpointer configured but server not responding at localhost:5432. "
                "Start pgvector: docker-compose up -d"
            )

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("Startup completed in %.1fms", startup_elapsed_ms)

        if prompt or no_tui:
            run_headless(
                cfg,
                prompt or "",
                thread_id=thread_id,
                output_format=output_format,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            run_tui(cfg, thread_id=thread_id, config_path=config)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
