"""Unit tests for protocol-1 wire envelope Pydantic models (RFC-450 §5, IG-522 Phase 1).

Covers serialization (``to_wire_dict`` / ``to_wire_json`` / ``encode_envelope``),
deserialization (``model_validate`` / ``from_wire_dict`` / ``decode_envelope``),
required-field validation, and batch encoding/decoding.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

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
    ResponseEnvelope,
    WireEnvelope,
    decode_envelope,
    encode_envelope,
)

# ---------------------------------------------------------------------------
# WireEnvelope base model
# ---------------------------------------------------------------------------


class TestWireEnvelopeBase:
    """WireEnvelope base model: fields, defaults, required validation."""

    def test_default_proto_is_one(self) -> None:
        """``proto`` defaults to ``"1"`` per RFC-450 §8.1."""
        env = WireEnvelope(type="request", method="loop_get")
        assert env.proto == "1"

    def test_all_fields_populated(self) -> None:
        """A fully populated envelope round-trips through model fields."""
        env = WireEnvelope(
            proto="1",
            type="request",
            method="loop_get",
            params={"loop_id": "abc", "verbose": True},
            id="req_001",
        )
        assert env.proto == "1"
        assert env.type == "request"
        assert env.method == "loop_get"
        assert env.params == {"loop_id": "abc", "verbose": True}
        assert env.id == "req_001"

    def test_type_is_required(self) -> None:
        """``type`` is mandatory; omitting it raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            WireEnvelope()  # type: ignore[call-arg]
        assert "type" in str(exc_info.value)

    def test_to_wire_dict_drops_none_fields(self) -> None:
        """``to_wire_dict`` omits ``None`` fields for a compact wire form."""
        env = WireEnvelope(type="ping")
        wire = env.to_wire_dict()
        assert wire == {"proto": "1", "type": "ping"}
        assert "method" not in wire
        assert "params" not in wire
        assert "id" not in wire

    def test_to_wire_json_compact(self) -> None:
        """``to_wire_json`` produces compact JSON text."""
        env = WireEnvelope(type="request", method="loop_get", id="r1")
        text = env.to_wire_json()
        assert '"proto":"1"' in text
        assert '"type":"request"' in text
        # No extra whitespace (compact separators)
        assert ", " not in text

    def test_proto_can_be_overridden(self) -> None:
        """``proto`` can be set to a future version string."""
        env = WireEnvelope(proto="2", type="request")
        assert env.proto == "2"


# ---------------------------------------------------------------------------
# ResponseEnvelope
# ---------------------------------------------------------------------------


class TestResponseEnvelope:
    """ResponseEnvelope: type default, result field, wire serialization."""

    def test_type_defaults_to_response(self) -> None:
        env = ResponseEnvelope(result={"status": "ok"}, id="r1")
        assert env.type == "response"

    def test_to_wire_dict_matches_rfc_example(self) -> None:
        """Wire form matches RFC-450 §5.5 response example."""
        env = ResponseEnvelope(result={"loop_id": "abc", "status": "running"}, id="r1")
        wire = env.to_wire_dict()
        assert wire == {
            "proto": "1",
            "type": "response",
            "result": {"loop_id": "abc", "status": "running"},
            "id": "r1",
        }

    def test_deserialize_from_dict(self) -> None:
        """A wire dict deserializes into a ResponseEnvelope."""
        env = ResponseEnvelope.model_validate(
            {"proto": "1", "type": "response", "result": {"x": 1}, "id": "r2"}
        )
        assert env.type == "response"
        assert env.result == {"x": 1}
        assert env.id == "r2"

    def test_response_without_id_is_valid(self) -> None:
        """A response without ``id`` is structurally valid (edge case)."""
        env = ResponseEnvelope(result={"done": True})
        wire = env.to_wire_dict()
        assert "id" not in wire


