"""Normalize LangChain message dicts for JSON wire transport.

Canonical serialization uses :func:`langchain_core.messages.message_to_dict` (enveloped)
then flattens to ``{type, content, tool_calls, …}`` with short wire type tags (``ai``,
``human``, …) for full messages and explicit ``*Chunk`` tags for streaming chunks.
Deserialization uses :func:`messages_from_wire_dicts`.

IMPORTANT: ``AIMessageChunk`` / ``HumanMessageChunk`` MUST keep their distinct wire
tags. Collapsing them to ``ai`` / ``human`` (the legacy mapping) causes the TUI
to receive synthesis stream chunks as plain ``AIMessage`` instances, breaking the
streaming branch (``isinstance(message, AIMessageChunk)`` returns ``False``) and
silently dropping all chunks after the first.
"""

from __future__ import annotations

import json
from typing import Any

# ``messages_from_dict`` / ``_message_from_dict`` only accept short wire tags (``ai``,
# ``human``, ``tool``, …) or explicit ``*Chunk`` tags — not Pydantic class names like
# ``AIMessage``. Some serializers emit class names; normalize before enveloping.
#
# Chunk types (``AIMessageChunk`` / ``HumanMessageChunk``) intentionally pass through
# unchanged: ``messages_from_dict`` understands these tags natively, and preserving
# them on the wire keeps the chunk identity intact so streaming consumers (TUI
# synthesis branch, etc.) can use ``isinstance(msg, AIMessageChunk)``.
_LC_MESSAGE_CLASS_TO_WIRE: dict[str, str] = {
    "AIMessage": "ai",
    "HumanMessage": "human",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": "chat",
    "RemoveMessage": "remove",
}


def envelope_langchain_message_dict(message: dict[str, Any]) -> dict[str, Any]:
    """Wrap flat ``model_dump``-style message dicts for ``messages_from_dict``.

    Args:
        message: Decoded JSON object for a single stream or state message.

    Returns:
        Either the original dict (already enveloped or not a message body) or the
        wrapped form suitable for ``messages_from_dict``.
    """
    if "data" in message:
        return message
    body = dict(message)
    raw_type = body.get("type")
    if isinstance(raw_type, str) and raw_type in _LC_MESSAGE_CLASS_TO_WIRE:
        body["type"] = _LC_MESSAGE_CLASS_TO_WIRE[raw_type]
    msg_type = body.get("type")
    if not isinstance(msg_type, str):
        return message
    if not any(k in body for k in ("content", "tool_calls", "tool_call_id", "tool_call_chunks")):
        return message
    return {"type": msg_type, "data": body}


def _stringify_tool_call_chunk_args_in_body(body: dict[str, Any]) -> bool:
    """Coerce ``tool_call_chunks[].args`` dicts to JSON strings for LangChain deserialize.

    ``AIMessageChunk`` validates chunk ``args`` as ``str`` (streaming JSON fragments).
    Executor backfill/enrich may attach complete dict kwargs; without this step
    ``messages_from_dict`` fails and the TUI never merges task descriptions.
    """
    chunks = body.get("tool_call_chunks")
    if not isinstance(chunks, list):
        return False
    changed = False
    new_chunks: list[Any] = []
    for tc in chunks:
        if not isinstance(tc, dict):
            new_chunks.append(tc)
            continue
        block = dict(tc)
        args = block.get("args")
        if isinstance(args, dict):
            block["args"] = json.dumps(args, separators=(",", ":"))
            changed = True
        new_chunks.append(block)
    if changed:
        body["tool_call_chunks"] = new_chunks
    return changed


def coerce_tool_call_chunk_args_for_wire(message: dict[str, Any]) -> dict[str, Any]:
    """Return a wire message dict safe for :func:`messages_from_dict`."""
    if "data" in message and isinstance(message.get("data"), dict):
        body = dict(message["data"])
        if _stringify_tool_call_chunk_args_in_body(body):
            out = dict(message)
            out["data"] = body
            return out
        return message
    if isinstance(message, dict):
        body = dict(message)
        if _stringify_tool_call_chunk_args_in_body(body):
            return body
    return message


