"""Shared streaming helper for Soothe examples.

Provides ``run_with_streaming`` which replaces blocking ``invoke()`` with
``astream()`` so that tool calls, LLM text, and subagent custom events are
rendered in real-time.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph


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


def _handle_ai_message(message_obj: AIMessage) -> None:
    """Render AI message content blocks: text tokens and tool call names."""
    if not hasattr(message_obj, "content_blocks"):
        return
    for block in message_obj.content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
        elif block_type in {"tool_call_chunk", "tool_call"}:
            name = block.get("name")
            if name:
                print(f"\n  [tool] Calling: {name}", flush=True)


def _handle_tool_message(message_obj: ToolMessage) -> None:
    """Print a truncated preview of a tool result."""
    content = message_obj.content
    if isinstance(content, list):
        try:
            content = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            content = str(content)
    elif not isinstance(content, str):
        content = str(content)
    print(f"  [tool] Result: {_truncate(content)}", flush=True)


async def run_with_streaming(
    agent: CompiledStateGraph,
    messages: list[HumanMessage],
    *,
    show_subagents: bool = False,
) -> None:
    """Stream agent execution with real-time progress output.

    Args:
        agent: A compiled Soothe agent graph.
        messages: List of input messages (typically one HumanMessage).
        show_subagents: When True, also render subagent custom progress
            events (from ``get_stream_writer()``). Internal subagent message
            traffic (AI text tokens, tool results) is always suppressed to
            avoid noisy output.
    """
    print("[streaming] Starting agent...\n", flush=True)

    try:
        async for chunk in agent.astream(
            {"messages": messages},
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        ):
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            namespace, mode, data = chunk
            is_main = not namespace

            if mode == "messages":
                if not is_main:
                    continue
                if not isinstance(data, tuple) or len(data) != 2:
                    continue
                message_obj, metadata = data

                if metadata and metadata.get("lc_source") == "summarization":
                    continue

                if isinstance(message_obj, AIMessage):
                    _handle_ai_message(message_obj)
                elif isinstance(message_obj, ToolMessage):
                    _handle_tool_message(message_obj)

            elif mode == "custom":
                if not is_main and not show_subagents:
                    continue
                line = _format_custom_event(data)
                if line:
                    print(f"\n  {line}", flush=True)

            elif mode == "updates":
                if isinstance(data, dict) and "__interrupt__" in data:
                    print("\n  [interrupt] Agent interrupted", flush=True)

    except Exception as exc:
        print(f"\n\n[streaming] Error: {type(exc).__name__}: {exc}", flush=True)

    print("\n\n[streaming] Done.", flush=True)
