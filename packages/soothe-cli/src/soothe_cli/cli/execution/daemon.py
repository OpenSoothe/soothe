"""Daemon-based execution for headless mode.

Uses RFC-0019 EventProcessor with HeadlessCliRenderer (stdout: loop-tagged answers only).
Uses WebSocket transport (RFC-0013).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

import typer
from soothe_sdk.client import (
    WebSocketClient,
    async_ws_command_client_from_config,
    bootstrap_loop_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_execution_error,
    is_daemon_worker_subprocess_lost,
)
from soothe_cli.cli.execution.headless_renderer import HeadlessCliRenderer
from soothe_cli.runtime import EventProcessor
from soothe_cli.tui._env_vars import resolve_cli_loop_workspace
from soothe_cli.tui.commands.subagent_routing import parse_subagent_from_input

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_SESSION_BOOTSTRAP_TIMEOUT_S = 30.0
_QUERY_START_TIMEOUT_S = 20.0
_HEADLESS_WORKER_LOST_RETRIES = 1
_CANCEL_SEND_TIMEOUT_S = 3.0


def _unwrap_next(event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Unwrap a protocol-1 ``next`` envelope to its inner streaming frame.

    Under protocol-1 (RFC-450 §9.3) the daemon wraps free-form streaming
    frames (``event``/``command_response``/card replay) in a
    ``{proto, type:"next", payload:{namespace, mode, data}}`` envelope. This
    helper returns the inner ``data`` dict (the legacy frame) so the headless
    loop and EventProcessor can branch on the same fields as before.
    ``status``/``error``/``response``/``complete`` are sent raw and pass
    through unchanged.
    """
    if not isinstance(event, dict):
        return event
    if event.get("type") != "next":
        return event
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return event
    data = payload.get("data")
    return data if isinstance(data, dict) else event


def _is_loop_scoped_event(event: dict[str, Any], *, active_loop_id: str) -> bool:
    """Return whether a daemon frame belongs to the active StrangeLoop session.

    Unwraps protocol-1 ``next`` envelopes first, then checks ``loop_id`` on the
    inner streaming frame. Non-scoped types (``response``, ``error``,
    ``complete``, etc.) are always considered in-scope.
    """
    event_type = event.get("type", "")
    if event_type == "next":
        inner = _unwrap_next(event)
        if isinstance(inner, dict):
            event_type = inner.get("type", "")
            return event_type not in {"status", "event"} or (inner.get("loop_id") == active_loop_id)
    if event_type not in {"status", "event"}:
        return True
    return event.get("loop_id") == active_loop_id


def _emit_headless_error(message: str) -> None:
    """Write a user-facing error line to stderr (headless renderer convention)."""
    typer.echo(f"ERROR: {message}", err=True)


async def _send_cancel_to_daemon(client: WebSocketClient) -> None:
    """Send /cancel to the daemon with a short timeout."""
    try:
        await asyncio.wait_for(
            client.notify("slash_command", {"cmd": "/cancel"}),
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
    from soothe_sdk.client import WebSocketClient

    ws_url = websocket_url_from_config(cfg)
    client = WebSocketClient(url=ws_url)

    # Track whether the daemon was notified of cancellation.
    cancel_sent = False
    sigint_received = False
    sigint_count = 0
    original_sigint: Any = None

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
        await connect_websocket_with_retries(client)
        cli_ws = resolve_cli_loop_workspace()
        # IG-441: three first-class modes (batch / adaptive / streaming).
        # Default is ``adaptive`` for headless runs as well — it gives smooth
        # progress on long synthesis while keeping wire traffic bounded.
        override = getattr(cfg, "output_streaming_mode", None)
        stream_delivery = override if override in ("batch", "adaptive", "streaming") else "adaptive"

        status_event = await bootstrap_loop_session(
            client,
            resume_loop_id=resume_loop_id,
            stream_delivery=stream_delivery,
            workspace=cli_ws,
            subscribe_timeout_s=_SESSION_BOOTSTRAP_TIMEOUT_S,
        )
        if status_event.get("type") == "error":
            raw = str(status_event.get("message", "unknown"))
            _emit_headless_error(friendly_daemon_execution_error(raw))
            return 1, is_daemon_worker_subprocess_lost(raw)

        active_loop_id = status_event.get("loop_id")
        if not active_loop_id:
            _emit_headless_error("No loop_id after session bootstrap")
            return 1, False

        subagent_name, cleaned_prompt = parse_subagent_from_input(prompt)
        effective_prompt = cleaned_prompt if subagent_name else prompt

        await asyncio.wait_for(
            client.send_input(
                active_loop_id,
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

        while True:
            # Check if SIGINT fired and send /cancel to the daemon.
            if sigint_received and not cancel_sent:
                cancel_sent = True
                logger.info("Headless query interrupted; sending /cancel to daemon")
                await _send_cancel_to_daemon(client)
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
            if not _is_loop_scoped_event(event, active_loop_id=active_loop_id):
                continue

            # Unwrap protocol-1 ``next`` envelopes to the inner streaming frame
            # (RFC-450 §9.3). ``status``/``error`` arrive raw and pass through.
            if event_type == "next":
                inner = _unwrap_next(event)
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
                    drain_deadline = loop_clock.time() + 30.0
                    while loop_clock.time() < drain_deadline:
                        try:
                            nxt = await asyncio.wait_for(client.read_event(), timeout=0.25)
                        except TimeoutError:
                            break
                        if not nxt:
                            break
                        if not _is_loop_scoped_event(nxt, active_loop_id=active_loop_id):
                            continue
                        # Unwrap ``next`` envelopes before handing to the
                        # processor so it sees the legacy frame shape.
                        if nxt.get("type") == "next":
                            inner = _unwrap_next(nxt)
                            if isinstance(inner, dict):
                                nxt = inner
                        processor.process_event(nxt)

                    processor.process_event(event)
                    break

            processor.process_event(event)

    except KeyboardInterrupt:
        if not cancel_sent:
            cancel_sent = True
            logger.info("Headless query interrupted by user; sending /cancel to daemon")
            await _send_cancel_to_daemon(client)
        return 1, False
    except asyncio.CancelledError:
        if not cancel_sent:
            cancel_sent = True
            logger.info("Headless query cancelled; sending /cancel to daemon")
            # Best-effort: the task is being cancelled so awaiting may fail.
            try:
                await asyncio.shield(_send_cancel_to_daemon(client))
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
        await client.close()


async def run_headless_via_daemon(
    cfg: Any,
    prompt: str,
    *,
    resume_loop_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon.

    Uses WebSocket transport for all connections (RFC-0013).
    Headless output is RFC-614 loop-tagged main-graph assistant text only (IG-343).

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