def _backfill_tool_calls_on_wire_body(body: dict[str, Any]) -> dict[str, Any]:
    """Copy complete chunk kwargs onto empty ``tool_calls[].args`` in a wire dict."""
    chunks = body.get("tool_call_chunks")
    calls = body.get("tool_calls")
    if not isinstance(chunks, list) or not isinstance(calls, list):
        return body
    args_by_id: dict[str, dict[str, Any]] = {}
    args_by_index: dict[int, dict[str, Any]] = {}
    for tc in chunks:
        if not isinstance(tc, dict):
            continue
        raw = tc.get("args")
        parsed: dict[str, Any] = {}
        if isinstance(raw, dict) and raw:
            parsed = dict(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = {}
        if not parsed:
            continue
        tid = str(tc.get("id") or "").strip()
        if tid:
            args_by_id[tid] = parsed
        idx_raw = tc.get("index")
        if idx_raw is not None:
            try:
                args_by_index[int(idx_raw)] = parsed
            except (TypeError, ValueError):
                pass
    if not args_by_id and not args_by_index:
        return body
    new_calls: list[Any] = []
    changed = False
    for call_idx, tc in enumerate(calls):
        if not isinstance(tc, dict):
            new_calls.append(tc)
            continue
        tid = str(tc.get("id") or "").strip()
        existing = tc.get("args")
        empty = existing is None or existing == {} or existing == ""
        fill: dict[str, Any] | None = None
        if empty and tid and tid in args_by_id:
            fill = args_by_id[tid]
        elif empty and call_idx in args_by_index:
            fill = args_by_index[call_idx]
        if fill is not None:
            patched = dict(tc)
            patched["args"] = fill
            new_calls.append(patched)
            changed = True
        else:
            new_calls.append(tc)
    if not changed:
        return body
    out = dict(body)
    out["tool_calls"] = new_calls
    return out


def _wire_type_tag(raw_type: Any) -> Any:
    if isinstance(raw_type, str):
        return _LC_MESSAGE_CLASS_TO_WIRE.get(raw_type, raw_type)
    return raw_type


def flatten_enveloped_message_dict(message: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``{type, data: body}`` to ``{type, …body fields}`` for JSON wire."""
    if "data" in message and isinstance(message.get("data"), dict):
        body = dict(message["data"])
        body.pop("type", None)
        wire_type = _wire_type_tag(message.get("type"))
        body = coerce_tool_call_chunk_args_for_wire(body)
        body = _backfill_tool_calls_on_wire_body(body)
        if isinstance(wire_type, str):
            return {"type": wire_type, **body}
        return body
    if isinstance(message, dict):
        body = dict(message)
        if "type" in body:
            body["type"] = _wire_type_tag(body["type"])
        body = coerce_tool_call_chunk_args_for_wire(body)
        return _backfill_tool_calls_on_wire_body(body)
    return message


def serialize_langchain_message_for_wire(message: Any) -> dict[str, Any]:
    """Canonical JSON-ready dict for one LangChain message (protocol-1 wire)."""
    if isinstance(message, dict):
        return flatten_enveloped_message_dict(message)
    try:
        from langchain_core.messages import BaseMessage, message_to_dict
    except ImportError:
        from soothe_sdk.wire.protocol import _serialize_for_json

        flat = _serialize_for_json(message)
        return flatten_enveloped_message_dict(flat) if isinstance(flat, dict) else {}
    if isinstance(message, BaseMessage):
        return flatten_enveloped_message_dict(message_to_dict(message))
    from soothe_sdk.wire.protocol import _serialize_for_json

    flat = _serialize_for_json(message)
    return flatten_enveloped_message_dict(flat) if isinstance(flat, dict) else {}


def deserialize_langchain_message_from_wire(message: Any) -> Any:
    """Restore a LangChain message from a wire dict (flat or enveloped)."""
    if not isinstance(message, dict):
        return message
    restored = messages_from_wire_dicts([message])
    if restored:
        return restored[0]
    return message


def prepare_stream_message_for_wire(message: Any) -> Any:
    """Serialize a LangChain stream message for WebSocket/JSON clients."""
    return serialize_langchain_message_for_wire(message)


def prepare_stream_data_for_wire(data: Any) -> Any:
    """Serialize a LangGraph ``messages`` stream pair ``(message, metadata)``."""
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return data
    msg, meta = data[0], data[1]
    from soothe_sdk.wire.protocol import _serialize_for_json

    out_meta = _serialize_for_json(meta) if meta is not None else {}
    return (prepare_stream_message_for_wire(msg), out_meta)


def messages_from_wire_dicts(messages: list[Any]) -> list[Any]:
    """Deserialize LangChain messages from wire/JSON list payloads.

    Args:
        messages: List of dicts (flat or enveloped) as received over the wire.

    Returns:
        List of :class:`~langchain_core.messages.BaseMessage` instances.
    """
    from langchain_core.messages import messages_from_dict

    prepared: list[Any] = []
    for m in messages:
        if isinstance(m, dict):
            m = coerce_tool_call_chunk_args_for_wire(m)
            m = envelope_langchain_message_dict(m)
        prepared.append(m)
    return messages_from_dict(prepared)


# ---------------------------------------------------------------------------
# Protocol-1 wire envelope models
# ---------------------------------------------------------------------------
# The unified `{proto, type, method, params, id}` envelope combines JSON-RPC
# 2.0's `method`/`params`/`id` structure with graphql-ws's `type` semantics
# for message class distinction.

from enum import StrEnum  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

DEFAULT_PROTO = "1"
"""Protocol version string for protocol-1 messages."""


class MessageType(StrEnum):
    """Message class values for the envelope ``type`` field.

    Each value is the literal wire string sent on the transport.
    """

    CONNECTION_INIT = "connection_init"
    CONNECTION_ACK = "connection_ack"
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    SUBSCRIBE = "subscribe"
    NEXT = "next"
    ERROR = "error"
    COMPLETE = "complete"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"
    PONG = "pong"
    RECEIPT_RESPONSE = "receipt_response"
    DISCONNECT = "disconnect"


class WireEnvelope(BaseModel):
    """Base protocol-1 wire envelope.

    All messages share the unified ``{proto, type, method, params, id}``
    structure. Subclasses constrain ``type`` to a specific message class and
    add class-specific fields.

    Attributes:
        proto: Protocol version string (default ``"1"``). Mandatory on every
            message; messages without it are rejected at validation.
        type: Message class (one of the values in :class:`MessageType`).
        method: RPC method or subscription target name. Conditional — present
            on request/notification/subscribe messages.
        params: Structured parameters object. All operation-specific fields
            MUST reside here.
        id: Operation correlation ID. Present = response expected; absent =
            fire-and-forget.
    """

    proto: str = Field(default=DEFAULT_PROTO, description="Protocol version string.")
    type: str = Field(description="Message class (see MessageType).")
    method: str | None = Field(default=None, description="RPC method or subscription target.")
    params: dict[str, Any] | None = Field(default=None, description="Structured parameters object.")
    id: str | None = Field(
        default=None, description="Operation correlation ID (absent = fire-and-forget)."
    )

    model_config = {"extra": "allow"}

    def to_wire_dict(self) -> dict[str, Any]:
        """Serialize this envelope to a protocol-1 compliant wire dict.

        Omits fields that are ``None`` so the wire form is compact and matches
        the protocol-1 wire examples. Subclasses may override to remap fields.
        """
        return _dump_envelope(self)

    def to_wire_json(self) -> str:
        """Serialize this envelope to protocol-1 compliant JSON text."""
        return json.dumps(self.to_wire_dict(), separators=(",", ":"))


def _dump_envelope(model: BaseModel) -> dict[str, Any]:
    """Build a compact wire dict from an envelope model, dropping ``None`` values."""
    out: dict[str, Any] = {}
    for k, v in model.model_dump().items():
        if v is None:
            continue
        if isinstance(v, dict) and not v:
            continue
        out[k] = v
    return out


class ResponseEnvelope(WireEnvelope):
    """Response envelope for successful RPC results.

    The server sends this in reply to a ``request`` that carried an ``id``.

    Attributes:
        result: The result data object.
        id: Correlation ID echoed from the originating request.
    """

    type: str = Field(default=MessageType.RESPONSE.value)
    result: dict[str, Any] | None = Field(
        default=None, description="The result data object for a successful response."
    )

    def to_wire_dict(self) -> dict[str, Any]:
        out = _dump_envelope(self)
        # ``result`` is a top-level field on responses.
        return out


class ErrorEnvelope(WireEnvelope):
    """Error envelope for failed operations.

    On the wire the structured error is nested under an ``error`` key:
    ``{"error": {"code", "message", "data"}}``. The model exposes ``code``,
    ``message``, and ``data`` as flat fields per the structured error object
    (protocol-1 wire form); :meth:`to_wire_dict` nests them under ``error`` for
    transport, and :meth:`from_wire_dict` accepts both nested and flat forms.

    Attributes:
        code: Integer error code (see the protocol-1 error code registry).
        message: Human-readable summary string.
        data: Optional machine-parseable details (field errors, context).
        id: Correlation ID echoed from the originating request, if any.
    """

    type: str = Field(default=MessageType.ERROR.value)
    code: int = Field(description="Numeric error code (protocol-1 error code registry).")
    message: str = Field(description="Human-readable error summary.")
    data: dict[str, Any] | None = Field(
        default=None, description="Optional machine-parseable error details."
    )

    # Hide the inherited ``params``/``method``/``result`` from the error form.
    method: str | None = Field(default=None, exclude=True)
    params: dict[str, Any] | None = Field(default=None, exclude=True)

    def to_wire_dict(self) -> dict[str, Any]:
        """Build the protocol-1 wire dict with the nested ``error`` object."""
        out: dict[str, Any] = {
            "proto": self.proto,
            "type": self.type,
        }
        error_obj: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            error_obj["data"] = self.data
        out["error"] = error_obj
        if self.id is not None:
            out["id"] = self.id
        return out

    @classmethod
    def from_wire_dict(cls, data: dict[str, Any]) -> ErrorEnvelope:
        """Construct an ErrorEnvelope from a protocol-1 wire dict.

        Expects the nested form ``{"error": {"code", "message", "data?"},
        "id"?}``. The flat top-level form is no longer accepted.
        """
        nested = data.get("error")
        if not isinstance(nested, dict):
            raise ValueError("error envelope missing nested 'error' object")
        flat: dict[str, Any] = {
            "code": nested["code"],
            "message": nested["message"],
        }
        if "data" in nested:
            flat["data"] = nested["data"]
        if "id" in data:
            flat["id"] = data["id"]
        return cls.model_validate(flat)


class ConnectionInitParams(BaseModel):
    """Parameters for the ``connection_init`` handshake message.

    Sent by the client as the first message after the WebSocket upgrade.

    Attributes:
        client_version: Client software version string.
        client_name: Optional client identifier (e.g. ``"soothe-cli"``).
        accept_proto: Protocol versions the client supports (e.g. ``["1"]``).
        capabilities: Client-declared capabilities (e.g. ``["streaming",
            "batch", "receipts"]``).
    """

    client_version: str = Field(description="Client software version.")
    client_name: str | None = Field(default=None, description="Optional client identifier.")
    accept_proto: list[str] = Field(
        default_factory=lambda: [DEFAULT_PROTO],
        description="Protocol versions the client supports.",
    )
    capabilities: list[str] = Field(
        default_factory=list, description="Client-declared capabilities."
    )

    model_config = {"extra": "allow"}


class ConnectionAckResult(BaseModel):
    """Result payload for the ``connection_ack`` handshake message.

    Sent by the server in reply to ``connection_init``.

    Attributes:
        server_version: Server software version string.
        protocol_version: Negotiated protocol version (highest both support).
        capabilities: Server-declared capabilities (intersected with client's).
        readiness_state: Server readiness state (``"ready"`` / ``"starting"`` /
            ``"warming"`` / ``"incompatible"``).
        heartbeat_interval_ms: Heartbeat interval in milliseconds (default 30000).
    """

    server_version: str = Field(description="Server software version.")
    protocol_version: str = Field(default=DEFAULT_PROTO, description="Negotiated protocol version.")
    capabilities: list[str] = Field(
        default_factory=list, description="Server-declared capabilities."
    )
    readiness_state: str = Field(default="ready", description="Server readiness state.")
    heartbeat_interval_ms: int = Field(
        default=30000, description="Heartbeat interval in milliseconds."
    )

    model_config = {"extra": "allow"}


class ConnectionInitEnvelope(WireEnvelope):
    """``connection_init`` handshake message.

    The first message the client sends after the WebSocket upgrade.

    Attributes:
        params: Connection initialization parameters.
    """

    type: str = Field(default=MessageType.CONNECTION_INIT.value)
    params: ConnectionInitParams | None = Field(  # type: ignore[assignment]
        default=None, description="Connection initialization parameters."
    )

    def to_wire_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"proto": self.proto, "type": self.type}
        if self.params is not None:
            out["params"] = self.params.model_dump(exclude_none=True)
        return out


class ConnectionAckEnvelope(WireEnvelope):
    """``connection_ack`` handshake message.

    Sent by the server in reply to ``connection_init``.

    Attributes:
        result: Connection acknowledgment result payload.
    """

    type: str = Field(default=MessageType.CONNECTION_ACK.value)
    result: ConnectionAckResult | None = Field(  # type: ignore[assignment]
        default=None, description="Connection acknowledgment result."
    )

    def to_wire_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"proto": self.proto, "type": self.type}
        if self.result is not None:
            out["result"] = self.result.model_dump(exclude_none=True)
        return out


class PingEnvelope(WireEnvelope):
    """``ping`` heartbeat message.

    Either party MAY send ``ping``; the receiver MUST respond with ``pong``
    within ``heartbeat_timeout_ms``.
    """

    type: str = Field(default=MessageType.PING.value)
    method: str | None = Field(default=None, exclude=True)
    params: dict[str, Any] | None = Field(default=None, exclude=True)


class PongEnvelope(WireEnvelope):
    """``pong`` heartbeat response."""

    type: str = Field(default=MessageType.PONG.value)
    method: str | None = Field(default=None, exclude=True)
    params: dict[str, Any] | None = Field(default=None, exclude=True)


class BatchRequest(BaseModel):
    """A single item in a batch request array.

    A batch is a JSON array of valid protocol-1 messages. Each item is either
    a request (carries ``id`` → expects a response) or a notification (no
    ``id`` → fire-and-forget).
    """

    proto: str = Field(default=DEFAULT_PROTO)
    type: str = Field(default=MessageType.REQUEST.value)
    method: str = Field(description="RPC method name.")
    params: dict[str, Any] | None = Field(default=None)
    id: str | None = Field(default=None, description="Correlation ID; absent = notification.")

    model_config = {"extra": "allow"}


class BatchRequestEnvelope(BaseModel):
    """Batch request envelope — a JSON array of protocol-1 messages.

    The wire form is a bare JSON array (not wrapped in an object). This model
    holds the list of batch items and provides encode/decode helpers.
    """

    items: list[BatchRequest] = Field(default_factory=list, description="Batch message items.")

    def to_wire_dict(self) -> list[dict[str, Any]]:
        """Serialize to a JSON array of wire dicts (batch wire form)."""
        return [_dump_envelope(item) for item in self.items]

    def to_wire_json(self) -> str:
        """Serialize to a JSON array text frame."""
        return json.dumps(self.to_wire_dict(), separators=(",", ":"))

    @classmethod
    def from_wire_dict(cls, data: list[Any]) -> BatchRequestEnvelope:
        """Construct from a parsed JSON array (the batch wire form)."""
        if not isinstance(data, list):
            raise TypeError("BatchRequestEnvelope expects a JSON array")
        items = [
            BatchRequest.model_validate(item) if isinstance(item, dict) else item for item in data
        ]
        return cls(items=items)


class BatchResponseEnvelope(BaseModel):
    """Batch response envelope — a JSON array of response/error messages.

    The server returns an array of responses, one per batch item that carried
    an ``id`` (notifications produce no response entry).
    """

    items: list[ResponseEnvelope | ErrorEnvelope] = Field(
        default_factory=list, description="Batch response items."
    )

    def to_wire_dict(self) -> list[dict[str, Any]]:
        """Serialize to a JSON array of wire dicts (batch wire form)."""
        return [item.to_wire_dict() for item in self.items]

    def to_wire_json(self) -> str:
        """Serialize to a JSON array text frame."""
        return json.dumps(self.to_wire_dict(), separators=(",", ":"))

    @classmethod
    def from_wire_dict(cls, data: list[Any]) -> BatchResponseEnvelope:
        """Construct from a parsed JSON array of response/error messages."""
        if not isinstance(data, list):
            raise TypeError("BatchResponseEnvelope expects a JSON array")
        items: list[ResponseEnvelope | ErrorEnvelope] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            msg_type = item.get("type")
            if msg_type == MessageType.ERROR.value:
                items.append(ErrorEnvelope.from_wire_dict(item))
            else:
                items.append(ResponseEnvelope.model_validate(item))
        return cls(items=items)


# ---------------------------------------------------------------------------
# Envelope encode / decode helpers
# ---------------------------------------------------------------------------


def encode_envelope(envelope: BaseModel) -> str:
    """Serialize an envelope model to JSON text for a WebSocket text frame.

    Uses the model's :meth:`to_wire_dict` when available so subclasses can
    produce protocol-1 compliant nested forms (e.g. :class:`ErrorEnvelope`).
    Otherwise falls back to a compact ``model_dump``.

    Args:
        envelope: A Pydantic envelope model instance.

    Returns:
        Compact JSON text suitable for ``Connection.send`` as a text frame.
    """
    if hasattr(envelope, "to_wire_dict"):
        payload: Any = envelope.to_wire_dict()  # type: ignore[attr-defined]
    else:
        dumped = envelope.model_dump(exclude_none=True)
        payload = dumped
    return json.dumps(payload, separators=(",", ":"))


def decode_envelope(text: str) -> dict[str, Any] | list[Any] | None:
    """Parse JSON text from a WebSocket frame into a raw dict or list.

    Validation against a specific envelope model happens separately (the
    caller selects the model by message ``type``). Returns ``None`` for empty
    or invalid JSON. A JSON array is returned as-is (batch form).

    Args:
        text: Raw frame payload.

    Returns:
        Parsed message dict, parsed list (batch), or ``None``.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


class ProtocolError(Exception):
    """Client-side protocol error from an error response.

    Raised by `WebSocketClient.request()` when the server replies with an
    ``error`` envelope matching the request ``id``. Carries the numeric
    ``code``, human-readable ``message``, and optional ``data`` from the
    structured error object.

    Attributes:
        code: Numeric error code from the protocol-1 error code registry.
        message: Human-readable error summary.
        data: Optional machine-parseable details (empty dict when unset).
    """

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a client-side protocol error.

        Args:
            code: Numeric error code from the error envelope.
            message: Human-readable error summary.
            data: Optional machine-parseable details.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def __str__(self) -> str:
        if self.data:
            return f"[{self.code}] {self.message} ({self.data})"
        return f"[{self.code}] {self.message}"


__all__ = [
    "coerce_tool_call_chunk_args_for_wire",
    "deserialize_langchain_message_from_wire",
    "envelope_langchain_message_dict",
    "flatten_enveloped_message_dict",
    "messages_from_wire_dicts",
    "prepare_stream_data_for_wire",
    "prepare_stream_message_for_wire",
    "serialize_langchain_message_for_wire",
    # Protocol-1 wire envelope models
    "DEFAULT_PROTO",
    "MessageType",
    "WireEnvelope",
    "ResponseEnvelope",
    "ErrorEnvelope",
    "ConnectionInitParams",
    "ConnectionAckResult",
    "ConnectionInitEnvelope",
    "ConnectionAckEnvelope",
    "PingEnvelope",
    "PongEnvelope",
    "BatchRequest",
    "BatchRequestEnvelope",
    "BatchResponseEnvelope",
    "ProtocolError",
    "encode_envelope",
    "decode_envelope",
]
