"""Daemon-based execution for headless mode.

Refactored to use RFC-0019 EventProcessor with CliRenderer.
Uses WebSocket transport (RFC-0013).
"""

import asyncio
import json
import logging
import sys
from typing import Any

import typer
from soothe_sdk.client import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

from soothe_cli.cli.renderer import CliRenderer
from soothe_cli.shared import EventProcessor
from soothe_cli.shared.presentation_engine import PresentationEngine
from soothe_cli.shared.subagent_routing import parse_subagent_from_input

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_SESSION_BOOTSTRAP_TIMEOUT_S = 5.0
_QUERY_START_TIMEOUT_S = 20.0


async def run_headless_via_daemon(
    cfg: Any,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon.

    Uses WebSocket transport for all connections (RFC-0013).
    Refactored to use RFC-0019 EventProcessor with CliRenderer.
    """
    from soothe_sdk.client import WebSocketClient

    ws_url = websocket_url_from_config(cfg)
    client = WebSocketClient(url=ws_url)
    verbosity = cfg.logging.verbosity
    final_output_mode = getattr(cfg, "final_output_mode", "streaming")

    try:
        await connect_websocket_with_retries(client)
        status_event = await bootstrap_thread_session(
            client,
            resume_thread_id=thread_id,
            verbosity=verbosity,
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

        # Send the input
        await asyncio.wait_for(
            client.send_input(
                cleaned_prompt if subagent_name else prompt,
                autonomous=autonomous,
                max_iterations=max_iterations,
                subagent=subagent_name,
            ),
            timeout=_SESSION_BOOTSTRAP_TIMEOUT_S,
        )

        # Initialize RFC-0019 unified event processor with one PresentationEngine
        # for pipeline + message gating (RFC-502).
        presentation = PresentationEngine()
        renderer = CliRenderer(verbosity=verbosity, presentation_engine=presentation)
        processor = EventProcessor(
            renderer,
            verbosity=verbosity,
            final_output_mode=final_output_mode,
            presentation_engine=presentation,
        )

        has_error = False
        query_started = False  # Track if we've seen the query start running

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

            # IMMEDIATE error check - exit before any other processing
            # This ensures errors before query starts return immediately (IG-181)
            if event_type == "error":
                typer.echo(f"Daemon error: {event.get('message', 'unknown')}", err=True)
                return 1

            # Check for soothe.error.* events before query starts
            ev_data = event.get("data")
            if (
                not query_started
                and isinstance(ev_data, dict)
                and str(ev_data.get("type", "")).startswith("soothe.error")
            ):
                typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
                return 1

            # Handle status changes (need to track query_started for timeout)
            if event_type == "status":
                state = event.get("state", "")
                if state == "running":
                    query_started = True
                elif (state == "idle" and query_started) or state == "stopped":
                    # loop.completed (and stray message chunks) may arrive *after* idle on the
                    # WebSocket stream; draining avoids dropping completion + final stdout (test-case1).
                    loop_clock = asyncio.get_event_loop()
                    drain_deadline = loop_clock.time() + 2.5
                    while loop_clock.time() < drain_deadline:
                        try:
                            nxt = await asyncio.wait_for(client.read_event(), timeout=0.25)
                        except TimeoutError:
                            break
                        if not nxt:
                            break
                        if output_format == "jsonl":
                            namespace = nxt.get("namespace", [])
                            mode = nxt.get("mode", "")
                            data = nxt.get("data")
                            sys.stdout.write(
                                json.dumps(
                                    {"namespace": list(namespace), "mode": mode, "data": data},
                                    default=str,
                                )
                                + "\n"
                            )
                            sys.stdout.flush()
                            continue
                        processor.process_event(nxt)

                    processor.process_event(event)  # Finalize (on_turn_end after drain)
                    break

            # JSONL output bypass processor
            if output_format == "jsonl":
                namespace = event.get("namespace", [])
                mode = event.get("mode", "")
                data = event.get("data")
                sys.stdout.write(
                    json.dumps(
                        {"namespace": list(namespace), "mode": mode, "data": data}, default=str
                    )
                    + "\n"
                )
                sys.stdout.flush()
                continue

            # Delegate to unified event processor
            processor.process_event(event)

        # Note: Final newline is handled by renderer.on_turn_end() called
        # when status changes to idle/stopped in _handle_status().
        # Daemon lifecycle remains silent in normal headless mode.

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
        return 1 if has_error else 0
    finally:
        await client.close()
