"""Shared message-display filtering for live and recovered TUI rendering."""

from __future__ import annotations

from typing import Any

from soothe_sdk.client.wire import envelope_langchain_message_dict


def normalize_stream_message(message: Any) -> Any:
    """Best-effort conversion of wire dict payloads to LangChain message objects."""
    if not isinstance(message, dict):
        return message
    try:
        from langchain_core.messages import messages_from_dict

        wrapped = envelope_langchain_message_dict(message)
        restored = messages_from_dict([wrapped])
        if restored:
            return restored[0]
    except Exception:
        return message
    return message


def extract_user_text_for_display(message: Any) -> str | None:
    """Return displayable user text, excluding internal system markers."""
    from langchain_core.messages import HumanMessage

    if not isinstance(message, HumanMessage):
        return None
    content = message.content if isinstance(message.content, str) else str(message.content)
    text = content.strip()
    if not text or text.startswith("[SYSTEM]"):
        return None
    return text


def extract_ai_text_for_display(message: Any) -> str:
    """Extract assistant-visible text from AI message payloads."""
    try:
        if hasattr(message, "text"):
            extracted = str(message.text() or "").strip()
            if extracted:
                return extracted
    except Exception:
        pass

    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block_text = str(block.get("text", "")).strip()
                if block_text:
                    parts.append(block_text)
            elif isinstance(block, str):
                block_text = block.strip()
                if block_text:
                    parts.append(block_text)
        return "".join(parts).strip()

    return ""


def extract_message_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Extract tool call dicts from an AI message/chunk for card rendering."""
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    tool_call_chunks = list(getattr(message, "tool_call_chunks", None) or [])
    return [call for call in [*tool_call_chunks, *tool_calls] if isinstance(call, dict)]
