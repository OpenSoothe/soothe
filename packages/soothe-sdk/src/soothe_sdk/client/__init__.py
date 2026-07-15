"""Shared client-facing contracts: wire codec, config paths, and protocol helpers.

Transport WebSocket client APIs live in ``soothe_client`` (package
``soothe-client-python``). This package keeps the encode/decode surface and
path constants so daemon and core can depend on soothe-sdk without depending
on the client library.
"""

from soothe_sdk.client.config import (
    DEFAULT_EXECUTE_TIMEOUT,
    SOOTHE_DATA_DIR,
    SOOTHE_HOME,
    CliConfigProtocol,
    DaemonConfigProtocol,
    DaemonTransportConfigProtocol,
    WebSocketConfigProtocol,
    migrate_data_to_subdir,
)
from soothe_sdk.client.protocol import (
    decode_websocket_text,
    encode_websocket_text,
)
from soothe_sdk.client.wire import (
    DEFAULT_PROTO,
    BatchRequest,
    BatchRequestEnvelope,
    BatchResponseEnvelope,
    ConnectionAckEnvelope,
    ConnectionAckResult,
    ConnectionInitEnvelope,
    ConnectionInitParams,
    ErrorEnvelope,
    MessageType,
    PingEnvelope,
    PongEnvelope,
    ProtocolError,
    ResponseEnvelope,
    WireEnvelope,
    decode_envelope,
    encode_envelope,
    envelope_langchain_message_dict,
    messages_from_wire_dicts,
)

__all__ = [
    # Config / paths
    "SOOTHE_HOME",
    "SOOTHE_DATA_DIR",
    "DEFAULT_EXECUTE_TIMEOUT",
    "migrate_data_to_subdir",
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
    # Protocol codec helpers
    "encode_websocket_text",
    "decode_websocket_text",
    # Wire envelopes
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
    "ProtocolError",
    "BatchRequest",
    "BatchRequestEnvelope",
    "BatchResponseEnvelope",
    "encode_envelope",
    "decode_envelope",
    "envelope_langchain_message_dict",
    "messages_from_wire_dicts",
]
