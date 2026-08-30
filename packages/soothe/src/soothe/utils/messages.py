"""LangChain message-content text extraction helpers."""

from __future__ import annotations

from typing import Any

__all__ = [
    "extract_text_from_message_content",
    "join_text_fragments",
]


def join_text_fragments(parts: list[str]) -> str:
    """Join text fragments with newline separators between content blocks."""
    return "\n".join(parts) if parts else ""


def extract_text_from_message_content(content: Any) -> str:
    """Flatten LangChain message `content` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return join_text_fragments(parts)
    return ""
