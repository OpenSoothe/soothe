"""Verify daemon broadcast events from raw daemon API without TUI logic.

This script connects to the daemon via SDK WebSocket client and verifies:
1. Unified tool call IDs (IG-416 format)
2. Task delegation and step association
3. Tool call and task instance association
4. Stream tool wire events (soothe.stream.tool_call.update)
5. Subagent wire events (soothe.subagent.*)

Usage:
    python scripts/verify_daemon_events.py [--daemon-url URL] [--timeout SECONDS]

Requirements:
    - Daemon running at the specified URL (default ws://localhost:8765)
    - Valid SootheConfig with providers configured
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from soothe_sdk.client.websocket import WebSocketClient
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE, extract_tool_call_updates_from_wire_message
from soothe_sdk.ux.task_namespace import (
    parse_unified_tool_call_id,
    normalize_unified_tool_call_id,
)
from soothe_sdk.core.subagent_wire import (
    ALLOWLISTED_SUBAGENT_EVENT_TYPES,
    parse_subagent_wire_agent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class EventStats:
    """Statistics collected from daemon events."""

    total_events: int = 0
    events_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Tool call tracking
    tool_call_ids: set[str] = field(default_factory=set)
    unified_tool_call_ids: set[str] = field(default_factory=set)
    legacy_tool_call_ids: set[str] = field(default_factory=set)

    # Step association
    tool_calls_by_step: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    # Task delegation tracking
    task_tool_calls: set[str] = field(default_factory=set)
    task_scopes: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # tool_call_id -> (id, subagent_type, step_id)

    # Subagent events
    subagent_events_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    subagent_events_by_agent: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Stream tool wire events
    stream_tool_updates: list[dict[str, Any]] = field(default_factory=list)

    # Args accumulation tracking (like TUI's pending_tool_calls)
    pending_tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    # tool_call_id -> {"name": str, "args_str": str, "is_complete_json": bool}

    # Track last active tool_call_id for orphan chunk attachment
    last_active_tool_call_id: str = ""

    # Final accumulated args per tool_call_id
    accumulated_args: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Validation errors
    errors: list[str] = field(default_factory=list)


def classify_tool_call_id(tool_call_id: str) -> tuple[str, str, int | None, str]:
    """Parse and classify a tool_call_id.

    Returns:
        (step_id, type_code, task_idx, tool_info)
        - step_id: empty for legacy, non-empty for unified
        - type_code: 's' for step-level, 't' for task-level, '' for legacy
        - task_idx: None for step-level, int for task-level
        - tool_info: tool name and index fragment
    """
    normalized = normalize_unified_tool_call_id(tool_call_id)
    return parse_unified_tool_call_id(normalized)


def validate_event(event: dict[str, Any], stats: EventStats) -> None:
    """Validate a single daemon event and update statistics."""

    stats.total_events += 1
    event_type = event.get("type", "unknown")
    stats.events_by_type[event_type] += 1

    # Handle wrapped events (daemon wraps LangGraph stream events in "event" type)
    if event_type == "event":
        # The daemon wraps events with: {"type": "event", "namespace": [...], "mode": "...", "data": ...}
        mode = event.get("mode", "")
        data = event.get("data")
        namespace = event.get("namespace", [])

        # Log all wrapped events for debugging
        logger.debug(
            "Wrapped event: mode=%s namespace=%s data_type=%s",
            mode, namespace, type(data).__name__
        )

        # Handle messages stream events - data is a tuple (message, metadata)
        if mode == "messages":
            if isinstance(data, (list, tuple)) and len(data) >= 1:
                msg = data[0]
                if isinstance(msg, dict):
                    # Log the message structure with full tool_calls content
                    tool_calls = msg.get("tool_calls", [])
                    chunks = msg.get("tool_call_chunks", [])
                    msg_type = msg.get("type", "unknown")

                    # Distinguish AIMessage vs AIMessageChunk
                    logger.info(
                        "Messages event: type=%s tool_calls=%d chunks=%d",
                        msg_type,
                        len(tool_calls),
                        len(chunks)
                    )

                    # --- Args accumulation (like TUI's accumulate_tool_call_chunks) ---
                    for tcc in chunks:
                        if not isinstance(tcc, dict):
                            continue
                        tc_id_raw = tcc.get("id")
                        tc_id = str(tc_id_raw) if tc_id_raw not in (None, "") else ""
                        tc_name = tcc.get("name")
                        tc_args = tcc.get("args", "")

                        # First chunk with a tool name: register the pending tool call
                        if tc_name and tc_id and tc_id not in stats.pending_tool_calls:
                            if isinstance(tc_args, str):
                                args_str = tc_args
                                is_complete = False  # String may be partial JSON
                            elif isinstance(tc_args, dict) and tc_args:
                                args_str = json.dumps(tc_args)
                                is_complete = True  # Dict yields complete JSON
                            else:
                                args_str = ""
                                is_complete = False  # Empty or missing args
                            stats.pending_tool_calls[tc_id] = {
                                "name": tc_name,
                                "args_str": args_str,
                                "is_complete_json": is_complete,
                            }
                            stats.last_active_tool_call_id = tc_id
                            logger.debug(
                                "Registered pending tool: id=%s name=%s args_str='%s'",
                                tc_id, tc_name, args_str[:50]
                            )
                        # Some providers send final args as a dict on a later chunk
                        elif tc_id and tc_id in stats.pending_tool_calls and isinstance(tc_args, dict) and tc_args:
                            stats.pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
                            stats.pending_tool_calls[tc_id]["is_complete_json"] = True
                            logger.debug(
                                "Updated pending tool with dict args: id=%s args=%s",
                                tc_id, str(tc_args)[:50]
                            )
                        # Subsequent chunks: accumulate partial JSON strings
                        elif tc_id and tc_id in stats.pending_tool_calls and isinstance(tc_args, str) and tc_args:
                            if stats.pending_tool_calls[tc_id].get("is_complete_json"):
                                # Provider refined args → restart accumulation
                                stats.pending_tool_calls[tc_id]["args_str"] = tc_args
                                stats.pending_tool_calls[tc_id]["is_complete_json"] = False
                            else:
                                # Normal partial accumulation
                                stats.pending_tool_calls[tc_id]["args_str"] += tc_args
                                logger.debug(
                                    "Accumulated chunk: id=%s args_str='%s'",
                                    tc_id, stats.pending_tool_calls[tc_id]["args_str"][:50]
                                )
                        # Chunks without id: attach to last active tool (the one being streamed currently)
                        elif tc_args and isinstance(tc_args, str) and tc_args:
                            last_id = stats.last_active_tool_call_id
                            if last_id and last_id in stats.pending_tool_calls:
                                if not stats.pending_tool_calls[last_id].get("_emitted"):
                                    stats.pending_tool_calls[last_id]["args_str"] += tc_args
                                    logger.debug(
                                        "Attached orphan chunk to last active: id=%s args_str='%s'",
                                        last_id, stats.pending_tool_calls[last_id]["args_str"][:50]
                                    )

                    # Also check tool_calls for complete args (terminal message)
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        tc_id = str(tc.get("id") or "").strip()
                        if not tc_id:
                            continue
                        tc_args = tc.get("args")
                        if isinstance(tc_args, dict) and tc_args:
                            # This is a terminal message with complete args
                            if tc_id in stats.pending_tool_calls:
                                stats.pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
                                stats.pending_tool_calls[tc_id]["is_complete_json"] = True
                                stats.pending_tool_calls[tc_id]["_from_terminal"] = True
                                logger.info(
                                    "Terminal tool_call with args: id=%s args=%s",
                                    tc_id, str(tc_args)[:100]
                                )

                    # Extract tool_call_ids from message (using standard function)
                    updates = extract_tool_call_updates_from_wire_message(msg)
                    logger.debug("Extracted %d tool call updates from message", len(updates))

                    # Also manually capture tool_call_ids even with empty args
                    # (the extract function skips entries with empty args)
                    manual_ids: set[str] = set()
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            tid = str(tc.get("id") or "").strip()
                            if tid and tid not in manual_ids:
                                manual_ids.add(tid)

                    for ch in chunks:
                        if isinstance(ch, dict):
                            tid = str(ch.get("id") or "").strip()
                            if tid and tid not in manual_ids:
                                manual_ids.add(tid)

                    # Record all found tool_call_ids
                    for tid in manual_ids:
                        stats.tool_call_ids.add(tid)
                        step_id, type_code, task_idx, tool_info = classify_tool_call_id(tid)

                        logger.info(
                            "Tool call ID found: id=%s step=%s type_code=%s tool=%s",
                            tid, step_id, type_code, tool_info
                        )

                        if step_id and type_code in ("s", "t"):
                            stats.unified_tool_call_ids.add(tid)
                            stats.tool_calls_by_step[step_id].add(tid)
                        else:
                            stats.legacy_tool_call_ids.add(tid)

                    for update in updates:
                        stats.stream_tool_updates.append(update)
                        tid = update.get("tool_call_id", "")
                        if tid:
                            stats.tool_call_ids.add(tid)
                            step_id, type_code, task_idx, tool_info = classify_tool_call_id(tid)

                            if step_id and type_code in ("s", "t"):
                                stats.unified_tool_call_ids.add(tid)
                                stats.tool_calls_by_step[step_id].add(tid)
                            else:
                                stats.legacy_tool_call_ids.add(tid)

        # Handle custom mode events (stream tool wire events, subagent events)
        elif mode == "custom":
            if isinstance(data, dict):
                inner_type = data.get("type", "")

                # Also log full data for non-status events
                if inner_type and inner_type not in ("status", "daemon_status"):
                    logger.info(
                        "Custom event payload: type=%s payload=%s",
                        inner_type,
                        json.dumps(data, separators=(",", ":"))[:300]
                    )

                if inner_type == STREAM_TOOL_CALL_UPDATE:
                    stats.stream_tool_updates.append(data)
                    tool_call_id = data.get("tool_call_id", "")
                    name = data.get("name", "")
                    args = data.get("args", {})

                    if tool_call_id:
                        stats.tool_call_ids.add(tool_call_id)
                        step_id, type_code, task_idx, tool_info = classify_tool_call_id(tool_call_id)

                        if step_id:
                            stats.unified_tool_call_ids.add(tool_call_id)
                            stats.tool_calls_by_step[step_id].add(tool_call_id)

                            if type_code == "t":
                                logger.debug(
                                    "Task-level tool: id=%s step=%s task_idx=%s tool=%s",
                                    tool_call_id, step_id, task_idx, tool_info
                                )
                            elif type_code == "s":
                                logger.debug(
                                    "Step-level tool: id=%s step=%s tool=%s",
                                    tool_call_id, step_id, tool_info
                                )
                                if name == "task":
                                    stats.task_tool_calls.add(tool_call_id)
                                    subagent_type = args.get("subagent_type", "?")
                                    stats.task_scopes[tool_call_id] = (tool_call_id, subagent_type, step_id)
                        else:
                            stats.legacy_tool_call_ids.add(tool_call_id)
                            stats.errors.append(
                                f"Legacy tool_call_id without unified format: {tool_call_id}"
                            )

                elif inner_type in ALLOWLISTED_SUBAGENT_EVENT_TYPES:
                    stats.subagent_events_by_type[inner_type] += 1
                    agent = parse_subagent_wire_agent(inner_type)
                    if agent:
                        stats.subagent_events_by_agent[agent] += 1

                    step_id = data.get("step_id", "")
                    if step_id:
                        logger.debug(
                            "Subagent event: type=%s agent=%s step=%s",
                            inner_type, agent, step_id
                        )

                elif inner_type:
                    logger.debug("Custom inner event type: %s", inner_type)

        return

    # Check for stream tool call update events (unwrapped)
    if event_type == STREAM_TOOL_CALL_UPDATE:
        stats.stream_tool_updates.append(event)
        tool_call_id = event.get("tool_call_id", "")
        name = event.get("name", "")
        args = event.get("args", {})

        if tool_call_id:
            stats.tool_call_ids.add(tool_call_id)
            step_id, type_code, task_idx, tool_info = classify_tool_call_id(tool_call_id)

            if step_id:
                stats.unified_tool_call_ids.add(tool_call_id)
                stats.tool_calls_by_step[step_id].add(tool_call_id)

                if type_code == "t":
                    logger.debug(
                        "Task-level tool: id=%s step=%s task_idx=%s tool=%s",
                        tool_call_id, step_id, task_idx, tool_info
                    )
                elif type_code == "s":
                    logger.debug(
                        "Step-level tool: id=%s step=%s tool=%s",
                        tool_call_id, step_id, tool_info
                    )
                    if name == "task":
                        stats.task_tool_calls.add(tool_call_id)
                        subagent_type = args.get("subagent_type", "?")
                        stats.task_scopes[tool_call_id] = (tool_call_id, subagent_type, step_id)
            else:
                stats.legacy_tool_call_ids.add(tool_call_id)
                stats.errors.append(
                    f"Legacy tool_call_id without unified format: {tool_call_id}"
                )

    # Check for subagent wire events (unwrapped)
    elif event_type in ALLOWLISTED_SUBAGENT_EVENT_TYPES:
        stats.subagent_events_by_type[event_type] += 1
        agent = parse_subagent_wire_agent(event_type)
        if agent:
            stats.subagent_events_by_agent[agent] += 1

        step_id = event.get("step_id", "")
        if step_id:
            logger.debug(
                "Subagent event: type=%s agent=%s step=%s",
                event_type, agent, step_id
            )

    # Check for messages stream events (unwrapped)
    elif event_type == "stream" or event.get("mode") == "messages":
        data = event.get("data")
        if isinstance(data, (list, tuple)) and len(data) >= 1:
            msg = data[0]
            if isinstance(msg, dict):
                updates = extract_tool_call_updates_from_wire_message(msg)
                for update in updates:
                    stats.stream_tool_updates.append(update)
                    tid = update.get("tool_call_id", "")
                    if tid:
                        stats.tool_call_ids.add(tid)
                        step_id, type_code, task_idx, tool_info = classify_tool_call_id(tid)

                        if step_id:
                            stats.unified_tool_call_ids.add(tid)
                            stats.tool_calls_by_step[step_id].add(tid)
                        else:
                            stats.legacy_tool_call_ids.add(tid)


def print_summary(stats: EventStats) -> None:
    """Print verification summary."""

    print("\n" + "=" * 80)
    print("DAEMON EVENT VERIFICATION SUMMARY")
    print("=" * 80)

    print(f"\nTotal events received: {stats.total_events}")

    print("\n--- Events by Type ---")
    for event_type, count in sorted(stats.events_by_type.items(), key=lambda x: -x[1]):
        print(f"  {event_type}: {count}")

    print("\n--- Tool Call ID Classification ---")
    print(f"  Total tool_call_ids: {len(stats.tool_call_ids)}")
    print(f"  Unified format (IG-416): {len(stats.unified_tool_call_ids)}")
    print(f"  Legacy format: {len(stats.legacy_tool_call_ids)}")

    if stats.legacy_tool_call_ids:
        print("\n  Legacy IDs (need unified format):")
        for tid in sorted(stats.legacy_tool_call_ids)[:10]:
            print(f"    - {tid}")
        if len(stats.legacy_tool_call_ids) > 10:
            print(f"    ... and {len(stats.legacy_tool_call_ids) - 10} more")

    print("\n--- Tool Calls by Step ---")
    for step_id, tids in sorted(stats.tool_calls_by_step.items()):
        print(f"  Step {step_id}: {len(tids)} tool calls")
        for tid in sorted(tids)[:5]:
            _, type_code, task_idx, tool_info = classify_tool_call_id(tid)
            type_label = "step" if type_code == "s" else f"task[{task_idx}]"
            print(f"    - {tid} ({type_label}: {tool_info})")

    print("\n--- Task Delegation ---")
    print(f"  Task tool calls: {len(stats.task_tool_calls)}")
    for tid in sorted(stats.task_tool_calls):
        scope = stats.task_scopes.get(tid)
        if scope:
            _, subagent_type, step_id = scope
            print(f"    - {tid}: subagent={subagent_type} step={step_id}")

    print("\n--- Stream Tool Wire Events ---")
    print(f"  Total: {len(stats.stream_tool_updates)}")
    # Group by tool name
    by_name = defaultdict(list)
    for update in stats.stream_tool_updates:
        by_name[update.get("name", "unknown")].append(update)
    for name, updates in sorted(by_name.items(), key=lambda x: -len(x[1])):
        print(f"  {name}: {len(updates)} updates")

    # --- Args Accumulation Summary ---
    print("\n--- Args Accumulation (Streaming Chunk Merge) ---")
    if stats.pending_tool_calls:
        print(f"  Pending tool calls tracked: {len(stats.pending_tool_calls)}")
        for tc_id, state in sorted(stats.pending_tool_calls.items()):
            args_str = state.get("args_str", "")
            is_complete = state.get("is_complete_json", False)
            name = state.get("name", "unknown")
            from_terminal = state.get("_from_terminal", False)

            # Try to parse accumulated args
            parsed_args = {}
            parse_error = None
            if args_str:
                try:
                    parsed = json.loads(args_str)
                    if isinstance(parsed, dict):
                        parsed_args = parsed
                except json.JSONDecodeError as e:
                    parse_error = str(e)[:50]

            status = "✓ complete" if is_complete else ("✓ terminal" if from_terminal else "⏳ partial")
            if parse_error:
                status = f"⚠ parse error: {parse_error}"

            args_preview = str(parsed_args)[:80] if parsed_args else args_str[:80]
            print(f"  {tc_id}:")
            print(f"    name: {name}")
            print(f"    status: {status}")
            print(f"    args: {args_preview if args_preview else '(empty)'}")
    else:
        print("  No tool calls tracked for args accumulation")

    print("\n--- Subagent Wire Events ---")
    print(f"  Total: {sum(stats.subagent_events_by_type.values())}")
    for agent, count in sorted(stats.subagent_events_by_agent.items()):
        print(f"  Agent '{agent}': {count} events")
    for event_type, count in sorted(stats.subagent_events_by_type.items()):
        print(f"    {event_type}: {count}")

    print("\n--- Validation Errors ---")
    if stats.errors:
        print(f"  {len(stats.errors)} errors found:")
        for err in stats.errors[:20]:
            print(f"    - {err}")
        if len(stats.errors) > 20:
            print(f"    ... and {len(stats.errors) - 20} more")
    else:
        print("  No validation errors")

    print("\n" + "=" * 80)

    # Return pass/fail status
    has_unified = len(stats.unified_tool_call_ids) > 0
    has_errors = len(stats.errors) > 0
    has_legacy = len(stats.legacy_tool_call_ids) > 0

    if has_unified and not has_errors:
        print("VERIFICATION PASSED: Unified tool call IDs are correctly formatted")
        return True
    elif has_errors:
        print("VERIFICATION FAILED: Validation errors detected")
        return False
    elif has_legacy and not has_unified:
        print("VERIFICATION INCOMPLETE: Only legacy tool_call_ids found (daemon may not be using IG-416)")
        return None
    else:
        print("VERIFICATION INCOMPLETE: No tool_call_ids found in events")
        return None


async def run_verification(
    daemon_url: str,
    test_prompt: str,
    timeout: float,
) -> EventStats:
    """Run verification by connecting to daemon and collecting events."""

    stats = EventStats()
    client = WebSocketClient(daemon_url, client_id="verify_events")

    logger.info("Connecting to daemon at %s", daemon_url)

    try:
        await client.connect()
        logger.info("Connected to daemon")

        # Wait for daemon ready
        try:
            ready_event = await client.wait_for_daemon_ready(ready_timeout_s=5.0)
            logger.info("Daemon ready: state=%s", ready_event.get("state"))
        except RuntimeError as e:
            logger.warning("Daemon readiness check failed: %s", e)
        except TimeoutError:
            logger.warning("Daemon readiness timeout (continuing anyway)")

        # Create a new loop
        request_id = "verify_new_loop"
        await client.send_loop_new(request_id=request_id)

        # Wait for loop_new_response
        loop_id = None
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            event = await client.read_event()
            if event is None:
                break

            validate_event(event, stats)

            if event.get("request_id") == request_id:
                if event.get("type") == "loop_new_response":
                    loop_id = event.get("loop_id")
                    logger.info("Created loop: %s", loop_id)
                    break
                elif event.get("type") == "error":
                    logger.error("Failed to create loop: %s", event.get("message"))
                    break

        if not loop_id:
            logger.error("No loop_id received from daemon")
            return stats

        # Subscribe to the loop
        subscribe_request_id = "verify_subscribe"
        await client.send_loop_subscribe(loop_id, verbosity="debug", request_id=subscribe_request_id)

        # Wait for subscription confirmation
        subscribed = False
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            event = await client.read_event()
            if event is None:
                break

            validate_event(event, stats)

            if event.get("request_id") == subscribe_request_id:
                if event.get("type") == "loop_subscribe_response":
                    subscribed = True
                    logger.info("Subscribed to loop: %s", loop_id)
                    break
                elif event.get("type") == "error":
                    logger.error("Failed to subscribe to loop: %s", event.get("message"))
                    break

        if not subscribed:
            logger.error("Failed to subscribe to loop")
            return stats

        # Send test input
        logger.info("Sending test prompt: %s", test_prompt[:100])
        await client.send_loop_input(loop_id, test_prompt, request_id="verify_input")

        # Collect events until timeout or completion
        logger.info("Collecting events for %s seconds...", timeout)
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:
            event = await client.read_event()
            if event is None:
                # Connection closed
                logger.info("Connection closed by daemon")
                break

            validate_event(event, stats)

            # Log important events
            event_type = event.get("type", "")
            if event_type.startswith("soothe.stream.") or event_type.startswith("soothe.subagent."):
                logger.info(
                    "Wire event: %s (%s)",
                    event_type,
                    json.dumps(event, separators=(",", ":"))[:200]
                )
            elif event_type == "step_started":
                logger.info("Step started: %s", event.get("step_id"))
            elif event_type == "step_completed":
                logger.info("Step completed: %s", event.get("step_id"))
            elif event_type == "loop_completed":
                logger.info("Loop completed: %s", loop_id)
                break
            elif event_type == "error":
                logger.error("Daemon error: %s", event.get("message"))

        logger.info("Event collection complete")

    except ConnectionError as e:
        logger.error("Connection error: %s", e)
        stats.errors.append(f"Connection error: {e}")
    except TimeoutError as e:
        logger.error("Timeout: %s", e)
        stats.errors.append(f"Timeout: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        stats.errors.append(f"Unexpected error: {e}")
    finally:
        await client.close()
        logger.info("Disconnected from daemon")

    return stats


def main() -> int:
    """Main entry point."""

    parser = argparse.ArgumentParser(
        description="Verify daemon broadcast events without TUI logic"
    )
    parser.add_argument(
        "--daemon-url",
        default="ws://localhost:8765",
        help="Daemon WebSocket URL (default: ws://localhost:8765)",
    )
    parser.add_argument(
        "--prompt",
        default="List the files in the current directory and read the README if it exists",
        help="Test prompt to send to daemon",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds for event collection (default: 60)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting daemon event verification")
    logger.info("Daemon URL: %s", args.daemon_url)
    logger.info("Test prompt: %s", args.prompt[:100])
    logger.info("Timeout: %s seconds", args.timeout)

    stats = asyncio.run(run_verification(
        daemon_url=args.daemon_url,
        test_prompt=args.prompt,
        timeout=args.timeout,
    ))

    result = print_summary(stats)

    if result is True:
        return 0
    elif result is False:
        return 1
    else:
        return 2  # Incomplete


if __name__ == "__main__":
    sys.exit(main())