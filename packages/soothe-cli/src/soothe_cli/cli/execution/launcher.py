"""TUI execution mode."""

import asyncio
import sys
from typing import Any

import typer
from soothe_client import protocol1_rpc, websocket_url_from_config

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


def _resume_gate(cfg: CLIConfig, resume_loop_id: str) -> dict[str, Any] | None:
    """Fetch execution state for a resumed loop before launching the TUI.

    Returns the ``{plan, step_index, iteration, status}`` snapshot on success,
    or ``None`` when the daemon is unreachable or the RPC fails (non-fatal —
    resume proceeds regardless).
    """
    try:
        ws_url = websocket_url_from_config(cfg)
        response = asyncio.run(
            protocol1_rpc(
                ws_url,
                "loop_execution_state_fetch",
                {"loop_id": resume_loop_id},
            )
        )
    except Exception:
        return None

    if isinstance(response, dict) and "error" not in response:
        return response
    return None


def _prompt_resume(resume_loop_id: str, state: dict[str, Any]) -> bool:
    """Prompt the user to confirm resume of an active loop.

    Returns ``True`` if the user confirms (Enter / y), ``False`` to discard
    (n / any other input). Non-interactive stdin (no TTY) defaults to resuming.
    """
    step_index = state.get("step_index", 0)
    iteration = state.get("iteration", 0)
    status = state.get("status", "unknown")
    typer.echo(
        f"Active loop found: {resume_loop_id} (iteration {iteration}, step {step_index}, {status})"
    )

    if not sys.stdin.isatty():
        # Non-interactive: auto-resume.
        typer.echo("Non-interactive stdin — resuming.")
        return True

    try:
        answer = typer.prompt(
            "Resume this loop?",
            default="y",
            show_default=True,
        )
    except (EOFError, KeyboardInterrupt):
        return False

    return answer.strip().lower() in ("y", "yes", "")


def run_tui(
    cfg: CLIConfig,
    *,
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    global _last_app_result

    # Resume gate: surface where the loop will pick up from the daemon's
    # execution state before the TUI attaches.
    if resume_loop_id:
        state = _resume_gate(cfg, resume_loop_id)
        if state is not None:
            status = state.get("status", "unknown")
            # Auto-resume loops in running/paused state only; terminal/idle
            # states fall through to normal startup.
            if status in ("running", "paused"):
                should_resume = cfg.auto_resume or _prompt_resume(resume_loop_id, state)
                if not should_resume:
                    typer.echo("Loop discarded. Starting fresh session.")
                    resume_loop_id = None
                else:
                    step_index = state.get("step_index", 0)
                    iteration = state.get("iteration", 0)
                    plan = state.get("plan")
                    typer.echo(
                        f"Resuming loop {resume_loop_id}: "
                        f"iteration {iteration}, step {step_index} ({status})"
                    )
                    if plan:
                        typer.echo(f"  Plan: {plan}")
            else:
                typer.echo(f"Loop {resume_loop_id} is {status} — starting fresh session.")
                resume_loop_id = None

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
