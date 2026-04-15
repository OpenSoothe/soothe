"""Unit tests for protocol validation (RFC-0013)."""

from __future__ import annotations


from soothe.daemon.protocol_v2 import (
    ERROR_AUTHENTICATION_REQUIRED,
    ERROR_INVALID_MESSAGE,
    ERROR_RATE_LIMITED,
    ProtocolError,
    create_error_response,
    validate_message,
    validate_message_size,
)


def test_validate_message_input_valid() -> None:
    """Test valid input message validation."""
    msg = {"type": "input", "text": "Hello, assistant!"}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_input_missing_text() -> None:
    """Test input message missing required text field."""
    msg = {"type": "input"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "text" in errors[0]


def test_validate_message_input_invalid_text_type() -> None:
    """Test input message with invalid text type."""
    msg = {"type": "input", "text": 123}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "must be a string" in errors[0]


def test_validate_message_input_autonomous_flag() -> None:
    """Test input message with autonomous flag."""
    msg = {"type": "input", "text": "Hello", "autonomous": True, "max_iterations": 10}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_input_invalid_autonomous() -> None:
    """Test input message with invalid autonomous flag."""
    msg = {"type": "input", "text": "Hello", "autonomous": "yes"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "autonomous must be a boolean" in errors[0]


def test_validate_message_command_valid() -> None:
    """Test valid command message validation."""
    msg = {"type": "command", "cmd": "/exit"}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_command_missing_cmd() -> None:
    """Test command message missing required cmd field."""
    msg = {"type": "command"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "cmd" in errors[0]


def test_validate_message_resume_thread_valid() -> None:
    """Test valid resume thread message validation."""
    msg = {"type": "resume_thread", "thread_id": "thread_001"}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_resume_thread_missing_id() -> None:
    """Test resume thread message missing thread_id."""
    msg = {"type": "resume_thread"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "thread_id" in errors[0]


def test_validate_message_detach_valid() -> None:
    """Test valid detach message validation."""
    msg = {"type": "detach"}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_auth_valid() -> None:
    """Test valid auth message validation."""
    msg = {"type": "auth", "token": "sk_live_abc123"}
    errors = validate_message(msg)
    assert errors == []


def test_validate_message_auth_missing_token() -> None:
    """Test auth message missing token."""
    msg = {"type": "auth"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "token" in errors[0]


def test_validate_message_missing_type() -> None:
    """Test message missing required type field."""
    msg = {"text": "Hello"}
    errors = validate_message(msg)
    assert len(errors) == 1
    assert "type" in errors[0]


def test_validate_message_skills_list_valid() -> None:
    errors = validate_message({"type": "skills_list"})
    assert errors == []


def test_validate_message_models_list_valid() -> None:
    errors = validate_message({"type": "models_list"})
    assert errors == []


def test_validate_message_invoke_skill_valid() -> None:
    errors = validate_message({"type": "invoke_skill", "skill": "my-skill", "args": "x"})
    assert errors == []


def test_validate_message_invoke_skill_missing_skill() -> None:
    errors = validate_message({"type": "invoke_skill", "args": ""})
    assert errors


def test_validate_message_unknown_type() -> None:
    """Test message with unknown type is allowed."""
    msg = {"type": "custom", "data": "test"}
    errors = validate_message(msg)
    assert errors == []  # Unknown types are allowed for forward compatibility


def test_validate_message_size_small() -> None:
    """Test message size validation with small message."""
    msg = {"type": "input", "text": "Hello"}
    assert validate_message_size(msg, max_size_bytes=1024)


def test_validate_message_size_large() -> None:
    """Test message size validation with large message."""
    large_text = "x" * (1024 * 1024)  # 1MB
    msg = {"type": "input", "text": large_text}
    assert not validate_message_size(msg, max_size_bytes=100)


def test_protocol_error_creation() -> None:
    """Test ProtocolError creation."""
    error = ProtocolError(
        code=ERROR_INVALID_MESSAGE,
        message="Invalid message structure",
        details={"field": "type"},
    )

    assert error.code == ERROR_INVALID_MESSAGE
    assert error.message == "Invalid message structure"
    assert error.details == {"field": "type"}


def test_protocol_error_to_dict() -> None:
    """Test ProtocolError to_dict conversion."""
    error = ProtocolError(
        code=ERROR_RATE_LIMITED,
        message="Rate limit exceeded",
        details={"retry_after_ms": 100},
    )

    error_dict = error.to_dict()

    assert error_dict["type"] == "error"
    assert error_dict["code"] == ERROR_RATE_LIMITED
    assert error_dict["message"] == "Rate limit exceeded"
    assert error_dict["details"]["retry_after_ms"] == 100


def test_protocol_error_to_dict_no_details() -> None:
    """Test ProtocolError to_dict without details."""
    error = ProtocolError(
        code=ERROR_AUTHENTICATION_REQUIRED,
        message="Authentication required",
    )

    error_dict = error.to_dict()

    assert error_dict["type"] == "error"
    assert error_dict["code"] == ERROR_AUTHENTICATION_REQUIRED
    assert "details" not in error_dict


def test_create_error_response() -> None:
    """Test create_error_response helper function."""
    response = create_error_response(
        code=ERROR_INVALID_MESSAGE,
        message="Invalid message",
        details={"field": "text"},
    )

    assert response["type"] == "error"
    assert response["code"] == ERROR_INVALID_MESSAGE
    assert response["message"] == "Invalid message"
    assert response["details"]["field"] == "text"
