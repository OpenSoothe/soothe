"""Extract plain text from streamed LangChain-style messages (CLI-local, no soothe core)."""

from __future__ import annotations

from typing import Any

from soothe_sdk.client.wire import flatten_enveloped_message_dict


def wire_message_body(msg: Any) -> Any:
    """Return the flat wire body for a daemon message dict (unwrap ``data`` envelope)."""
    if not isinstance(msg, dict):
        return msg
    return flatten_enveloped_message_dict(msg)


def extract_text_from_message_content(content: Any) -> str:
    """Flatten message ``content`` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return ""


def extract_plain_text_from_stream_message(msg: Any) -> str:
    """Best-effort plain text from an AIMessage object or wire dict."""
    if msg is None:
        return ""
    if hasattr(msg, "content_blocks") and msg.content_blocks:
        texts: list[str] = []
        for block in msg.content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    texts.append(str(text))
        if texts:
            return "".join(texts)
    if hasattr(msg, "content"):
        return extract_text_from_message_content(getattr(msg, "content", None))
    if isinstance(msg, dict):
        body = wire_message_body(msg)
        blocks = body.get("content_blocks") or []
        if blocks:
            texts = []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(str(text))
            return "".join(texts)
        content = body.get("content", "")
        if isinstance(content, str):
            return content
        return extract_text_from_message_content(content)
    return ""


__all__ = [
    "extract_plain_text_from_stream_message",
    "extract_text_from_message_content",
    "wire_message_body",
]
