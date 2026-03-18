"""Run command for Soothe CLI."""

import logging
import sys
import time
from typing import Annotated, Literal

import typer

from soothe.cli.core import load_config, migrate_rocksdb_to_data_subfolder, setup_logging
from soothe.cli.execution import check_postgres_available, run_headless, run_tui

logger = logging.getLogger(__name__)


def run(
    prompt: Annotated[
        str | None,
        typer.Argument(help="Prompt to send to the agent. Omit for interactive TUI."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
    thread: Annotated[
        str | None,
        typer.Option("--thread", "-t", help="Thread ID to resume."),
    ] = None,
    *,
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    autonomous: Annotated[
        bool,
        typer.Option("--autonomous", "-a", help="Enable autonomous iteration mode."),
    ] = False,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Max iterations for autonomous mode."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
    progress_verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--progress-verbosity",
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
) -> None:
    """Run the Soothe agent with a prompt or in interactive TUI mode."""
    startup_start = time.perf_counter()

    try:
        cfg = load_config(config)
        if progress_verbosity is not None:
            logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
            cfg = cfg.model_copy(update={"logging": logging_config})
        setup_logging(cfg)
        migrate_rocksdb_to_data_subfolder()

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
                thread_id=thread,
                output_format=output_format,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            run_tui(cfg, thread_id=thread, config_path=config)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
