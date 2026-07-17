"""LangChain wire message normalization for stream preparation."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_lc_stream_message(message: Any) -> Any:
    """Turn daemon JSON dicts into LangChain message objects when possible."""
    if not isinstance(message, dict):
        return message
    try:
        from soothe_sdk.wire.codec import deserialize_langchain_message_from_wire

        restored = deserialize_langchain_message_from_wire(message)
        if restored is not message:
            return restored
    except Exception:
        logger.debug("Could not restore LangChain message from dict", exc_info=True)
    return message


def is_summarization_chunk(metadata: dict | None) -> bool:
    """Return True when metadata marks a summarization middleware chunk."""
    if metadata is None:
        return False
    return metadata.get("lc_source") == "summarization"
