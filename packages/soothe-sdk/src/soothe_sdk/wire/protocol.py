"""IPC protocol for Soothe server communication."""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any

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


def encode_websocket_text(msg: dict[str, Any]) -> str:
    """Encode a message as a single WebSocket text frame (no NDJSON newline).

    Uses compact JSON (no extra whitespace) to reduce frame size and avoid
    redundant UTF-8 encode/decode when sending via ``websockets``.

    Args:
        msg: Message dictionary to encode.

    Returns:
        JSON text suitable for ``Connection.send`` as a text frame.
    """
    serialized = _serialize_for_json(msg)
    return json.dumps(serialized, separators=(",", ":"))


def decode_websocket_text(text: str) -> dict[str, Any] | None:
    """Decode JSON from a WebSocket text frame.

    Args:
        text: Raw frame payload (typically one JSON object).

    Returns:
        Parsed message dict, or None if empty or invalid.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        logger.debug("Invalid daemon WebSocket JSON: %s", preview_first(stripped, 120))
        return None


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


def preview_first(text: str, max_len: int) -> str:
    """Preview the first part of a string for logging."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


__all__ = [
    "WorkspaceMapping",
    "decode",
    "decode_websocket_text",
    "encode",
    "encode_websocket_text",
    "preview_first",
]


@dataclass
class WorkspaceMapping:
    """Bidirectional path mapping for container deployments.

    When the server runs in a container, client paths differ from container paths.
    This mapping enables transparent translation: the SDK converts container paths
    back to client paths for display, and client paths to container paths for
    outgoing messages.
    """

    host_root: str | None
    container_root: str | None

    @property
    def is_configured(self) -> bool:
        """True when both host_root and container_root are non-empty."""
        return bool(self.host_root) and bool(self.container_root)

    def translate_to_client(self, path: str) -> str:
        """Translate a container path to a client path for display.

        Paths outside container_root are returned unchanged.
        Only matches at path boundaries (avoids partial prefix matches).
        """
        if not self.is_configured:
            return path
        if path == self.container_root:
            return self.host_root
        if path.startswith(self.container_root + "/"):
            return self.host_root + path[len(self.container_root) :]
        return path

    def translate_to_container(self, path: str) -> str:
        """Translate a client path to a container path (outgoing messages).

        Paths outside host_root are returned unchanged.
        Only matches at path boundaries (avoids partial prefix matches).
        """
        if not self.is_configured:
            return path
        if path == self.host_root:
            return self.container_root
        if path.startswith(self.host_root + "/"):
            return self.container_root + path[len(self.host_root) :]
        return path
