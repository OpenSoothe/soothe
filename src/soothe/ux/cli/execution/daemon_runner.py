"""Daemon-based execution for headless mode."""

import asyncio
import json
import logging
import re
import sys

import typer

from soothe.config import SootheConfig
from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT, PLAN_CREATED
from soothe.ux.shared.message_processing import (
    coerce_tool_call_args_to_dict,
    extract_tool_brief,
    format_tool_call_args,
    normalize_tool_calls_list,
    tool_calls_have_any_arg_dict,
)

logger = logging.getLogger(__name__)

_DAEMON_FALLBACK_EXIT_CODE = 42


def _to_snake_case(name: str) -> str:
    """Convert PascalCase or camelCase to snake_case.

    Args:
        name: Tool name in any case format.

    Returns:
        snake_case version of the name.

    Examples:
        >>> _to_snake_case("ReadFile")
        'read_file'
        >>> _to_snake_case("Ls")
        'ls'
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower() if name else name


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
    from soothe.daemon import DaemonClient
    from soothe.ux.cli.rendering import render_progress_event
    from soothe.ux.shared.progress_verbosity import classify_custom_event, should_show
    from soothe.ux.shared.rendering import resolve_namespace_label, update_name_map_from_tool_calls

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

        # Stream events
        full_response: list[str] = []
        seen_message_ids: set[str] = set()
        name_map: dict[str, str] = {}
        has_error = False
        verbosity = cfg.logging.progress_verbosity
        query_started = False  # Track if we've seen the query start running
        needs_stdout_newline = False
        multi_step_active = False  # Suppress step AI text from stdout; final report only

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
                    if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
                        multi_step_active = True
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
                        # Format 1: content_blocks array (align with MessageProcessor / IG-053)
                        update_name_map_from_tool_calls({"content_blocks": content_blocks}, name_map)

                        if msg_id:
                            if msg_id in seen_message_ids:
                                continue
                            seen_message_ids.add(msg_id)

                        from soothe.tools.display_names import get_tool_display_name

                        raw_tcs = msg_data.get("tool_calls") or []
                        has_tc_args = tool_calls_have_any_arg_dict(raw_tcs)
                        tool_call_emitted_from_blocks = False

                        for block in content_blocks:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                text = block.get("text", "")
                                if is_main and text and should_show("assistant_text", verbosity):
                                    full_response.append(text)
                                    if not multi_step_active:
                                        sys.stdout.write(text)
                                        sys.stdout.flush()
                                        needs_stdout_newline = True
                            elif btype in ("tool_call", "tool_call_chunk") and should_show("tool_activity", verbosity):
                                if has_tc_args:
                                    continue
                                name = block.get("name", "")
                                if not name:
                                    continue
                                coerced = coerce_tool_call_args_to_dict(block.get("args"))
                                # Direct stderr debug to see what's happening
                                sys.stderr.write(
                                    f"[DEBUG-daemon] Tool: {name}, args={block.get('args')}, coerced={coerced}\n"
                                )
                                sys.stderr.flush()
                                logger.debug(
                                    "Tool call block: name=%s, args_raw=%s, coerced=%s, block_keys=%s",
                                    name,
                                    block.get("args"),
                                    coerced,
                                    list(block.keys()),
                                )
                                if not coerced and raw_tcs:
                                    continue
                                if needs_stdout_newline:
                                    sys.stdout.write("\n")
                                    sys.stdout.flush()
                                    needs_stdout_newline = False
                                prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                display_name = get_tool_display_name(name)
                                internal_name = _to_snake_case(name)
                                args_str = format_tool_call_args(internal_name, {"args": coerced})
                                logger.debug(
                                    "Tool display: name=%s, internal_name=%s, args_str=%s",
                                    name,
                                    internal_name,
                                    args_str,
                                )
                                if coerced:
                                    tool_call_emitted_from_blocks = True
                                if prefix:
                                    sys.stderr.write(f"[{prefix}] ⚙ {display_name}{args_str}\n")
                                else:
                                    sys.stderr.write(f"⚙ {display_name}{args_str}\n")
                                sys.stderr.flush()

                        tcs = normalize_tool_calls_list(raw_tcs)
                        if tcs and should_show("tool_activity", verbosity):
                            for tc in tcs:
                                name = tc.get("name", "")
                                if not name:
                                    continue
                                tc_display = dict(tc)
                                tc_display["args"] = coerce_tool_call_args_to_dict(tc.get("args"))
                                if not (has_tc_args or (not tc_display["args"] and not tool_call_emitted_from_blocks)):
                                    continue
                                if needs_stdout_newline:
                                    sys.stdout.write("\n")
                                    sys.stdout.flush()
                                    needs_stdout_newline = False
                                prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                display_name = get_tool_display_name(name)
                                internal_name = _to_snake_case(name)
                                args_str = format_tool_call_args(internal_name, tc_display)
                                if prefix:
                                    sys.stderr.write(f"[{prefix}] ⚙ {display_name}{args_str}\n")
                                else:
                                    sys.stderr.write(f"⚙ {display_name}{args_str}\n")
                                sys.stderr.flush()

                    elif content and isinstance(content, str):
                        # Format 2: simple content string (from daemon serialization)
                        if is_main and should_show("assistant_text", verbosity):
                            full_response.append(content)
                            if not multi_step_active:
                                sys.stdout.write(content)
                                sys.stdout.flush()
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

                    # Format as tree child (see IG-053)
                    if prefix:
                        sys.stderr.write(f"[{prefix}]   └ ✓ {brief}\n")
                    else:
                        sys.stderr.write(f"  └ ✓ {brief}\n")
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
