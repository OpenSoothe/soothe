"""Unit tests for protocol validation (RFC-0013).

Legacy global "input" message type was removed in favor of loop_input.
"""

from __future__ import annotations

from soothe_daemon.protocol import (
    ErrorCode,
    RpcProtocolError,
    build_error_response,
    validate_message,
    validate_message_size,
)


def test_validate_message_command_valid() -> None:
    """Test valid slash_command notification validation."""
    msg = {
        "proto": "1",
        "type": "notification",
        "method": "slash_command",
        "params": {"cmd": "/exit"},
    }
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_command_missing_cmd() -> None:
    """Test slash_command notification missing required cmd field."""
    msg = {"proto": "1", "type": "notification", "method": "slash_command", "params": {}}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "cmd" in errors[0]


def test_validate_message_detach_valid() -> None:
    """Test valid disconnect notification validation."""
    msg = {"proto": "1", "type": "notification", "method": "disconnect", "params": {}}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_missing_type() -> None:
    """Test message missing required type field."""
    msg = {"text": "Hello"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "type" in errors[0]


def test_validate_message_skills_list_valid() -> None:
    errors = validate_message(
        {"proto": "1", "type": "request", "method": "skills_list", "params": {}, "id": "r1"}
    )
    assert errors == []


def test_validate_message_models_list_valid() -> None:
    errors = validate_message(
        {"proto": "1", "type": "request", "method": "models_list", "params": {}, "id": "r1"}
    )
    assert errors == []


def test_validate_message_invoke_skill_valid() -> None:
    errors = validate_message(
        {
            "proto": "1",
            "type": "request",
            "method": "invoke_skill",
            "params": {"skill": "my-skill", "args": "x"},
            "id": "r1",
        }
    )
    assert errors == []


def test_validate_message_invoke_skill_missing_skill() -> None:
    errors = validate_message(
        {
            "proto": "1",
            "type": "request",
            "method": "invoke_skill",
            "params": {"args": ""},
            "id": "r1",
        }
    )
    assert errors


def test_validate_message_unknown_type() -> None:
    """Test message with unknown type is rejected (RFC-450 §6.3)."""
    msg = {"type": "custom", "data": "test"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "Unknown message type" in errors[0]


def test_validate_message_size_small() -> None:
    """Test message size validation with small message."""
    msg = {"type": "loop_input", "loop_id": "test", "content": "Hello"}
    assert validate_message_size(msg, max_size_bytes=1024)


def test_validate_message_size_large() -> None:
    """Test message size validation with large message."""
    large_text = "x" * (1024 * 1024)  # 1MB
    msg = {"type": "loop_input", "loop_id": "test", "content": large_text}
    assert not validate_message_size(msg, max_size_bytes=100)


def test_protocol_error_creation() -> None:
    """Test RpcProtocolError creation with numeric code (RFC-450 §7.4)."""
    error = RpcProtocolError(
        ErrorCode.INVALID_REQUEST,
        "Invalid message structure",
        data={"field": "type"},
    )

    assert error.code == ErrorCode.INVALID_REQUEST
    assert error.code == -32600
    assert error.message == "Invalid message structure"
    assert error.data == {"field": "type"}


def test_protocol_error_to_dict() -> None:
    """Test RpcProtocolError to_dict conversion produces wire envelope."""
    error = RpcProtocolError(
        ErrorCode.RATE_LIMITED,
        "Rate limit exceeded",
        data={"retry_after_ms": 100},
    )

    error_dict = error.to_dict()

    assert error_dict["type"] == "error"
    assert error_dict["error"]["code"] == -32000
    assert error_dict["error"]["message"] == "Rate limit exceeded"
    assert error_dict["error"]["data"]["retry_after_ms"] == 100


def test_protocol_error_to_dict_no_data() -> None:
    """Test RpcProtocolError to_dict omits data when empty."""
    error = RpcProtocolError(
        ErrorCode.INVALID_REQUEST,
        "Invalid message",
    )

    error_dict = error.to_dict()

    assert error_dict["type"] == "error"
    assert error_dict["error"]["code"] == -32600
    assert "data" not in error_dict["error"]


def test_build_error_response() -> None:
    """Test build_error_response helper produces wire envelope (RFC-450 §7.1)."""
    response = build_error_response(
        ErrorCode.INVALID_REQUEST,
        "Invalid message",
        request_id="req_42",
        data={"field": "text"},
    )

    assert response["proto"] == "1"
    assert response["type"] == "error"
    assert response["error"]["code"] == -32600
    assert response["error"]["message"] == "Invalid message"
    assert response["error"]["data"]["field"] == "text"
    assert response["id"] == "req_42"


def test_build_error_response_no_id_no_data() -> None:
    """build_error_response omits id and data when not provided."""
    response = build_error_response(
        ErrorCode.PARSE_ERROR,
        "Invalid JSON",
    )

    assert response["proto"] == "1"
    assert response["type"] == "error"
    assert response["error"]["code"] == -32700
    assert "data" not in response["error"]
    assert "id" not in response
