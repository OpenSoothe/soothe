"""Attach command for Soothe CLI."""

import sys
from typing import Annotated, Literal

import typer

from soothe.cli.core import load_config
from soothe.cli.daemon import SootheDaemon


def attach(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    progress_verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--progress-verbosity",
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="Thread ID to resume."),
    ] = None,
) -> None:
    """Attach the TUI to an already-running Soothe daemon."""
    if not SootheDaemon.is_running():
        typer.echo("Error: No Soothe daemon is running. Use 'soothe run' or 'soothe server start'.", err=True)
        sys.exit(1)

    cfg = load_config(config)
    if progress_verbosity is not None:
        logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
        cfg = cfg.model_copy(update={"logging": logging_config})
    try:
        from soothe.cli.tui import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id, config_path=config)
    except ImportError:
        typer.echo("Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'", err=True)
        sys.exit(1)
