"""Format LangChain ``ToolMessage`` content for CLI/TUI (shared, TUI-free).

Moved from ``soothe_cli.tui.tool_display`` so headless and TUI share one implementation.
"""

from __future__ import annotations

import json
from typing import Any


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
        Flattened string suitable for tool cards and CLI summaries.
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
]
