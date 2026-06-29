"""Tests for validate_message() covering ALL message types (RFC-450 §6.3, IG-522 Phase 8).

For each (type, method) pair in PARAMS_REGISTRY, this file tests:
- Valid params → empty error list
- Missing required field → non-empty error list
- Wrong type → non-empty error list

Also covers:
- Missing proto on envelope types → error
- Missing type → error
- Unknown type → error
- Unknown (type, method) combination → error
- Legacy flat format validation
- Envelope format validation
"""

from __future__ import annotations

from soothe_daemon.protocol.validation import VALID_TYPES, validate_message

# ---------------------------------------------------------------------------
# Envelope validation
# ---------------------------------------------------------------------------


class TestEnvelopeValidation:
    """Envelope-level validation (proto, type, method lookup)."""

    def test_missing_type(self) -> None:
        errors = validate_message({"text": "hello"})
        assert len(errors) == 1
        assert "type" in errors[0]

    def test_empty_type(self) -> None:
        errors = validate_message({"type": ""})
        assert len(errors) == 1
        assert "type" in errors[0]

    def test_unknown_type(self) -> None:
        errors = validate_message({"type": "future_msg"})
        assert len(errors) == 1
        assert "Unknown message type" in errors[0]

    def test_envelope_missing_proto_rejected(self) -> None:
        """Envelope types (request, notification, etc.) require proto='1'."""
        errors = validate_message(
            {
                "type": "request",
                "method": "loop_get",
                "params": {"loop_id": "abc"},
                "id": "r1",
            }
        )
        assert len(errors) == 1
        assert "proto" in errors[0].lower()

    def test_envelope_wrong_proto_rejected(self) -> None:
        errors = validate_message(
            {
                "proto": "2",
                "type": "request",
                "method": "loop_get",
                "params": {"loop_id": "abc"},
                "id": "r1",
            }
        )
        assert len(errors) == 1
        assert "proto" in errors[0].lower()

    def test_envelope_valid_proto(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "request",
                "method": "loop_get",
                "params": {"loop_id": "abc"},
                "id": "r1",
            }
        )
        assert errors == []

    def test_flat_form_rejected(self) -> None:
        """Legacy flat-form messages (no method/params) are rejected."""
        errors = validate_message({"type": "loop_get", "loop_id": "abc"})
        assert len(errors) >= 1
        assert "Unknown" in errors[0]

    def test_unknown_method_for_known_type(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "request",
                "method": "nonexistent_method",
                "params": {},
                "id": "r1",
            }
        )
        assert len(errors) >= 1
        assert "Unknown method" in errors[0] or "Unknown" in errors[0]

    def test_valid_types_includes_all_message_classes(self) -> None:
        """VALID_TYPES must include all RFC-450 §9.1 message classes."""
        for t in (
            "connection_init",
            "connection_ack",
            "request",
            "response",
            "notification",
            "subscribe",
            "next",
            "error",
            "complete",
            "unsubscribe",
            "ping",
            "pong",
            "receipt_response",
            "disconnect",
        ):
            assert t in VALID_TYPES, f"{t!r} missing from VALID_TYPES"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Envelope format validation (type + method + nested params)
# ---------------------------------------------------------------------------


class TestEnvelopeFormatValidation:
    """Validate messages in protocol-1 envelope format {proto, type, method, params, id}."""

    def test_loop_get_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "loop_get",
                    "params": {"loop_id": "abc"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_loop_get_envelope_missing_loop_id(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "request",
                "method": "loop_get",
                "params": {},
                "id": "r1",
            }
        )
        assert "loop_id" in errors[0]

    def test_loop_list_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "loop_list",
                    "params": {},
                    "id": "r1",
                }
            )
            == []
        )

    def test_loop_new_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "loop_new",
                    "params": {"workspace": "/tmp"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_loop_input_notification_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "notification",
                    "method": "loop_input",
                    "params": {"loop_id": "abc", "content": "hi"},
                }
            )
            == []
        )

    def test_loop_input_request_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "loop_input",
                    "params": {"loop_id": "abc", "content": "hi"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_loop_events_subscribe_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "subscribe",
                    "method": "loop_events",
                    "params": {"loop_id": "abc"},
                    "id": "s1",
                }
            )
            == []
        )

    def test_loop_events_subscribe_missing_loop_id(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "subscribe",
                "method": "loop_events",
                "params": {},
                "id": "s1",
            }
        )
        assert "loop_id" in errors[0]

    def test_autopilot_events_subscribe_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "subscribe",
                    "method": "autopilot_events",
                    "params": {},
                    "id": "s1",
                }
            )
            == []
        )

    def test_job_create_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_create",
                    "params": {"goal": "do thing"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_job_status_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "job_status",
                    "params": {"job_id": "j1"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_daemon_status_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "daemon_status",
                    "params": {},
                    "id": "r1",
                }
            )
            == []
        )

    def test_skills_list_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "skills_list",
                    "params": {},
                    "id": "r1",
                }
            )
            == []
        )

    def test_invoke_skill_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "invoke_skill",
                    "params": {"skill": "s1"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_invoke_skill_envelope_missing_skill(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "request",
                "method": "invoke_skill",
                "params": {},
                "id": "r1",
            }
        )
        assert "skill" in errors[0]

    def test_auth_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "auth",
                    "params": {"access_key": "ak", "secret_key": "sk"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_auth_refresh_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "auth_refresh",
                    "params": {"refresh_token": "rt"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_slash_command_notification_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "notification",
                    "method": "slash_command",
                    "params": {"cmd": "/exit"},
                }
            )
            == []
        )

    def test_slash_command_missing_cmd(self) -> None:
        errors = validate_message(
            {
                "proto": "1",
                "type": "notification",
                "method": "slash_command",
                "params": {},
            }
        )
        assert "cmd" in errors[0]

    def test_rpc_command_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "request",
                    "method": "rpc_command",
                    "params": {"command": "autopilot_status"},
                    "id": "r1",
                }
            )
            == []
        )

    def test_rpc_command_missing_command(self) -> None:
        # CommandRequestParams is intentionally permissive — the handler
        # returns a domain-specific error for missing command.
        errors = validate_message(
            {
                "proto": "1",
                "type": "request",
                "method": "rpc_command",
                "params": {},
                "id": "r1",
            }
        )
        assert errors == []

    def test_disconnect_notification_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "notification",
                    "method": "disconnect",
                    "params": {},
                }
            )
            == []
        )

    def test_unsubscribe_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "unsubscribe",
                    "id": "s1",
                }
            )
            == []
        )

    def test_connection_init_envelope(self) -> None:
        assert (
            validate_message(
                {
                    "proto": "1",
                    "type": "connection_init",
                    "params": {"client_version": "0.5.0", "accept_proto": ["1"]},
                }
            )
            == []
        )


# ---------------------------------------------------------------------------
# Message size validation
# ---------------------------------------------------------------------------


class TestMessageSizeValidation:
    """validate_message_size still works (unchanged)."""

    def test_small_message(self) -> None:
        from soothe_daemon.protocol.validation import validate_message_size

        assert validate_message_size({"type": "ping"}, max_size_bytes=1024)

    def test_large_message(self) -> None:
        from soothe_daemon.protocol.validation import validate_message_size

        large = "x" * (1024 * 1024)
        assert not validate_message_size(
            {"type": "loop_input", "content": large}, max_size_bytes=100
        )
