"""Daemon-based execution for headless mode.

Refactored to use RFC-0019 EventProcessor with CliRenderer.
Uses WebSocket transport (RFC-0013).
"""

import asyncio
import json
import logging
import sys

import typer

from soothe.config import SootheConfig
from soothe.ux.cli.renderer import CliRenderer
from soothe.ux.core import EventProcessor

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42
_CONNECT_RETRY_COUNT = 40
_CONNECT_RETRY_DELAY_S = 0.25
_CONNECT_TIMEOUT_S = 5.0
_DAEMON_READY_TIMEOUT_S = 20.0
_SESSION_BOOTSTRAP_TIMEOUT_S = 5.0
_QUERY_START_TIMEOUT_S = 20.0


def _get_websocket_url(cfg: SootheConfig) -> str:
    """Get WebSocket URL from configuration.

    Args:
        cfg: Soothe configuration.

    Returns:
        WebSocket URL string.
    """
    host = cfg.daemon.transports.websocket.host
    port = cfg.daemon.transports.websocket.port
    return f"ws://{host}:{port}"


async def _connect_with_retries(client: object) -> None:
    """Connect to the daemon with bounded retries for cold-start races."""
    last_error: OSError | ConnectionError | TimeoutError | None = None
    for attempt in range(_CONNECT_RETRY_COUNT):
        try:
            await asyncio.wait_for(client.connect(), timeout=_CONNECT_TIMEOUT_S)
        except (ConnectionRefusedError, OSError, ConnectionError, TimeoutError) as exc:
            last_error = exc
            if attempt == _CONNECT_RETRY_COUNT - 1:
                raise
            await asyncio.sleep(_CONNECT_RETRY_DELAY_S)
        else:
            return

    if last_error is not None:
        raise last_error


async def _wait_for_thread_status(client: object, *, timeout_s: float = 5.0) -> dict[str, object]:
    """Wait for the post-bootstrap thread status, ignoring empty handshake status."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for thread status from daemon")

        event = await asyncio.wait_for(client.read_event(), timeout=remaining)
        if not event:
            raise ValueError("No event received")

        if event.get("type") == "error":
            return event

        if event.get("type") != "status":
            continue

        thread_id = event.get("thread_id")
        if thread_id:
            return event


async def run_headless_via_daemon(
    cfg: SootheConfig,
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
    from soothe.daemon.websocket_client import WebSocketClient

    _ = thread_id
    ws_url = _get_websocket_url(cfg)
    client = WebSocketClient(url=ws_url)

    try:
        await _connect_with_retries(client)
        await client.request_daemon_ready()
        await client.wait_for_daemon_ready(ready_timeout_s=_DAEMON_READY_TIMEOUT_S)

        # Request thread creation or resumption
        if thread_id:
            await client.send_resume_thread(thread_id)
        else:
            await client.send_new_thread()

        # Wait for actual thread status, skipping initial empty handshake status
        status_event = await _wait_for_thread_status(client, timeout_s=_SESSION_BOOTSTRAP_TIMEOUT_S)
        if status_event.get("type") == "error":
            typer.echo(f"Daemon error: {status_event.get('message', 'unknown')}", err=True)
            return 1

        actual_thread_id = status_event.get("thread_id")
        if not actual_thread_id:
            typer.echo("Error: No thread_id in status message", err=True)
            return 1

        # Subscribe to the thread with verbosity preference (RFC-0013, RFC-0022)
        verbosity = cfg.logging.verbosity
        await client.subscribe_thread(actual_thread_id, verbosity=verbosity)
        await client.wait_for_subscription_confirmed(
            actual_thread_id, verbosity=verbosity, timeout=_SESSION_BOOTSTRAP_TIMEOUT_S
        )

        # Parse slash commands for subagent routing (e.g. /browser, /research)
        from soothe.ux.cli.commands.subagent_names import parse_subagent_from_input

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

        # Initialize RFC-0019 unified event processor
        # Note: verbosity already determined above for subscription
        renderer = CliRenderer(verbosity=verbosity)
        processor = EventProcessor(renderer, verbosity=verbosity)

        has_error = False
        query_started = False  # Track if we've seen the query start running
        last_heartbeat = asyncio.get_event_loop().time()  # Track last heartbeat for timeout extension

        while True:
            try:
                if query_started:
                    event = await client.read_event()
                else:
                    # Extend timeout if heartbeat received recently
                    time_since_heartbeat = asyncio.get_event_loop().time() - last_heartbeat
                    effective_timeout = max(1.0, _QUERY_START_TIMEOUT_S - time_since_heartbeat)
                    event = await asyncio.wait_for(client.read_event(), timeout=effective_timeout)
            except TimeoutError:
                return _DAEMON_FALLBACK_EXIT_CODE
            if not event:
                break

            event_type = event.get("type", "")

            # Handle heartbeat events - reset timeout tracking
            if event_type == "event":
                ev_data = event.get("data")
                if isinstance(ev_data, dict) and ev_data.get("type") == "soothe.lifecycle.daemon.heartbeat":
                    last_heartbeat = asyncio.get_event_loop().time()
                    continue  # Don't process heartbeat as regular event

            # Handle status changes (need to track query_started for timeout)
            if event_type == "status":
                state = event.get("state", "")
                if state == "running":
                    query_started = True
                elif (state == "idle" and query_started) or state == "stopped":
                    processor.process_event(event)  # Finalize
                    break

            # Detect errors before query started as a hard failure
            ev_data = event.get("data")
            if event_type == "error":
                typer.echo(f"Daemon error: {event.get('message', 'unknown')}", err=True)
                return 1

            if (
                not query_started
                and isinstance(ev_data, dict)
                and str(ev_data.get("type", "")).startswith("soothe.error")
            ):
                typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
                return 1

            # JSONL output bypass processor
            if output_format == "jsonl":
                namespace = event.get("namespace", [])
                mode = event.get("mode", "")
                data = event.get("data")
                sys.stdout.write(
                    json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
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
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e, context='daemon connection')}", err=True)
        return _DAEMON_FALLBACK_EXIT_CODE
    except Exception as e:
        logger.exception("Failed to run via daemon")
        from soothe.utils.error_format import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        return 1
    else:
        return 1 if has_error else 0
    finally:
        await client.close()
