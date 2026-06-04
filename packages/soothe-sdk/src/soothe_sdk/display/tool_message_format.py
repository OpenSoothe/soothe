"""Format LangChain ``ToolMessage`` content for summaries and step-card stats."""

from __future__ import annotations

import json
from typing import Any

# Serialized shape historically used by ``RunPythonTool`` (dict envelope); REPL tools may return plain text.
_RUN_PYTHON_RESULT_KEYS: frozenset[str] = frozenset({"success", "output", "result", "error"})


def try_parse_run_python_result_envelope(text: str) -> dict[str, Any] | None:
    """If ``text`` is JSON for ``run_python``, return the dict; else ``None``.

    Uses a strict key check so arbitrary JSON containing the word ``error`` is not
    mistaken for this envelope (and substring heuristics are never applied to it).

    Args:
        text: Tool message body (often a single JSON object string).

    Returns:
        Parsed dict when keys match the run_python contract; otherwise ``None``.
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if not _RUN_PYTHON_RESULT_KEYS.issubset(obj.keys()):
        return None
    return obj


def run_python_envelope_indicates_failure(env: dict[str, Any]) -> bool:
    """Match server-side failure semantics: ``not success`` or truthy ``error``."""
    if not env.get("success"):
        return True
    err = env.get("error")
    return bool(err)


def format_content_block_for_tool_display(block: dict[str, Any]) -> str:
    """Format a single multimodal / structured content block for terminal display.

    Replaces large binary payloads (e.g. base64 image/video data) with a
    human-readable placeholder so they do not flood the terminal.

    Args:
        block: A content block dict (image, video, file, etc.).

    Returns:
        A display-friendly string for the block.
    """
    if block.get("type") == "image" and isinstance(block.get("base64"), str):
        b64 = block["base64"]
        size_kb = len(b64) * 3 // 4 // 1024  # approximate decoded size
        mime = block.get("mime_type", "image")
        return f"[Image: {mime}, ~{size_kb}KB]"
    if block.get("type") == "video" and isinstance(block.get("base64"), str):
        b64 = block["base64"]
        size_kb = len(b64) * 3 // 4 // 1024  # approximate decoded size
        mime = block.get("mime_type", "video")
        return f"[Video: {mime}, ~{size_kb}KB]"
    if block.get("type") == "file" and isinstance(block.get("base64"), str):
        b64 = block["base64"]
        size_kb = len(b64) * 3 // 4 // 1024  # approximate decoded size
        mime = block.get("mime_type", "file")
        return f"[File: {mime}, ~{size_kb}KB]"
    try:
        return json.dumps(block, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(block)


def format_tool_message_content(content: Any) -> str:  # noqa: ANN401
    """Convert ``ToolMessage`` content into a printable string.

    Handles ``str``, ``list`` (multimodal / block segments), and other types.

    Args:
        content: Raw ``ToolMessage.content`` value.

    Returns:
        Flattened string suitable for briefs, logging, and status lines.
    """
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(format_content_block_for_tool_display(item))
            else:
                try:
                    parts.append(json.dumps(item, ensure_ascii=False))
                except (TypeError, ValueError):
                    parts.append(str(item))
        return "\n".join(parts)
    return str(content)


__all__ = [
    "format_content_block_for_tool_display",
    "format_tool_message_content",
    "run_python_envelope_indicates_failure",
    "try_parse_run_python_result_envelope",
]