# ---------------------------------------------------------------------------
# ErrorEnvelope
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    """ErrorEnvelope: required code/message, nested wire form, dual-form parse."""

    def test_type_defaults_to_error(self) -> None:
        env = ErrorEnvelope(code=-32200, message="Loop not found", id="r1")
        assert env.type == "error"

    def test_code_and_message_are_required(self) -> None:
        """Both ``code`` and ``message`` are mandatory."""
        with pytest.raises(ValidationError) as exc:
            ErrorEnvelope(id="r1")  # type: ignore[call-arg]
        assert "code" in str(exc.value)
        assert "message" in str(exc.value)

    def test_code_must_be_int(self) -> None:
        """``code`` must be an integer."""
        with pytest.raises(ValidationError):
            ErrorEnvelope(code="not-an-int", message="oops")  # type: ignore[arg-type]

    def test_data_is_optional(self) -> None:
        env = ErrorEnvelope(code=-32600, message="bad request")
        assert env.data is None

    def test_to_wire_dict_nests_error_object(self) -> None:
        """Wire form nests code/message/data under ``error`` (RFC-450 §7.1)."""
        env = ErrorEnvelope(
            code=-32200,
            message="Loop not found",
            data={"loop_id": "abc123"},
            id="req_001",
        )
        wire = env.to_wire_dict()
        assert wire == {
            "proto": "1",
            "type": "error",
            "error": {
                "code": -32200,
                "message": "Loop not found",
                "data": {"loop_id": "abc123"},
            },
            "id": "req_001",
        }

    def test_to_wire_dict_omits_empty_data(self) -> None:
        """Empty/None ``data`` is omitted from the nested error object."""
        env = ErrorEnvelope(code=-32600, message="bad", id="r1")
        wire = env.to_wire_dict()
        assert "data" not in wire["error"]

    def test_from_wire_dict_nested_form(self) -> None:
        """Parse the RFC-450 nested ``error`` object form."""
        wire = {
            "proto": "1",
            "type": "error",
            "error": {"code": -32200, "message": "Loop not found", "data": {"x": 1}},
            "id": "req_001",
        }
        env = ErrorEnvelope.from_wire_dict(wire)
        assert env.code == -32200
        assert env.message == "Loop not found"
        assert env.data == {"x": 1}
        assert env.id == "req_001"

    def test_from_wire_dict_rejects_flat_form(self) -> None:
        """Flat error dicts (no nested ``error`` object) are rejected (clear cut)."""
        with pytest.raises(ValueError):
            ErrorEnvelope.from_wire_dict(
                {"proto": "1", "type": "error", "code": -32601, "message": "no method", "id": "r9"}
            )

    def test_error_without_id_is_valid(self) -> None:
        """An error without ``id`` (notification failure) is valid."""
        env = ErrorEnvelope(code=-32600, message="bad notification")
        wire = env.to_wire_dict()
        assert "id" not in wire


# ---------------------------------------------------------------------------
# ConnectionInit / ConnectionAck handshake
# ---------------------------------------------------------------------------


class TestConnectionHandshake:
    """ConnectionInit / ConnectionAck models per RFC-450 §8.2."""

    def test_connection_init_params_defaults(self) -> None:
        params = ConnectionInitParams(client_version="0.5.0")
        assert params.client_version == "0.5.0"
        assert params.client_name is None
        assert params.accept_proto == ["1"]
        assert params.capabilities == []

    def test_connection_init_envelope_to_wire(self) -> None:
        """Wire form matches RFC-450 §8.2 connection_init example."""
        env = ConnectionInitEnvelope(
            params=ConnectionInitParams(
                client_version="0.5.0",
                client_name="soothe-cli",
                accept_proto=["1"],
                capabilities=["streaming", "batch", "receipts"],
            )
        )
        wire = env.to_wire_dict()
        assert wire == {
            "proto": "1",
            "type": "connection_init",
            "params": {
                "client_version": "0.5.0",
                "client_name": "soothe-cli",
                "accept_proto": ["1"],
                "capabilities": ["streaming", "batch", "receipts"],
            },
        }

    def test_connection_init_type_defaults(self) -> None:
        env = ConnectionInitEnvelope(params=ConnectionInitParams(client_version="0.5.0"))
        assert env.type == "connection_init"

    def test_connection_ack_result_defaults(self) -> None:
        result = ConnectionAckResult(server_version="0.5.0")
        assert result.protocol_version == "1"
        assert result.readiness_state == "ready"
        assert result.heartbeat_interval_ms == 30000

    def test_connection_ack_envelope_to_wire(self) -> None:
        """Wire form matches RFC-450 §8.2 connection_ack example."""
        env = ConnectionAckEnvelope(
            result=ConnectionAckResult(
                server_version="0.5.0",
                protocol_version="1",
                capabilities=["streaming", "batch", "receipts", "heartbeat"],
                readiness_state="ready",
                heartbeat_interval_ms=30000,
            )
        )
        wire = env.to_wire_dict()
        assert wire == {
            "proto": "1",
            "type": "connection_ack",
            "result": {
                "server_version": "0.5.0",
                "protocol_version": "1",
                "capabilities": ["streaming", "batch", "receipts", "heartbeat"],
                "readiness_state": "ready",
                "heartbeat_interval_ms": 30000,
            },
        }


