"""Extract parseable text and JSON objects from provider AIMessage responses."""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def text_from_message_content(content: Any) -> str:
    """Flatten AIMessage ``content`` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type in ("text", "output_text"):
                    parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content)


def llm_response_text(response: Any) -> str:
    """Return parseable text from an AIMessage-like response.

    Thinking models may put JSON in ``additional_kwargs["reasoning_content"]``
    or list-style ``content`` blocks while leaving primary ``content`` empty.
    """
    if hasattr(response, "content") and response.content:
        return text_from_message_content(response.content)
    kwargs = getattr(response, "additional_kwargs", None) or {}
    if isinstance(kwargs, dict):
        reasoning = kwargs.get("reasoning_content")
        if reasoning:
            return str(reasoning)
    return str(response)


def parse_json_object(content: str) -> dict[str, Any] | None:
    """Parse a JSON object from model output (raw or markdown-fenced)."""
    text = (content or "").strip()
    if not text:
        return None

    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
    return None


__all__ = ["llm_response_text", "parse_json_object", "text_from_message_content"]
