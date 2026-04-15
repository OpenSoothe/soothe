"""TUI execution mode."""

import sys

import typer

# TODO IG-174 Phase 5: Create CLI-specific config class
# SootheConfig import kept for daemon RPC communication
from soothe.config import SootheConfig


def run_tui(
    cfg: SootheConfig,
    *,
    thread_id: str | None = None,
    config_path: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    try:
        from soothe_cli.tui import run_textual_tui

        run_textual_tui(
            config=cfg,
            autopilot_mode=False,
            thread_id=thread_id,
            config_path=config_path,
            initial_prompt=initial_prompt,
        )
    except ImportError:
        typer.echo(
            "Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'",
            err=True,
        )
        sys.exit(1)