# ---------------------------------------------------------------------------
# Heartbeat (ping / pong)
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Ping / Pong heartbeat models per RFC-450 §8.3."""

    def test_ping_to_wire(self) -> None:
        env = PingEnvelope()
        wire = env.to_wire_dict()
        assert wire == {"proto": "1", "type": "ping"}
        assert env.type == "ping"

    def test_pong_to_wire(self) -> None:
        env = PongEnvelope()
        wire = env.to_wire_dict()
        assert wire == {"proto": "1", "type": "pong"}
        assert env.type == "pong"

    def test_ping_round_trip(self) -> None:
        env = PingEnvelope()
        text = encode_envelope(env)
        parsed = decode_envelope(text)
        assert parsed == {"proto": "1", "type": "ping"}

    def test_message_type_enum_values(self) -> None:
        """MessageType enum values match RFC-450 §9.1 type strings."""
        assert MessageType.PING.value == "ping"
        assert MessageType.PONG.value == "pong"
        assert MessageType.CONNECTION_INIT.value == "connection_init"
        assert MessageType.CONNECTION_ACK.value == "connection_ack"
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.ERROR.value == "error"
        assert MessageType.NOTIFICATION.value == "notification"
        assert MessageType.SUBSCRIBE.value == "subscribe"
        assert MessageType.NEXT.value == "next"
        assert MessageType.COMPLETE.value == "complete"
        assert MessageType.UNSUBSCRIBE.value == "unsubscribe"
        assert MessageType.RECEIPT_RESPONSE.value == "receipt_response"
        assert MessageType.DISCONNECT.value == "disconnect"


# ---------------------------------------------------------------------------
# Batch models
# ---------------------------------------------------------------------------


class TestBatch:
    """Batch request/response models per RFC-450 §5.6."""

    def test_batch_request_to_wire_is_array(self) -> None:
        """Batch wire form is a bare JSON array (RFC-450 §5.6)."""
        batch = BatchRequestEnvelope(
            items=[
                BatchRequest(
                    proto="1",
                    type="request",
                    method="loop_get",
                    params={"loop_id": "a"},
                    id="1",
                ),
                BatchRequest(
                    proto="1",
                    type="request",
                    method="loop_get",
                    params={"loop_id": "b"},
                    id="2",
                ),
                BatchRequest(
                    proto="1",
                    type="notification",
                    method="loop_detach",
                    params={"loop_id": "a"},
                ),
            ]
        )
        wire = batch.to_wire_dict()
        assert isinstance(wire, list)
        assert len(wire) == 3
        assert wire[0] == {
            "proto": "1",
            "type": "request",
            "method": "loop_get",
            "params": {"loop_id": "a"},
            "id": "1",
        }
        # Notification has no id
        assert "id" not in wire[2]

    def test_batch_request_to_wire_json(self) -> None:
        """Batch JSON text is a bare array."""
        batch = BatchRequestEnvelope(items=[BatchRequest(method="loop_get", id="1")])
        text = batch.to_wire_json()
        assert text.startswith("[")
        assert text.endswith("]")
        parsed = json.loads(text)
        assert isinstance(parsed, list)
        assert parsed[0]["method"] == "loop_get"

    def test_batch_request_from_wire_dict(self) -> None:
        """Decode a JSON array into a BatchRequestEnvelope."""
        wire = [
            {
                "proto": "1",
                "type": "request",
                "method": "loop_get",
                "params": {"loop_id": "a"},
                "id": "1",
            },
            {
                "proto": "1",
                "type": "notification",
                "method": "loop_detach",
                "params": {"loop_id": "a"},
            },
        ]
        batch = BatchRequestEnvelope.from_wire_dict(wire)
        assert len(batch.items) == 2
        assert batch.items[0].method == "loop_get"
        assert batch.items[0].id == "1"
        assert batch.items[1].type == "notification"
        assert batch.items[1].id is None

    def test_batch_request_default_proto(self) -> None:
        """BatchRequest items default proto to "1"."""
        item = BatchRequest(method="loop_get", id="1")
        assert item.proto == "1"

    def test_batch_response_to_wire_is_array(self) -> None:
        """Batch response wire form is a bare JSON array of response/error."""
        batch = BatchResponseEnvelope(
            items=[
                ResponseEnvelope(result={"loop_id": "a", "status": "running"}, id="1"),
                ErrorEnvelope(code=-32200, message="Loop b not found", id="2"),
            ]
        )
        wire = batch.to_wire_dict()
        assert isinstance(wire, list)
        assert len(wire) == 2
        assert wire[0]["type"] == "response"
        assert wire[0]["result"] == {"loop_id": "a", "status": "running"}
        assert wire[1]["type"] == "error"
        assert wire[1]["error"]["code"] == -32200

    def test_batch_response_from_wire_dict(self) -> None:
        """Decode a JSON array of response/error messages."""
        wire = [
            {"proto": "1", "type": "response", "result": {"ok": True}, "id": "1"},
            {
                "proto": "1",
                "type": "error",
                "error": {"code": -32200, "message": "not found"},
                "id": "2",
            },
        ]
        batch = BatchResponseEnvelope.from_wire_dict(wire)
        assert len(batch.items) == 2
        assert isinstance(batch.items[0], ResponseEnvelope)
        assert batch.items[0].result == {"ok": True}
        assert isinstance(batch.items[1], ErrorEnvelope)
        assert batch.items[1].code == -32200
        assert batch.items[1].message == "not found"

    def test_batch_round_trip(self) -> None:
        """Full batch encode → decode round trip preserves data."""
        original = BatchResponseEnvelope(
            items=[
                ResponseEnvelope(result={"v": 1}, id="1"),
                ErrorEnvelope(code=-32600, message="bad", data={"k": "v"}, id="2"),
            ]
        )
        text = encode_envelope(original)
        parsed = decode_envelope(text)
        assert isinstance(parsed, list)
        restored = BatchResponseEnvelope.from_wire_dict(parsed)
        assert len(restored.items) == 2
        assert restored.items[0].result == {"v": 1}
        assert restored.items[1].code == -32600
        assert restored.items[1].data == {"k": "v"}

    def test_batch_request_method_required(self) -> None:
        """BatchRequest requires a ``method``."""
        with pytest.raises(ValidationError):
            BatchRequest(type="request", id="1")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Encode / decode helpers
# ---------------------------------------------------------------------------


class TestEncodeDecodeHelpers:
    """encode_envelope / decode_envelope helpers (IG-522 Phase 1 task 4)."""

    def test_encode_envelope_uses_to_wire_dict(self) -> None:
        """encode_envelope delegates to to_wire_dict for RFC-compliant forms."""
        env = ErrorEnvelope(code=-32200, message="not found", id="r1")
        text = encode_envelope(env)
        parsed = json.loads(text)
        # Nested error form (RFC-450 §7.1), not flat
        assert parsed["error"]["code"] == -32200
        assert parsed["error"]["message"] == "not found"

    def test_encode_envelope_compact_json(self) -> None:
        env = WireEnvelope(type="request", method="loop_get", id="r1")
        text = encode_envelope(env)
        assert ", " not in text

    def test_decode_envelope_dict(self) -> None:
        text = '{"proto":"1","type":"ping"}'
        parsed = decode_envelope(text)
        assert parsed == {"proto": "1", "type": "ping"}

    def test_decode_envelope_list_batch(self) -> None:
        """decode_envelope returns a list for batch (JSON array) frames."""
        text = '[{"proto":"1","type":"request","method":"loop_get","id":"1"}]'
        parsed = decode_envelope(text)
        assert isinstance(parsed, list)
        assert parsed[0]["method"] == "loop_get"

    def test_decode_envelope_empty_returns_none(self) -> None:
        assert decode_envelope("") is None
        assert decode_envelope("   ") is None

    def test_decode_envelope_invalid_json_returns_none(self) -> None:
        assert decode_envelope("not json") is None
        assert decode_envelope("{broken") is None

    def test_round_trip_request(self) -> None:
        """A request envelope round-trips through encode/decode."""
        env = WireEnvelope(
            type="request",
            method="loop_get",
            params={"loop_id": "abc", "verbose": True},
            id="req_001",
        )
        text = encode_envelope(env)
        parsed = decode_envelope(text)
        assert parsed == {
            "proto": "1",
            "type": "request",
            "method": "loop_get",
            "params": {"loop_id": "abc", "verbose": True},
            "id": "req_001",
        }

    def test_round_trip_connection_init(self) -> None:
        """ConnectionInit round-trips through encode/decode."""
        env = ConnectionInitEnvelope(
            params=ConnectionInitParams(
                client_version="0.5.0",
                accept_proto=["1"],
                capabilities=["streaming"],
            )
        )
        text = encode_envelope(env)
        parsed = decode_envelope(text)
        assert parsed == {
            "proto": "1",
            "type": "connection_init",
            "params": {
                "client_version": "0.5.0",
                "accept_proto": ["1"],
                "capabilities": ["streaming"],
            },
        }


# ---------------------------------------------------------------------------
# Cross-cutting: DEFAULT_PROTO and MessageType consistency
# ---------------------------------------------------------------------------


class TestProtocolConstants:
    """Protocol-level constants are consistent."""

    def test_default_proto_value(self) -> None:
        assert DEFAULT_PROTO == "1"

    def test_message_type_is_str_enum(self) -> None:
        """MessageType is a str enum so values are usable as JSON strings."""
        assert isinstance(MessageType.PING, str)
        assert MessageType.PING == "ping"
