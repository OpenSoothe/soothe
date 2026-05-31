"""TUI execution mode."""

import sys
from typing import Any

import typer

from soothe_cli.config import CLIConfig

# Module-level storage for the last TUI result (for post-exit tip display)
# Use Any to avoid circular import issues at module load time
_last_app_result: Any = None


def get_last_app_result() -> Any:
    """Return the result from the most recent TUI run.

    Returns:
        The AppResult from the last TUI session, or None if TUI hasn't run.
    """
    return _last_app_result


def run_tui(
    cfg: CLIConfig,
    *,
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    global _last_app_result
    try:
        from soothe_cli.tui import run_textual_tui

        result = run_textual_tui(
            config=cfg,
            resume_loop_id=resume_loop_id,
            initial_prompt=initial_prompt,
        )
        _last_app_result = result
    except ImportError:
        typer.echo(
            "Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'",
            err=True,
        )
        sys.exit(1)
