"""Run command for Soothe CLI."""

import logging
import sys
import time
from pathlib import Path

import typer
from soothe_sdk.client.config import SOOTHE_HOME
from soothe_sdk.utils.logging import resolve_cli_log_level

from soothe_cli.cli.execution import run_headless, run_tui
from soothe_cli.events import load_config, setup_logging

logger = logging.getLogger(__name__)


def run_impl(
    prompt: str | None,
    resume_loop_id: str | None,
    no_tui: bool,  # noqa: FBT001
    autonomous: bool,  # noqa: FBT001
    max_iterations: int | None,
    streaming_enabled: bool | None = None,
    streaming_mode: str | None = None,
    *,
    tui_with_prompt: bool = False,
    config_path: str | None = None,
) -> None:
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional user message; non-empty prompt defaults to a headless
            one-shot run unless ``tui_with_prompt`` is set or a loop is being
            resumed (``resume_loop_id``).
        resume_loop_id: Existing loop id to attach to (optional)
        no_tui: Require headless mode (must include a non-empty prompt)
        autonomous: Enable autonomous iteration mode
        max_iterations: Max iterations for autonomous mode
        streaming_enabled: Override daemon streaming enabled setting (RFC-614)
        streaming_mode: Override daemon streaming mode ('streaming' or 'batch')
        tui_with_prompt: When True with a prompt, open the TUI instead of headless.
    """
    startup_start = time.perf_counter()

    try:
        cfg = load_config(config_path)
        log_level = resolve_cli_log_level(logging_level=cfg.logging_level)
        log_file = Path(SOOTHE_HOME) / "logs" / "cli.log"
        setup_logging(log_level, log_file=log_file)

        # PostgreSQL availability check (requires daemon-side config)
        if hasattr(cfg, "protocols") and hasattr(cfg.protocols, "durability"):
            checkpointer = getattr(cfg.protocols.durability, "checkpointer", None)
            if checkpointer == "postgresql":
                logger.info("PostgreSQL checkpointer configured; ensure server is running.")

        # Apply CLI streaming overrides (RFC-614)
        if streaming_enabled is not None:
            cfg.output_streaming_enabled = streaming_enabled
        if streaming_mode is not None:
            cfg.output_streaming_mode = streaming_mode

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("[Startup] ✓ Ready (%.1fms)", startup_elapsed_ms)

        run_start = time.perf_counter()

        has_prompt = bool(prompt and str(prompt).strip())
        attaching_loop = bool(resume_loop_id and str(resume_loop_id).strip())

        if tui_with_prompt and has_prompt:
            use_headless = False
        elif no_tui and not has_prompt:
            typer.echo(
                "Error: --no-tui requires a non-empty --prompt (-p).",
                err=True,
            )
            sys.exit(1)
        elif no_tui:
            use_headless = True
        else:
            use_headless = has_prompt and not attaching_loop

        if use_headless:
            run_headless(
                cfg,
                str(prompt).strip(),
                resume_loop_id=resume_loop_id,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            run_tui(cfg, resume_loop_id=resume_loop_id, initial_prompt=prompt)

        run_elapsed_s = time.perf_counter() - run_start
        typer.echo(f"Total running time: {run_elapsed_s:.2f}s", err=True)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted. (daemon query cancelled)")
        sys.exit(130)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe_sdk.utils import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)
