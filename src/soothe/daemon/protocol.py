"""IPC protocol for Soothe daemon communication."""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


def _serialize_for_json(obj: Any) -> Any:
    """Serialize objects for JSON, handling LangChain messages specially."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, (list, tuple)):
        return [_serialize_for_json(item) for item in obj]

    if isinstance(obj, dict):
        return {str(k): _serialize_for_json(v) for k, v in obj.items()}

    if hasattr(obj, "model_dump"):
        with contextlib.suppress(Exception):
            dumped = obj.model_dump()
            return _serialize_for_json(dumped)

    if hasattr(obj, "dict"):
        with contextlib.suppress(Exception):
            return _serialize_for_json(obj.dict())

    if hasattr(obj, "__dict__"):
        with contextlib.suppress(Exception):
            return _serialize_for_json(obj.__dict__)

    return str(obj)


def encode(msg: dict[str, Any]) -> bytes:
    """Encode a message as JSON with newline delimiter.

    Args:
        msg: Message dictionary to encode.

    Returns:
        JSON-encoded bytes with trailing newline.
    """
    serialized = _serialize_for_json(msg)
    return (json.dumps(serialized) + "\n").encode()


def decode(line: bytes) -> dict[str, Any] | None:
    """Decode a JSON line into a message dictionary.

    Args:
        line: Raw bytes line to decode.

    Returns:
        Parsed message dict, or None if empty or invalid.
    """
    text = line.decode().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Invalid daemon protocol line: %s", preview_first(text, 120))
        return None
