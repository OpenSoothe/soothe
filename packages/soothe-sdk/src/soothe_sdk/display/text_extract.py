"""Shared message-display filtering for live and recovered TUI rendering.

Lives in the SDK (RFC-413) so the daemon-resident ``CardBinder`` can reuse
it without importing client code.
"""

from __future__ import annotations

from typing import Any


def normalize_stream_message(message: Any) -> Any:
    """Best-effort conversion of wire dict payloads to LangChain message objects."""
    if not isinstance(message, dict):
        return message
    try:
        from soothe_sdk.langchain_wire import deserialize_langchain_message_from_wire

        restored = deserialize_langchain_message_from_wire(message)
        if restored is not message:
            return restored
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
    from langchain_core.messages import AIMessageChunk

    preserve_whitespace = isinstance(message, AIMessageChunk)

    try:
        if hasattr(message, "text"):
            # LangChain TextAccessor: use property/str(), not .text() (deprecated).
            extracted = str(message.text or "")
            if preserve_whitespace:
                if extracted:
                    return extracted
            elif extracted.strip():
                return extracted.strip()
    except Exception:
        pass

    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content if preserve_whitespace else content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block_text = str(block.get("text", ""))
                if preserve_whitespace:
                    if block_text:
                        parts.append(block_text)
                else:
                    block_text = block_text.strip()
                    if block_text:
                        parts.append(block_text)
            elif isinstance(block, str):
                if preserve_whitespace:
                    if block:
                        parts.append(block)
                else:
                    block_text = block.strip()
                    if block_text:
                        parts.append(block_text)
        joined = "".join(parts)
        return joined if preserve_whitespace else joined.strip()

    return ""
