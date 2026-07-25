"""Shared streaming helpers for Soothe examples.

Provides two streaming entrypoints:

- ``run_with_streaming`` — replaces blocking ``invoke()`` with ``astream()`` so
  that tool calls, LLM text, and subagent custom events are rendered in
  real-time for CoreAgent examples.
- ``stream_soothe_runner`` — streams ``SootheRunner.astream`` (StrangeLoop,
  non-autopilot) to stdout with quiet fj-style progress lines.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from soothe.runner import SootheRunner

SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Planner",
    "scout": "Scout",
    "deep_research": "Deep Research",
}

_TASK_NAME_RE = re.compile(r'"?name"?\s*:\s*"?(\w+)"?')


def _truncate(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_custom_event(data: Any) -> str | None:
    """Format a custom event dict into a single display line."""
    if not isinstance(data, dict):
        return f"[custom] {data}"
    event_type = data.get("type", "unknown")
    parts = [f"[custom] {event_type}"]
    for key, value in data.items():
        if key == "type":
            continue
        if isinstance(value, str) and len(value) > 120:
            value = value[:120] + "…"
        parts.append(f"{key}={value}")
    return ": ".join(parts[:2]) if len(parts) >= 2 else parts[0]


def _resolve_namespace(
    namespace: tuple[Any, ...],
    name_map: dict[str, str],
) -> str:
    """Resolve a namespace tuple to a friendly display label.

    Uses ``name_map`` to translate LangGraph tool-call IDs to capitalised
    subagent names (e.g. ``("tools:abc123",)`` -> ``"Planner"``).
    """
    if not namespace:
        return "main"
    parts: list[str] = []
    for segment in namespace:
        seg_str = str(segment)
        if seg_str in name_map:
            parts.append(name_map[seg_str])
        elif seg_str.startswith("tools:"):
            tool_id = seg_str.split(":", 1)[1] if ":" in seg_str else seg_str
            parts.append(name_map.get(tool_id, seg_str))
        else:
            parts.append(seg_str)
    return "/".join(parts)


def _try_extract_subagent_name(message_obj: AIMessage) -> tuple[str, str] | None:
    """Try to extract (tool_call_id, subagent_name) from a task tool call."""
    tool_calls = getattr(message_obj, "tool_calls", None) or []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if tc.get("name") != "task":
            continue
        call_id = tc.get("id", "")
        args = tc.get("args", {})
        if isinstance(args, dict):
            agent_name = args.get("agent", "") or args.get("name", "")
            if agent_name:
                return (call_id, agent_name)
        args_str = str(args)
        match = _TASK_NAME_RE.search(args_str)
        if match:
            return (call_id, match.group(1))
    return None


def _handle_ai_message(
    message_obj: AIMessage,
    *,
    prefix: str | None = None,
    name_map: dict[str, str] | None = None,
) -> None:
    """Render AI message content blocks: text tokens and tool call names."""
    if name_map is None:
        name_map = {}
    extracted = _try_extract_subagent_name(message_obj)
    if extracted:
        call_id, raw_name = extracted
        display = SUBAGENT_DISPLAY_NAMES.get(raw_name.lower(), raw_name.title())
        name_map[call_id] = display

    header_printed = False
    if hasattr(message_obj, "content_blocks") and message_obj.content_blocks:
        for block in message_obj.content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    if prefix and not header_printed:
                        sys.stdout.write(f"\n  [{prefix}] ")
                        header_printed = True
                    sys.stdout.write(text)
                    sys.stdout.flush()
            elif block_type in {"tool_call_chunk", "tool_call"}:
                name = block.get("name")
                if name:
                    if prefix:
                        print(f"\n  [{prefix}] [tool] Calling: {name}", flush=True)
                    else:
                        print(f"\n  [tool] Calling: {name}", flush=True)
    elif isinstance(message_obj.content, str) and message_obj.content:
        if prefix:
            sys.stdout.write(f"\n  [{prefix}] ")
        sys.stdout.write(message_obj.content)
        sys.stdout.flush()


def _handle_tool_message(message_obj: ToolMessage, *, prefix: str | None = None) -> None:
    """Print a truncated preview of a tool result."""
    content = message_obj.content
    if isinstance(content, list):
        try:
            content = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            content = str(content)
    elif not isinstance(content, str):
        content = str(content)
    if prefix:
        print(f"  [{prefix}] [tool] Result: {_truncate(content)}", flush=True)
    else:
        print(f"  [tool] Result: {_truncate(content)}", flush=True)


async def run_with_streaming(
    agent: CompiledStateGraph,
    messages: list[HumanMessage],
    *,
    show_subagents: bool = False,
    show_subagent_messages: bool = False,
    thread_id: str = "example-thread",
) -> None:
    """Stream agent execution with real-time progress output."""
    print("[streaming] Starting agent...\n", flush=True)

    name_map: dict[str, str] = {}

    try:
        async for chunk in agent.astream(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        ):
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            namespace, mode, data = chunk
            is_main = not namespace

            if mode == "messages":
                if not is_main and not show_subagent_messages:
                    continue
                if not isinstance(data, tuple) or len(data) != 2:
                    continue
                message_obj, metadata = data
                prefix = _resolve_namespace(namespace, name_map) if not is_main else None

                if metadata and metadata.get("lc_source") == "summarization":
                    continue

                if isinstance(message_obj, AIMessage):
                    _handle_ai_message(message_obj, prefix=prefix, name_map=name_map)
                elif isinstance(message_obj, ToolMessage):
                    _handle_tool_message(message_obj, prefix=prefix)

            elif mode == "custom":
                if not is_main and not show_subagents:
                    continue
                line = _format_custom_event(data)
                if line:
                    if is_main:
                        print(f"\n  {line}", flush=True)
                    else:
                        label = _resolve_namespace(namespace, name_map)
                        print(f"\n  [{label}] {line}", flush=True)

            elif mode == "updates":
                if isinstance(data, dict) and "__interrupt__" in data:
                    print("\n  [interrupt] Agent interrupted", flush=True)

    except Exception as exc:
        print(f"\n\n[streaming] Error: {type(exc).__name__}: {exc}", flush=True)

    print("\n\n[streaming] Done.", flush=True)


# --------------------------------------------------------------------------- #
# StrangeLoop (SootheRunner) streaming helpers
# --------------------------------------------------------------------------- #


def _format_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        try:
            return json.dumps(content, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            return str(content)[:200]
    return str(content)[:200]


def _ai_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content) if content else ""


def _accumulate_ai_text(current: str, message: AIMessage) -> str:
    text = _ai_text(message)
    if not text:
        return current
    if isinstance(message, AIMessageChunk):
        if current and text.startswith(current):
            return text
        if current and current.startswith(text) and len(current) >= len(text):
            return current
        return current + text
    if len(text) >= len(current):
        return text
    return current


def _print_progress(event_type: str, data: dict[str, Any]) -> None:
    """Print high-signal StrangeLoop progress lines (fj-style, quiet)."""
    if event_type.endswith(".strange_loop.started"):
        goal = str(data.get("goal") or "")[:80]
        print(f"\n  [StrangeLoop] started — {goal}", flush=True)
        return
    if event_type.endswith(".strange_loop.plan.decision"):
        iteration = data.get("iteration", 0)
        total = data.get("total_steps", 0)
        print(f"  [Plan] iteration={iteration} steps={total}", flush=True)
        return
    if event_type.endswith(".strange_loop.step.started"):
        step = data.get("step_id") or data.get("description") or "?"
        print(f"  [Step] start {step}", flush=True)
        return
    if event_type.endswith(".strange_loop.step.completed"):
        step = data.get("step_id") or data.get("description") or "?"
        status = data.get("status") or "done"
        print(f"  [Step] {status} {step}", flush=True)
        return
    if event_type.endswith(".strange_loop.completed"):
        status = data.get("status") or "unknown"
        progress = data.get("goal_progress") or ""
        summary = str(data.get("completion_summary") or data.get("evidence_summary") or "")
        summary = _truncate(summary, 120)
        print(f"\n  [StrangeLoop] completed status={status} progress={progress}", flush=True)
        if summary:
            print(f"  [Summary] {summary}", flush=True)
        return
    if event_type.endswith(".intent.classified"):
        intent = data.get("intent_type") or "unknown"
        reason = data.get("reasoning")
        suffix = f" — {reason}" if reason else ""
        print(f"  [Intent] {intent}{suffix}", flush=True)


async def stream_soothe_runner(
    runner: SootheRunner,
    query: str,
    *,
    thread_id: str | None = None,
    workspace: str | None = None,
    show_tool_calls: bool = True,
) -> str:
    """Stream ``SootheRunner.astream`` (StrangeLoop, non-autopilot) to stdout.

    Args:
        runner: Initialized host runner.
        query: User query text.
        thread_id: Optional thread for checkpoint resume.
        workspace: Optional workspace root (defaults via runner resolution).
        show_tool_calls: When True, mirror tool call/result previews.

    Returns:
        Accumulated assistant text from the message stream.
    """
    print(f"\n[Query] {query}\n", flush=True)
    print("[Streaming] StrangeLoop via SootheRunner...\n", flush=True)

    final_response = ""

    try:
        async for chunk in runner.astream(
            query,
            thread_id=thread_id,
            workspace=workspace,
        ):
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            _namespace, mode, data = chunk

            if mode == "messages":
                if not isinstance(data, tuple) or len(data) != 2:
                    continue
                message_obj, _metadata = data

                if isinstance(message_obj, AIMessage):
                    prev = final_response
                    final_response = _accumulate_ai_text(final_response, message_obj)
                    delta = final_response[len(prev) :] if final_response.startswith(prev) else ""
                    if delta:
                        sys.stdout.write(delta)
                        sys.stdout.flush()

                    if show_tool_calls and getattr(message_obj, "tool_calls", None):
                        for tc in message_obj.tool_calls:
                            if isinstance(tc, dict):
                                print(f"\n  [Tool Call] {tc.get('name', 'unknown')}", flush=True)

                elif isinstance(message_obj, ToolMessage) and show_tool_calls:
                    preview = _truncate(_format_content(message_obj.content))
                    print(f"\n  [Tool Result] {preview}", flush=True)

            elif mode == "custom" and isinstance(data, dict):
                event_type = str(data.get("type") or "unknown")
                _print_progress(event_type, data)

            elif mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                print("\n  [Interrupted] Agent paused for input", flush=True)

    except Exception as exc:
        print(f"\n\n[Error] {type(exc).__name__}: {exc}", flush=True)
        raise

    print("\n\n[Streaming] Done.", flush=True)
    return final_response
