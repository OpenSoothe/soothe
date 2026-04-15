"""Extract human-visible text from LangChain-style AI messages."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_text_from_ai_message(msg: Any) -> list[str]:
    """Extract text content from AI messages for conversation logging.

    Handles both LangChain AIMessage objects and deserialized dicts.

    Args:
        msg: Message object (AIMessage or dict).

    Returns:
        List of text strings extracted from the message.
    """
    texts: list[str] = []
    try:
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
        elif hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
            texts.append(msg.content)
        elif isinstance(msg, dict):
            blocks = msg.get("content_blocks") or []
            if not blocks:
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    texts.append(content)
            else:
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
    except Exception:
        logger.debug("Failed to extract assistant text", exc_info=True)

    return texts
