"""Shared helpers for structured intent_hint integration tests."""

from __future__ import annotations

import asyncio
import json
from typing import Any

WORD_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"word": {"type": "string"}},
    "required": ["word"],
    "additionalProperties": False,
}


def _unwrap_next(event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Unwrap a protocol-1 ``next`` envelope to its inner ``data`` frame.

    Under protocol-1 (RFC-450 §9.3) streamed ``event`` frames arrive wrapped as
    ``{proto, type:"next", payload:{namespace, mode, data}}``. This helper
    returns the inner ``data`` dict (the legacy ``{type:"event", mode, data}``
    frame) so the extraction helpers can branch on the legacy shape. Non-``next``
    frames pass through unchanged.
    """
    if not isinstance(event, dict):
        return event
    if event.get("type") != "next":
        return event
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return event
    data = payload.get("data")
    return data if isinstance(data, dict) else event


def extract_messages_assistant_content(event: dict[str, Any]) -> str | None:
    """Parse assistant text from a daemon ``mode=messages`` event."""
    frame = _unwrap_next(event)
    if not isinstance(frame, dict) or frame.get("type") != "event":
        return None
    if frame.get("mode") != "messages":
        return None
    data = frame.get("data")
    msg: Any
    if isinstance(data, (list, tuple)) and data:
        msg = data[0]
    elif isinstance(data, dict):
        msg = data
    else:
        return None
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        stripped = content.strip()
        return stripped if stripped else None
    return None


async def await_messages_assistant_content(
    read_event,
    *,
    timeout: float = 90.0,
) -> str:
    """Read events until a non-empty assistant message is received."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = "Timed out waiting for mode=messages assistant content"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(read_event(), timeout=max(remaining, 0.001))
        if not event:
            continue
        if event.get("type") == "error":
            err = event.get("error") or {}
            code = err.get("code", event.get("code", ""))
            message = err.get("message", event.get("message", ""))
            raise AssertionError(f"daemon error {code}: {message}")
        content = extract_messages_assistant_content(event)
        if content:
            return content


def parse_word_reply_json(raw: str) -> dict[str, Any]:
    """Parse and minimally validate the word-reply integration schema."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        msg = f"expected JSON object, got {type(data).__name__}"
        raise TypeError(msg)
    word = data.get("word")
    if not isinstance(word, str) or not word.strip():
        msg = "missing or empty word field"
        raise ValueError(msg)
    return data
