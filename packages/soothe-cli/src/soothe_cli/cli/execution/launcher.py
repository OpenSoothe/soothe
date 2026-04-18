"""TUI execution mode."""

import sys

import typer

from soothe_cli.config import CLIConfig


def run_tui(
    cfg: CLIConfig,
    *,
    thread_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    try:
        from soothe_cli.tui import run_textual_tui

        run_textual_tui(
            config=cfg,
            thread_id=thread_id,
            initial_prompt=initial_prompt,
        )
    except ImportError:
        typer.echo(
            "Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'",
            err=True,
        )
        sys.exit(1)
