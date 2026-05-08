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
    bootstrap_thread_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

from soothe_cli.cli.execution.headless_renderer import HeadlessCliRenderer
from soothe_cli.shared import EventProcessor
from soothe_cli.shared.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.shared.core.presentation_engine import PresentationEngine

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_SESSION_BOOTSTRAP_TIMEOUT_S = 5.0
_QUERY_START_TIMEOUT_S = 20.0


def _is_thread_scoped_event_for_active_thread(
    event: dict[str, Any],
    *,
    active_thread_id: str,
) -> bool:
    """Return whether a daemon frame belongs to the active headless thread.

    In headless mode we only want `status` and streamed `event` frames for the
    thread started by this CLI invocation. This avoids cross-thread leakage when
    unrelated frames are present on the transport.
    """
    event_type = event.get("type", "")
    if event_type not in {"status", "event"}:
        return True
    return event.get("thread_id") == active_thread_id


async def run_headless_via_daemon(
    cfg: Any,
    prompt: str,
    *,
    thread_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon.

    Uses WebSocket transport for all connections (RFC-0013).
    Headless output is RFC-614 loop-tagged main-graph assistant text only (IG-343).
    """
    from soothe_sdk.client import WebSocketClient

    ws_url = websocket_url_from_config(cfg)
    client = WebSocketClient(url=ws_url)

    try:
        await connect_websocket_with_retries(client)
        cli_ws = os.environ.get("SOOTHE_CLI_WORKSPACE", "").strip() or os.getcwd()
        status_event = await bootstrap_thread_session(
            client,
            resume_thread_id=thread_id,
            verbosity="normal",
            workspace=cli_ws,
            thread_status_timeout_s=_SESSION_BOOTSTRAP_TIMEOUT_S,
            subscription_timeout_s=_SESSION_BOOTSTRAP_TIMEOUT_S,
        )
        if status_event.get("type") == "error":
            typer.echo(f"Daemon error: {status_event.get('message', 'unknown')}", err=True)
            return 1

        actual_thread_id = status_event.get("thread_id")
        if not actual_thread_id:
            typer.echo("Error: No thread_id in status message", err=True)
            return 1

        subagent_name, cleaned_prompt = parse_subagent_from_input(prompt)

        await asyncio.wait_for(
            client.send_input(
                cleaned_prompt if subagent_name else prompt,
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
                return _DAEMON_FALLBACK_EXIT_CODE
            if not event:
                break

            event_type = event.get("type", "")
            if not _is_thread_scoped_event_for_active_thread(
                event, active_thread_id=actual_thread_id
            ):
                continue

            if event_type == "error":
                typer.echo(f"Daemon error: {event.get('message', 'unknown')}", err=True)
                return 1

            ev_data = event.get("data")
            if (
                not query_started
                and isinstance(ev_data, dict)
                and str(ev_data.get("type", "")).startswith("soothe.error")
            ):
                typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
                return 1

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
                        if not _is_thread_scoped_event_for_active_thread(
                            nxt, active_thread_id=actual_thread_id
                        ):
                            continue
                        processor.process_event(nxt)

                    processor.process_event(event)
                    break

            processor.process_event(event)

    except (ConnectionError, OSError, TimeoutError) as e:
        logger.exception("Daemon connection failed")
        from soothe_sdk.utils import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        return _DAEMON_FALLBACK_EXIT_CODE
    except Exception as e:
        logger.exception("Failed to run via daemon")
        from soothe_sdk.utils import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        return 1
    else:
        return 0
    finally:
        await client.close()
