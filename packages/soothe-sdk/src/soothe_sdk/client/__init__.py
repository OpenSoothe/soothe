"""Compatibility package for relocated wire/paths modules.

Prefer canonical imports:

- ``soothe_sdk.wire`` / ``soothe_sdk.wire.codec`` / ``soothe_sdk.wire.protocol``
- ``soothe_sdk.paths``

Submodules ``soothe_sdk.client.config``, ``.wire``, and ``.protocol`` remain as
thin re-export shims during the slim-SDK migration.
"""

from soothe_sdk.paths import (
    DEFAULT_EXECUTE_TIMEOUT,
    SOOTHE_DATA_DIR,
    SOOTHE_HOME,
    CliConfigProtocol,
    DaemonConfigProtocol,
    DaemonTransportConfigProtocol,
    WebSocketConfigProtocol,
    migrate_data_to_subdir,
)
from soothe_sdk.wire.codec import (
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
from soothe_sdk.wire.protocol import (
    decode_websocket_text,
    encode_websocket_text,
)

__all__ = [
    "SOOTHE_HOME",
    "SOOTHE_DATA_DIR",
    "DEFAULT_EXECUTE_TIMEOUT",
    "migrate_data_to_subdir",
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
    "encode_websocket_text",
    "decode_websocket_text",
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
