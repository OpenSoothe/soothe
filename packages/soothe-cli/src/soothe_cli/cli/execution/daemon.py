"""Daemon-based execution for headless mode.

Uses RFC-0019 EventProcessor with HeadlessCliRenderer (stdout: loop-tagged answers only).
Uses WebSocket transport (RFC-0013).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import typer
from soothe_sdk.client import (
    bootstrap_loop_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

from soothe_cli.cli.execution.headless_renderer import HeadlessCliRenderer
from soothe_cli.shared import EventProcessor
from soothe_cli.shared.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.shared.core.presentation_engine import PresentationEngine
from soothe_cli.shared.daemon_errors import (
    friendly_daemon_execution_error,
    is_daemon_worker_subprocess_lost,
)

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_SESSION_BOOTSTRAP_TIMEOUT_S = 30.0
_QUERY_START_TIMEOUT_S = 20.0
_HEADLESS_WORKER_LOST_RETRIES = 1


def _is_loop_scoped_event(event: dict[str, Any], *, active_loop_id: str) -> bool:
    """Return whether a daemon frame belongs to the active AgentLoop session."""
    event_type = event.get("type", "")
    if event_type not in {"status", "event"}:
        return True
    return event.get("loop_id") == active_loop_id


def _emit_headless_error(message: str) -> None:
    """Write a user-facing error line to stderr (headless renderer convention)."""
    typer.echo(f"ERROR: {message}", err=True)


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

    try:
        await connect_websocket_with_retries(client)
        cli_ws = os.environ.get("SOOTHE_CLI_WORKSPACE", "").strip() or os.getcwd()
        stream_delivery = "batch"
        if getattr(cfg, "output_streaming_mode", None) == "streaming":
            stream_delivery = "full"
        elif getattr(cfg, "output_streaming_mode", None) == "merged":
            stream_delivery = "merged"

        status_event = await bootstrap_loop_session(
            client,
            resume_loop_id=resume_loop_id,
            verbosity="normal",
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

            if event_type == "error":
                raw = str(event.get("message", "unknown"))
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
                    drain_deadline = loop_clock.time() + 2.5
                    while loop_clock.time() < drain_deadline:
                        try:
                            nxt = await asyncio.wait_for(client.read_event(), timeout=0.25)
                        except TimeoutError:
                            break
                        if not nxt:
                            break
                        if not _is_loop_scoped_event(nxt, active_loop_id=active_loop_id):
                            continue
                        processor.process_event(nxt)

                    processor.process_event(event)
                    break

            processor.process_event(event)

    except (ConnectionError, OSError, TimeoutError) as e:
        logger.exception("Daemon connection failed")
        from soothe_sdk.utils import format_cli_error

        _emit_headless_error(format_cli_error(e))
        return _DAEMON_FALLBACK_EXIT_CODE, False
    except Exception as e:
        logger.exception("Failed to run via daemon")
        friendly = friendly_daemon_execution_error(e)
        _emit_headless_error(friendly)
        return 1, is_daemon_worker_subprocess_lost(e)
    else:
        return 0, False
    finally:
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
