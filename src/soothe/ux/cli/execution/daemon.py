"""Daemon-based execution for headless mode.

Refactored to use RFC-0019 EventProcessor with CliRenderer.
"""

import asyncio
import json
import logging
import sys

import typer

from soothe.config import SootheConfig
from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT
from soothe.ux.cli.renderer import CliRenderer
from soothe.ux.core import EventProcessor

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42


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

    Refactored to use RFC-0019 EventProcessor with CliRenderer.
    """
    from soothe.daemon import DaemonClient

    _ = thread_id
    daemon_start_timeout_s = 20.0
    daemon_inactivity_timeout_s = 180.0
    client = DaemonClient()

    try:
        await asyncio.wait_for(client.connect(), timeout=5.0)

        # Request thread creation or resumption
        if thread_id:
            await client.send_resume_thread(thread_id)
        else:
            await client.send_new_thread()

        # Wait for status message with thread_id
        status_event = await asyncio.wait_for(client.read_event(), timeout=5.0)
        if not status_event or status_event.get("type") != "status":
            typer.echo("Error: Expected status message from daemon", err=True)
            return 1

        actual_thread_id = status_event.get("thread_id")
        if not actual_thread_id:
            typer.echo("Error: No thread_id in status message", err=True)
            return 1

        # Subscribe to the thread (RFC-0013)
        await client.subscribe_thread(actual_thread_id)
        await client.wait_for_subscription_confirmed(actual_thread_id)

        # Send the input
        await asyncio.wait_for(
            client.send_input(
                prompt,
                autonomous=autonomous,
                max_iterations=max_iterations,
            ),
            timeout=5.0,
        )

        # Initialize RFC-0019 unified event processor
        verbosity = cfg.logging.verbosity
        renderer = CliRenderer(verbosity=verbosity)
        processor = EventProcessor(renderer, verbosity=verbosity)

        has_error = False
        query_started = False  # Track if we've seen the query start running

        while True:
            timeout_s = daemon_inactivity_timeout_s if query_started else daemon_start_timeout_s
            try:
                event = await asyncio.wait_for(client.read_event(), timeout=timeout_s)
            except TimeoutError:
                if query_started:
                    typer.echo("Error: daemon stream timed out while waiting for events.", err=True)
                    return 1
                return _DAEMON_FALLBACK_EXIT_CODE
            if not event:
                break

            event_type = event.get("type", "")

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

            # Handle special CLI-only events before processor
            mode = event.get("mode", "")
            data = event.get("data")
            if mode == "custom" and isinstance(data, dict):
                etype = str(data.get("type", ""))
                if etype == FINAL_REPORT:
                    report_text = data.get("summary", "")
                    if report_text:
                        sys.stdout.write("\n\n")
                        sys.stdout.write(report_text)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    continue
                if etype == CHITCHAT_RESPONSE:
                    chitchat_content = data.get("content", "")
                    if chitchat_content:
                        sys.stdout.write(chitchat_content)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    continue

            # Delegate to unified event processor
            processor.process_event(event)

        # Final newline after response
        if renderer.full_response:
            sys.stdout.write("\n")
            sys.stdout.flush()

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
