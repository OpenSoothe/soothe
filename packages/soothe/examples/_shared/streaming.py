"""Streaming helper for SootheRunner (StrangeLoop) examples."""

from __future__ import annotations

import json
import sys
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.runner import SootheRunner


def _truncate(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


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
