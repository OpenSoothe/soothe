"""Shared utilities for platform channel implementations.

Migrated from nanoBot's nanobot.utils.helpers with adaptations for soothe-daemon.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Filename sanitization
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores.

    Args:
        name: Original filename.

    Returns:
        Sanitized filename safe for filesystem use.
    """
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text with a stable suffix.

    Args:
        text: Text to truncate.
        max_chars: Maximum character limit.

    Returns:
        Truncated text with suffix if needed.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes.

    Args:
        data: Image binary data.

    Returns:
        MIME type string or None if unrecognized.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(
    raw: bytes, mime: str, path: str, label: str
) -> list[dict[str, Any]]:
    """Build native image blocks plus a short text label.

    Args:
        raw: Image binary data.
        mime: MIME type.
        path: File path for metadata.
        label: Text label to append.

    Returns:
        List of content blocks for LLM vision input.
    """
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


def strip_think(text: str) -> str:
    """Remove thinking blocks from model output.

    Handles Anthropic-style thinking blocks and other model-specific formats.

    Args:
        text: Text with potential thinking blocks.

    Returns:
        Cleaned text without thinking blocks.
    """
    # Remove well-formed <thought> blocks
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text)
    # Remove unclosed <thought> at start
    text = re.sub(r"^\s*<thought>[\s\S]*$", "", text)
    # Malformed opening tags (missing >)
    text = re.sub(r"<think(?![A-Za-z0-9_\-:>/])", "", text)
    text = re.sub(r"<thought(?![A-Za-z0-9_\-:>/])", "", text)
    # Orphan closing tags at edges
    text = re.sub(r"^\s*</thought>\s*", "", text)
    text = re.sub(r"\s*</thought>\s*$", "", text)
    # Channel markers
    text = re.sub(r"^\s*<\|?channel\|?>\s*", "", text)
    # Partial control tags at end
    partial_control_tag = (
        r"</?(?:t|th|thi|thin|think|tho|thou|thoug|though|thought)>?"
        r"|<\|?(?:c|ch|cha|chan|chann|channe|channel)(?:\|?>?)?"
    )
    text = re.sub(rf"(?:{partial_control_tag})$", "", text)
    return text.strip()


def extract_think(text: str) -> tuple[str | None, str]:
    """Extract thinking content from inline blocks.

    Args:
        text: Text with potential thinking blocks.

    Returns:
        Tuple of (thinking_text, cleaned_text).
    """
    parts: list[str] = []
    for m in re.finditer(r"<thought>([\s\S]*?)</thought>", text):
        parts.append(m.group(1).strip())
    thinking = "\n\n".join(parts) if parts else None
    return thinking, strip_think(text)


def escape_html(text: str) -> str:
    """Escape HTML special characters.

    Args:
        text: Text to escape.

    Returns:
        HTML-safe text.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_markdown_inline(text: str) -> str:
    """Strip markdown inline formatting from text.

    Args:
        text: Markdown formatted text.

    Returns:
        Plain text without markdown syntax.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def strip_markdown_block(text: str) -> str:
    """Strip block-level and inline markdown for readable plain-text preview.

    Args:
        text: Markdown formatted text.

    Returns:
        Plain text suitable for display during streaming edits.
    """
    # Code blocks -> just the code
    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", r"\1", text)
    # Headers -> plain text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)
    # Bold / italic / strikethrough
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bullet lists
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)
    # Numbered lists
    text = re.sub(r"^(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)
    return text


__all__ = [
    "build_image_content_blocks",
    "detect_image_mime",
    "escape_html",
    "extract_think",
    "safe_filename",
    "split_message",
    "strip_markdown_block",
    "strip_markdown_inline",
    "strip_think",
    "truncate_text",
]
