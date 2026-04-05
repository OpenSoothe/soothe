"""Streaming helper for CoreAgent examples.

Provides ``stream_core_agent`` which wraps CoreAgent.astream() for
real-time output rendering of messages, tool calls, and custom events.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe.core.agent import CoreAgent


def _truncate(text: str, limit: int = 200) -> str:
    """Truncate text to limit characters."""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_content(content: Any) -> str:
    """Format message content for display."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        try:
            return json.dumps(content, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            return str(content)[:200]
    return str(content)[:200]


async def stream_core_agent(
    agent: CoreAgent,
    query: str,
    *,
    thread_id: str = "example-thread",
    show_tool_calls: bool = True,
) -> str:
    """Stream CoreAgent execution with real-time output.

    Args:
        agent: CoreAgent instance to execute.
        query: User query string.
        thread_id: Thread identifier for persistence.
        show_tool_calls: Whether to display tool call results.

    Returns:
        Final response text from the agent.
    """
    print(f"\n[Query] {query}\n", flush=True)
    print("[Streaming] Starting CoreAgent...\n", flush=True)

    messages = [HumanMessage(content=query)]
    config = {"configurable": {"thread_id": thread_id}}

    final_response = ""

    try:
        async for chunk in agent.astream(
            {"messages": messages},
            config=config,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        ):
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            namespace, mode, data = chunk

            if mode == "messages":
                if not isinstance(data, tuple) or len(data) != 2:
                    continue
                message_obj, metadata = data

                if isinstance(message_obj, AIMessage):
                    # Handle AI message content
                    if isinstance(message_obj.content, str) and message_obj.content:
                        sys.stdout.write(message_obj.content)
                        sys.stdout.flush()
                        final_response = message_obj.content

                    # Handle tool calls in AI message
                    if show_tool_calls and hasattr(message_obj, "tool_calls"):
                        for tc in message_obj.tool_calls:
                            if isinstance(tc, dict):
                                tool_name = tc.get("name", "unknown")
                                print(f"\n  [Tool Call] {tool_name}", flush=True)

                elif isinstance(message_obj, ToolMessage):
                    if show_tool_calls:
                        content_preview = _truncate(_format_content(message_obj.content))
                        print(f"\n  [Tool Result] {content_preview}", flush=True)

            elif mode == "custom":
                if isinstance(data, dict):
                    event_type = data.get("type", "unknown")
                    print(f"\n  [Event] {event_type}", flush=True)

            elif mode == "updates":
                if isinstance(data, dict) and "__interrupt__" in data:
                    print("\n  [Interrupted] Agent paused for input", flush=True)

    except Exception as exc:
        print(f"\n\n[Error] {type(exc).__name__}: {exc}", flush=True)
        raise

    print("\n\n[Streaming] Done.", flush=True)
    return final_response
