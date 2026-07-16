"""Daemon-based execution for headless mode.

Uses EventProcessor with HeadlessCliRenderer (stdout: loop-tagged answers only).
Session lifecycle goes through ``soothe_client.appkit.DaemonSession``.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

import typer
from soothe_client import (
    async_ws_command_client_from_config,
    websocket_url_from_config,
)
from soothe_client.appkit import DaemonSession, is_loop_scoped_event, unwrap_next

from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_execution_error,
    is_daemon_worker_subprocess_lost,
)
from soothe_cli.cli.execution.headless_renderer import HeadlessCliRenderer
from soothe_cli.runtime import EventProcessor
from soothe_cli.runtime.presentation.engine import PresentationEngine
from soothe_cli.tui._env_vars import resolve_cli_loop_workspace
from soothe_cli.tui.commands.subagent_routing import parse_subagent_from_input

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_SESSION_BOOTSTRAP_TIMEOUT_S = 30.0
_QUERY_START_TIMEOUT_S = 20.0
_HEADLESS_WORKER_LOST_RETRIES = 1
_CANCEL_SEND_TIMEOUT_S = 3.0


def _emit_headless_error(message: str) -> None:
    """Write a user-facing error line to stderr (headless renderer convention)."""
    typer.echo(f"ERROR: {message}", err=True)


async def _send_cancel_to_daemon(session: DaemonSession) -> None:
    """Send /cancel to the daemon with a short timeout."""
    try:
        await asyncio.wait_for(
            session.cancel_remote_query(),
            timeout=_CANCEL_SEND_TIMEOUT_S,
        )
    except Exception:
        logger.warning("Failed to send /cancel to daemon", exc_info=True)


def _parse_cron_slash_prompt(prompt: str) -> str | None:
    """Return natural-language cron text if ``prompt`` is a ``/cron`` slash command.

    Args:
        prompt: User input (e.g. ``/cron in 1 hour remind me to deploy``).

    Returns:
        Text after ``/cron``, or ``None`` if not a cron slash command.
    """
    stripped = prompt.strip()
    if not stripped.lower().startswith("/cron"):
        return None
    rest = stripped[len("/cron") :].strip()
    return rest


async def _run_headless_session_once(
    cfg: Any,
    prompt: str,
    *,
    resume_loop_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> tuple[int, bool]:
    """Run one headless daemon session; return ``(exit_code, retry_on_worker_loss)``."""
    # Track whether the daemon was notified of cancellation.
    cancel_sent = False
    sigint_received = False
    sigint_count = 0
    original_sigint: Any = None
    session: DaemonSession | None = None

    cron_text = _parse_cron_slash_prompt(prompt)
    if cron_text is not None:
        if not cron_text.strip():
            _emit_headless_error("Usage: /cron <natural language schedule>")
            return 1, False
        try:
            ws_client = async_ws_command_client_from_config(cfg)
            result = await ws_client.cron_add(cron_text)
        except RuntimeError as exc:
            _emit_headless_error(str(exc))
            return 1, False
        job = result.get("job") or {}
        job_id = job.get("id", "?")
        typer.echo(f"Scheduled cron job: {job_id}")
        typer.echo(f"  Description: {job.get('description', cron_text)}")
        typer.echo(f"  Next run: {str(job.get('next_run', ''))[:19]}")
        return 0, False

    try:
        cli_ws = resolve_cli_loop_workspace()
        # Three first-class modes (batch / adaptive / streaming).
        # Default is ``adaptive`` for headless runs as well — it gives smooth
        # progress on long synthesis while keeping wire traffic bounded.
        override = getattr(cfg, "output_streaming_mode", None)
        stream_delivery = override if override in ("batch", "adaptive", "streaming") else "adaptive"

        session = DaemonSession(
            websocket_url_from_config(cfg),
            workspace=cli_ws,
            stream_delivery=stream_delivery,
        )
        try:
            status_event = await asyncio.wait_for(
                session.connect(resume_loop_id=resume_loop_id),
                timeout=_SESSION_BOOTSTRAP_TIMEOUT_S,
            )
        except RuntimeError as exc:
            raw = str(exc)
            _emit_headless_error(friendly_daemon_execution_error(raw))
            return 1, is_daemon_worker_subprocess_lost(raw)

        if status_event.get("type") == "error":
            raw = str(status_event.get("message", "unknown"))
            _emit_headless_error(friendly_daemon_execution_error(raw))
            return 1, is_daemon_worker_subprocess_lost(raw)

        active_loop_id = session.loop_id or status_event.get("loop_id")
        if not active_loop_id:
            _emit_headless_error("No loop_id after session bootstrap")
            return 1, False

        subagent_name, cleaned_prompt = parse_subagent_from_input(prompt)
        effective_prompt = cleaned_prompt if subagent_name else prompt

        await asyncio.wait_for(
            session.send_turn(
                effective_prompt,
                autonomous=autonomous,
                max_iterations=max_iterations,
                preferred_subagent=subagent_name,
            ),
            timeout=_SESSION_BOOTSTRAP_TIMEOUT_S,
        )

        # Install a custom SIGINT handler that sends /cancel to the daemon
        # before cancelling the asyncio task.  This overrides the handler
        # that asyncio.run() installed so we can notify the daemon first.
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        def _on_headless_sigint() -> None:
            nonlocal sigint_received, sigint_count
            sigint_count += 1
            if sigint_count >= 2:
                # Second Ctrl+C — force exit without waiting.
                logger.info("Second Ctrl+C received; forcing exit")
                import sys

                sys.exit(130)
            sigint_received = True

        try:
            original_sigint = signal.getsignal(signal.SIGINT)
            loop.add_signal_handler(signal.SIGINT, _on_headless_sigint)
        except (ValueError, OSError):
            # Not main thread or signals not supported; rely on fallbacks.
            pass

        presentation = PresentationEngine()
        renderer = HeadlessCliRenderer()
        processor = EventProcessor(
            renderer,
            presentation_engine=presentation,
            headless_output=True,
            streaming_mode="batch" if stream_delivery == "batch" else "streaming",
        )

        query_started = False
        client = session.client

        while True:
            # Check if SIGINT fired and send /cancel to the daemon.
            if sigint_received and not cancel_sent:
                cancel_sent = True
                logger.info("Headless query interrupted; sending /cancel to daemon")
                await _send_cancel_to_daemon(session)
                # After notifying the daemon, cancel the main task so
                # asyncio.run() can unwind cleanly.
                if main_task is not None and not main_task.done():
                    main_task.cancel()

            try:
                if query_started:
                    event = await client.read_event()
                else:
                    event = await asyncio.wait_for(
                        client.read_event(), timeout=_QUERY_START_TIMEOUT_S
                    )
            except TimeoutError:
                return _DAEMON_FALLBACK_EXIT_CODE, False
            if not event:
                break

            event_type = event.get("type", "")
            if not is_loop_scoped_event(event, active_loop_id=active_loop_id):
                continue

            # Unwrap protocol-1 ``next`` envelopes to the inner streaming frame.
            # ``status``/``error`` arrive raw and pass through.
            if event_type == "next":
                inner = unwrap_next(event)
                if isinstance(inner, dict):
                    event = inner
                    event_type = event.get("type", "")

            if event_type == "error":
                # Protocol-1 error envelope: {type:'error', error:{code, message, data}}
                err_obj = event.get("error") or {}
                raw = str(err_obj.get("message") or event.get("message") or "unknown")
                _emit_headless_error(friendly_daemon_execution_error(raw))
                return 1, is_daemon_worker_subprocess_lost(raw)

            ev_data = event.get("data")
            if isinstance(ev_data, dict) and str(ev_data.get("type", "")).startswith(
                "soothe.error"
            ):
                raw = str(ev_data.get("error", "unknown"))
                _emit_headless_error(friendly_daemon_execution_error(raw))
                return 1, is_daemon_worker_subprocess_lost(raw)

            if event_type == "status":
                state = event.get("state", "")
                if state == "running":
                    query_started = True
                elif (state == "idle" and query_started) or state == "stopped":
                    loop_clock = asyncio.get_event_loop()
                    drain_deadline = loop_clock.time() + 0.5
                    while loop_clock.time() < drain_deadline:
                        try:
                            nxt = await asyncio.wait_for(client.read_event(), timeout=0.25)
                        except TimeoutError:
                            break
                        if not nxt:
                            break
                        if not is_loop_scoped_event(nxt, active_loop_id=active_loop_id):
                            continue
                        # Unwrap ``next`` envelopes before handing to the
                        # processor so it sees the legacy frame shape.
                        if nxt.get("type") == "next":
                            inner = unwrap_next(nxt)
                            if isinstance(inner, dict):
                                nxt = inner
                        processor.process_event(nxt)

                    processor.process_event(event)
                    break

            processor.process_event(event)

    except KeyboardInterrupt:
        if session is not None and not cancel_sent:
            cancel_sent = True
            logger.info("Headless query interrupted by user; sending /cancel to daemon")
            await _send_cancel_to_daemon(session)
        return 1, False
    except asyncio.CancelledError:
        if session is not None and not cancel_sent:
            cancel_sent = True
            logger.info("Headless query cancelled; sending /cancel to daemon")
            # Best-effort: the task is being cancelled so awaiting may fail.
            try:
                await asyncio.shield(_send_cancel_to_daemon(session))
            except (asyncio.CancelledError, Exception):
                pass
        raise
    except (ConnectionError, OSError, TimeoutError) as e:
        logger.exception("Daemon connection failed")
        from soothe_cli.cli.execution.daemon_errors import friendly_daemon_connection_error

        _emit_headless_error(friendly_daemon_connection_error(e))
        return _DAEMON_FALLBACK_EXIT_CODE, False
    except Exception as e:
        logger.exception("Failed to run via daemon")
        friendly = friendly_daemon_execution_error(e)
        _emit_headless_error(friendly)
        return 1, is_daemon_worker_subprocess_lost(e)
    else:
        return 0, False
    finally:
        # Restore original SIGINT handler.
        try:
            loop = asyncio.get_running_loop()
            loop.remove_signal_handler(signal.SIGINT)
            if original_sigint is not None:
                signal.signal(signal.SIGINT, original_sigint)
        except (ValueError, OSError, RuntimeError):
            pass
        if session is not None:
            await session.close()


async def run_headless_via_daemon(
    cfg: Any,
    prompt: str,
    *,
    resume_loop_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon.

    Uses WebSocket transport for all connections.
    Headless output is loop-tagged main-graph assistant text only.

    Retries once when the worker pool loses a subprocess mid-query (common idle-timeout
    race or transient worker recycle).
    """
    last_code = 1
    for attempt in range(_HEADLESS_WORKER_LOST_RETRIES + 1):
        last_code, retryable = await _run_headless_session_once(
            cfg,
            prompt,
            resume_loop_id=resume_loop_id,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )
        if last_code == 0:
            return 0
        if retryable and attempt < _HEADLESS_WORKER_LOST_RETRIES:
            logger.warning("Headless query failed after worker subprocess exit; retrying once")
            continue
        return last_code
    return last_code
