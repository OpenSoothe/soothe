"""Daemon-based execution for headless mode."""

import asyncio
import json
import logging
import sys

import typer

from soothe.cli.rendering.tool_brief import extract_tool_brief
from soothe.config import SootheConfig
from soothe.core.events import CHITCHAT_RESPONSE, FINAL_REPORT

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42


def _daemon_tool_brief(tool_name: str, content: object) -> str:
    """One-line summary of a tool result for daemon headless output."""
    text = content if isinstance(content, str) else str(content)
    return extract_tool_brief(tool_name, text)


async def run_headless_via_daemon(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon."""
    from soothe.cli.daemon import DaemonClient
    from soothe.cli.progress_verbosity import classify_custom_event, should_show
    from soothe.cli.rendering import render_progress_event
    from soothe.cli.tui_shared import resolve_namespace_label, update_name_map_from_tool_calls

    _ = thread_id
    daemon_start_timeout_s = 20.0
    daemon_inactivity_timeout_s = 180.0
    client = DaemonClient()

    try:
        await asyncio.wait_for(client.connect(), timeout=5.0)

        # Send the input
        await asyncio.wait_for(
            client.send_input(
                prompt,
                autonomous=autonomous,
                max_iterations=max_iterations,
            ),
            timeout=5.0,
        )

        # Stream events
        full_response: list[str] = []
        seen_message_ids: set[str] = set()
        name_map: dict[str, str] = {}
        has_error = False
        verbosity = cfg.logging.progress_verbosity
        query_started = False  # Track if we've seen the query start running
        needs_stdout_newline = False

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

            # Handle status changes
            if event_type == "status":
                state = event.get("state", "")
                if state == "running":
                    query_started = True
                elif (state == "idle" and query_started) or state == "stopped":
                    break
                continue

            if event_type != "event":
                continue

            # Detect errors before query started as a hard failure
            ev_data = event.get("data")
            if (
                not query_started
                and isinstance(ev_data, dict)
                and str(ev_data.get("type", "")).startswith("soothe.error")
            ):
                typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
                return 1

            namespace = tuple(event.get("namespace", []))
            mode = event.get("mode", "")
            data = event.get("data")

            if output_format == "jsonl":
                sys.stdout.write(
                    json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
                )
                sys.stdout.flush()
                continue

            if mode == "custom" and isinstance(data, dict):
                etype = str(data.get("type", ""))

                if etype == FINAL_REPORT:
                    report_text = data.get("summary", "")
                    if report_text:
                        sys.stdout.write("\n\n")
                        sys.stdout.write(report_text)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        full_response.append(report_text)
                elif etype == CHITCHAT_RESPONSE:
                    chitchat_content = data.get("content", "")
                    if chitchat_content:
                        sys.stdout.write(chitchat_content)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        full_response.append(chitchat_content)
                else:
                    category = classify_custom_event(namespace, data)
                    if should_show(category, verbosity):
                        # Add newline before stderr output if needed
                        if needs_stdout_newline:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            needs_stdout_newline = False
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        render_progress_event(data, prefix=prefix, verbosity=verbosity)
                    if category == "error":
                        has_error = True

            if mode == "messages":
                message_data_tuple_length = 2
                if not isinstance(data, (list, tuple)) or len(data) != message_data_tuple_length:
                    continue
                msg_data, metadata = data
                is_main = not namespace
                if metadata and metadata.get("lc_source") == "summarization":
                    continue

                # Reconstruct message object from serialized data
                msg_type = msg_data.get("type") if isinstance(msg_data, dict) else None

                # Handle AI messages (both AIMessage and AIMessageChunk)
                if msg_type in ("ai", "AIMessage", "AIMessageChunk"):
                    msg_id = msg_data.get("id", "")

                    # Handle both content_blocks format and simple content format
                    content_blocks = msg_data.get("content_blocks", [])
                    content = msg_data.get("content", "")

                    if content_blocks and isinstance(content_blocks, list):
                        # Format 1: content_blocks array
                        update_name_map_from_tool_calls({"content_blocks": content_blocks}, name_map)

                        if msg_id:
                            if msg_id in seen_message_ids:
                                continue
                            seen_message_ids.add(msg_id)

                        for block in content_blocks:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                text = block.get("text", "")
                                if is_main and text and should_show("assistant_text", verbosity):
                                    sys.stdout.write(text)
                                    sys.stdout.flush()
                                    full_response.append(text)
                                    needs_stdout_newline = True
                            elif btype in ("tool_call", "tool_call_chunk") and should_show("tool_activity", verbosity):
                                name = block.get("name", "")
                                if name:
                                    # Add newline before stderr output if needed
                                    if needs_stdout_newline:
                                        sys.stdout.write("\n")
                                        sys.stdout.flush()
                                        needs_stdout_newline = False
                                    prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                    if prefix:
                                        sys.stderr.write(f"[{prefix}] [tool] Calling: {name}\n")
                                    else:
                                        sys.stderr.write(f"[tool] Calling: {name}\n")
                                    sys.stderr.flush()

                    elif content and isinstance(content, str):
                        # Format 2: simple content string (from daemon serialization)
                        if is_main and should_show("assistant_text", verbosity):
                            sys.stdout.write(content)
                            sys.stdout.flush()
                            full_response.append(content)
                            needs_stdout_newline = True

                elif msg_type in ("tool", "ToolMessage") and should_show("tool_activity", verbosity):
                    tool_name = msg_data.get("name", "tool")
                    content = msg_data.get("content", "")
                    brief = _daemon_tool_brief(tool_name, content)
                    # Add newline before stderr output if needed
                    if needs_stdout_newline:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        needs_stdout_newline = False
                    prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                    if prefix:
                        sys.stderr.write(f"[{prefix}] [tool] Result ({tool_name}): {brief}\n")
                    else:
                        sys.stderr.write(f"[tool] Result ({tool_name}): {brief}\n")
                    sys.stderr.flush()

        if full_response:
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
