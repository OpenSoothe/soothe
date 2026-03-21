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
    continue_last: Annotated[
        bool,
        typer.Option("--continue", "-C", help="Continue the most recent thread."),
    ] = False,
    list_threads: Annotated[
        bool,
        typer.Option("--list-threads", help="List all threads and exit."),
    ] = False,
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

        # Handle --list-threads flag
        if list_threads:
            import asyncio

            from soothe.core.runner import SootheRunner

            runner = SootheRunner(cfg)

            async def _list() -> None:
                try:
                    threads = await runner.list_threads()
                    if not threads:
                        typer.echo("No threads.")
                        return
                    typer.echo(f"{'ID':<10}  {'Status':<10}  {'Created':<19}  {'Last Message':<19}")
                    typer.echo("─" * 65)
                    for t in threads:
                        tid = t.get("thread_id", "?")
                        t_status = t.get("status", "?")
                        created = str(t.get("created_at", "?"))[:19]
                        last_msg = str(t.get("updated_at", "?"))[:19]
                        typer.echo(f"{tid:<10}  {t_status:<10}  {created:<19}  {last_msg:<19}")
                finally:
                    # Clean up runner resources to avoid hanging
                    if hasattr(runner, "cleanup"):
                        await runner.cleanup()

            asyncio.run(_list())
            return

        # Resolve thread ID for --continue flag
        thread_id = thread
        if continue_last and not thread_id:
            import asyncio

            from soothe.core.runner import SootheRunner

            runner = SootheRunner(cfg)

            async def _get_last_thread() -> str | None:
                threads = await runner.list_threads()
                if not threads:
                    return None
                # Sort by updated_at descending and get the most recent active thread
                active_threads = [t for t in threads if t.get("status") == "active"]
                if not active_threads:
                    return None
                active_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                return active_threads[0].get("thread_id")

            thread_id = asyncio.run(_get_last_thread())
            if thread_id:
                logger.info("Continuing thread %s", thread_id)

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
