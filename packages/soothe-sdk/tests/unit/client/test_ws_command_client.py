"""Unit tests for WsCommandClient protocol-1 wire format (RFC-450 §5, IG-522 Phase 6).

Covers the migration from the old ``{type:'command', command:..., payload:...}``
format to the unified protocol-1 envelope:

- ``_send_command`` sends a ``WireEnvelope`` with ``type='request'``,
  ``method=command_type``, ``params=payload``, ``id=uuid4``.
- Serialization uses :func:`encode_envelope` / :func:`decode_envelope`.
- Response parsing handles ``{type:'response', result:...}`` (success).
- Response parsing handles ``{type:'error', code:..., message:...}`` (error →
  ``RuntimeError`` carrying the daemon's code/message).
- The old ``command`` key is absent; ``method`` is used instead.
- The public convenience API (``autopilot_status``, ``autopilot_submit``,
  ``cron_add``, etc.) delegates to the migrated ``_send_command``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from soothe_sdk.client.ws_command_client import WsCommandClient

# ---------------------------------------------------------------------------
# Helpers: fake a websockets.connect async context manager
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Minimal stand-in for a websockets Connection used by WsCommandClient."""

    def __init__(self, *, send_captured: list[str] | None = None) -> None:
        self._send_captured = send_captured if send_captured is not None else []
        # ``recv`` is an AsyncMock configured per-test.
        self.recv = AsyncMock()
        self.send = AsyncMock(side_effect=self._record_send)

    async def _record_send(self, text: str) -> None:
        self._send_captured.append(text)

    async def __aenter__(self) -> _FakeWebSocket:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _patch_connect(fake_ws: _FakeWebSocket):
    """Return a patcher for ``websockets.connect`` returning ``fake_ws``."""
    return patch(
        "websockets.connect",
        return_value=MagicMock(__aenter__=AsyncMock(return_value=fake_ws)),
    )


def _connection_ack_json(*, readiness_state: str = "ready") -> str:
    """Return a ready ``connection_ack`` frame for handshake mocks."""
    return json.dumps(
        {
            "proto": "1",
            "type": "connection_ack",
            "result": {
                "server_version": "0.0.0",
                "protocol_version": "1",
                "capabilities": ["streaming", "batch", "heartbeat"],
                "readiness_state": readiness_state,
                "heartbeat_interval_ms": 30000,
            },
        }
    )


def _last_sent_type(fake_ws: _FakeWebSocket) -> str:
    """Return the ``type`` field of the most recently sent wire frame."""
    return json.loads(fake_ws._send_captured[-1]).get("type", "")


def _response_for_last_request(
    fake_ws: _FakeWebSocket,
    *,
    result: dict[str, Any] | None = None,
) -> str:
    """Build a matching ``response`` envelope for the latest request frame."""
    sent = json.loads(fake_ws._send_captured[-1])
    return json.dumps({"proto": "1", "type": "response", "result": result or {}, "id": sent["id"]})


def _install_handshake_then_response_recv(
    fake_ws: _FakeWebSocket,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    """Mock recv to complete handshake, then return one matching response."""

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        return _response_for_last_request(fake_ws, result=result)

    fake_ws.recv = AsyncMock(side_effect=recv)


# ---------------------------------------------------------------------------
# Request envelope construction
# ---------------------------------------------------------------------------


async def test_send_command_performs_connection_handshake_before_request() -> None:
    """_send_command sends connection_init and waits for connection_ack first."""
    fake_ws = _FakeWebSocket()
    _install_handshake_then_response_recv(fake_ws, result={"ok": True})
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        result = await client._send_command("autopilot_status")

    assert result == {"ok": True}
    assert len(fake_ws._send_captured) == 2
    init = json.loads(fake_ws._send_captured[0])
    request = json.loads(fake_ws._send_captured[1])
    assert init["type"] == "connection_init"
    assert request["type"] == "request"
    assert request["method"] == "autopilot_status"


async def test_send_command_uses_protocol1_request_envelope() -> None:
    """_send_command sends {proto, type='request', method, params, id} on the wire."""
    fake_ws = _FakeWebSocket()
    captured_id = ""

    async def recv() -> str:
        nonlocal captured_id
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        captured_id = sent["id"]
        return json.dumps(
            {"proto": "1", "type": "response", "result": {"ok": True}, "id": captured_id}
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        result = await client._send_command("autopilot_status", {"filter": "all"})

    # Result is the response's `result` payload.
    assert result == {"ok": True}

    # The sent request frame is a protocol-1 request envelope.
    sent = json.loads(fake_ws._send_captured[-1])
    assert sent["proto"] == "1"
    assert sent["type"] == "request"
    assert sent["method"] == "autopilot_status"
    assert sent["params"] == {"filter": "all"}
    assert sent["id"] == captured_id
    # id is a UUID4 string (36 chars, valid hex).
    assert len(sent["id"]) == 36
    UUID(sent["id"], version=4)


async def test_send_command_no_old_command_key() -> None:
    """The old 'command' key is gone; 'method' is used instead (IG-522 Phase 6)."""
    fake_ws = _FakeWebSocket()
    _install_handshake_then_response_recv(fake_ws)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        await client._send_command("autopilot_status")

    sent = json.loads(fake_ws._send_captured[-1])
    assert "command" not in sent
    assert "request_id" not in sent
    assert "payload" not in sent
    assert sent["method"] == "autopilot_status"
    # Empty params are omitted from the wire (compact form); the envelope still
    # carries params={} internally, which the daemon treats as no parameters.
    assert sent.get("params", {}) == {}


async def test_send_command_default_payload_is_empty_dict() -> None:
    """Omitting payload still produces a valid request with no extra param fields."""
    fake_ws = _FakeWebSocket()
    _install_handshake_then_response_recv(fake_ws)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        await client._send_command("cron_list")

    sent = json.loads(fake_ws._send_captured[-1])
    assert sent["method"] == "cron_list"
    # No stray payload/command keys; empty params omitted from wire.
    assert "payload" not in sent
    assert "command" not in sent


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


async def test_send_command_returns_result_from_response_envelope() -> None:
    """A {type:'response', result:...} envelope returns its result dict."""
    fake_ws = _FakeWebSocket()
    _install_handshake_then_response_recv(fake_ws, result={"goals": ["g1", "g2"]})
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        result = await client._send_command("autopilot_list_goals")

    assert result == {"goals": ["g1", "g2"]}


async def test_send_command_error_envelope_raises_runtimeerror() -> None:
    """A {type:'error', code, message} envelope raises RuntimeError with code/message."""
    fake_ws = _FakeWebSocket()

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        return json.dumps(
            {
                "proto": "1",
                "type": "error",
                "error": {
                    "code": -32602,
                    "message": "Invalid params",
                    "data": {"field": "goal_id"},
                },
                "id": sent["id"],
            }
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        with pytest.raises(RuntimeError) as exc_info:
            await client._send_command("autopilot_get_goal", {"goal_id": "missing"})

    msg = str(exc_info.value)
    assert "-32602" in msg
    assert "Invalid params" in msg


async def test_send_command_error_envelope_without_data() -> None:
    """An error envelope with no data still raises RuntimeError with code/message."""
    fake_ws = _FakeWebSocket()

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        return json.dumps(
            {
                "proto": "1",
                "type": "error",
                "error": {"code": -32600, "message": "Invalid request"},
                "id": sent["id"],
            }
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        with pytest.raises(RuntimeError) as exc_info:
            await client._send_command("autopilot_status")

    assert "-32600" in str(exc_info.value)
    assert "Invalid request" in str(exc_info.value)


async def test_send_command_error_form_propagated() -> None:
    """An RFC-450 nested error envelope is propagated as a RuntimeError."""
    fake_ws = _FakeWebSocket()

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        return json.dumps(
            {
                "proto": "1",
                "type": "error",
                "error": {"code": -32603, "message": "Internal error"},
                "id": sent["id"],
            }
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        with pytest.raises(RuntimeError) as exc_info:
            await client._send_command("memory_stats", {"mode": "daemon"})

    assert "-32603" in str(exc_info.value)
    assert "Internal error" in str(exc_info.value)


async def test_send_command_correlates_response_by_id() -> None:
    """_send_command ignores responses whose id doesn't match and waits for its own."""
    fake_ws = _FakeWebSocket()
    calls = 0

    async def recv() -> str:
        nonlocal calls
        calls += 1
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        if calls == 2:
            # Unrelated response with a different id — must be skipped.
            return json.dumps(
                {"proto": "1", "type": "response", "result": {"stale": True}, "id": "other-id"}
            )
        # Matching response.
        return json.dumps(
            {"proto": "1", "type": "response", "result": {"matched": True}, "id": sent["id"]}
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        result = await client._send_command("autopilot_status")

    assert result == {"matched": True}
    assert calls == 3


async def test_send_command_skips_unrelated_message_types() -> None:
    """Non-response/error frames (e.g. next/complete) are skipped until the match."""
    fake_ws = _FakeWebSocket()
    calls = 0

    async def recv() -> str:
        nonlocal calls
        calls += 1
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        if calls == 2:
            # A stray 'next' message, unrelated type for a blocking request.
            return json.dumps({"proto": "1", "type": "next", "payload": {"x": 1}, "id": sent["id"]})
        return json.dumps(
            {"proto": "1", "type": "response", "result": {"done": True}, "id": sent["id"]}
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        result = await client._send_command("autopilot_status")

    assert result == {"done": True}


async def test_send_command_invalid_json_raises_runtimeerror() -> None:
    """A non-JSON or non-dict response raises RuntimeError."""
    fake_ws = _FakeWebSocket()
    calls = 0

    async def recv() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _connection_ack_json()
        return "not json"

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        with pytest.raises(RuntimeError):
            await client._send_command("autopilot_status")


# ---------------------------------------------------------------------------
# Serialization helpers (encode_envelope / decode_envelope)
# ---------------------------------------------------------------------------


async def test_send_command_uses_encode_envelope_not_raw_json_dumps() -> None:
    """The sent frame is produced by encode_envelope (compact, proto-1 compliant)."""
    fake_ws = _FakeWebSocket()
    _install_handshake_then_response_recv(fake_ws)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        await client._send_command("autopilot_status")

    raw = fake_ws._send_captured[-1]
    # encode_envelope uses compact separators (no spaces after , or :).
    assert ", " not in raw
    assert ": " not in raw
    # And the decoded form round-trips via decode_envelope.
    from soothe_sdk.client.wire import decode_envelope

    decoded = decode_envelope(raw)
    assert isinstance(decoded, dict)
    assert decoded["type"] == "request"


# ---------------------------------------------------------------------------
# Public API delegation
# ---------------------------------------------------------------------------


async def test_autopilot_status_delegates_to_send_command() -> None:
    """autopilot_status() calls _send_command('autopilot_status') with no payload."""
    client = WsCommandClient("ws://localhost:8765/")
    captured: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_send(command_type, payload=None):
        captured.append((command_type, payload))
        return {"status": "idle"}

    client._send_command = fake_send  # type: ignore[assignment]

    result = await client.autopilot_status()

    assert result == {"status": "idle"}
    assert captured == [("autopilot_status", None)]


async def test_autopilot_submit_sends_correct_method_and_payload() -> None:
    """autopilot_submit() delegates with method='autopilot_submit' and its payload."""
    client = WsCommandClient("ws://localhost:8765/")
    captured: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_send(command_type, payload=None):
        captured.append((command_type, payload))
        return {"goal_id": "g-123"}

    client._send_command = fake_send  # type: ignore[assignment]

    result = await client.autopilot_submit("deploy the app", priority=80, workspace="/tmp")

    assert result == {"goal_id": "g-123"}
    method, payload = captured[0]
    assert method == "autopilot_submit"
    assert payload == {"description": "deploy the app", "priority": 80, "workspace": "/tmp"}


async def test_cron_add_delegates_to_send_command() -> None:
    """cron_add() delegates with method='cron_add' and its payload."""
    client = WsCommandClient("ws://localhost:8765/")
    captured: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_send(command_type, payload=None):
        captured.append((command_type, payload))
        return {"job_id": "cj-1"}

    client._send_command = fake_send  # type: ignore[assignment]

    result = await client.cron_add("in 1 hour remind me to deploy", priority=10)

    assert result == {"job": {"id": "cj-1"}}
    method, payload = captured[0]
    assert method == "cron_add"
    assert payload == {"text": "in 1 hour remind me to deploy", "priority": 10}


async def test_memory_stats_delegates_to_send_command() -> None:
    """memory_stats() delegates with method='memory_stats' and mode param."""
    client = WsCommandClient("ws://localhost:8765/")
    captured: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_send(command_type, payload=None):
        captured.append((command_type, payload))
        return {"rss_mb": 120}

    client._send_command = fake_send  # type: ignore[assignment]

    result = await client.memory_stats("daemon")

    assert result == {"rss_mb": 120}
    method, payload = captured[0]
    assert method == "memory_stats"
    assert payload == {"mode": "daemon"}


# ---------------------------------------------------------------------------
# Error propagation shape (CLI compatibility)
# ---------------------------------------------------------------------------


async def test_error_envelope_propagates_as_runtime_error() -> None:
    """Errors surface as RuntimeError (not ProtocolError) so CLI catch sites keep working."""
    fake_ws = _FakeWebSocket()

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        return json.dumps(
            {
                "proto": "1",
                "type": "error",
                "error": {"code": -32601, "message": "Method not found"},
                "id": sent["id"],
            }
        )

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        with pytest.raises(RuntimeError) as exc_info:
            await client._send_command("autopilot_status")

    # CLI code does `except RuntimeError: typer.echo(str(exc))` — the message
    # must contain the daemon's code and message.
    assert "-32601" in str(exc_info.value)
    assert "Method not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# id is a fresh UUID4 per call
# ---------------------------------------------------------------------------


async def test_request_id_is_unique_uuid4_per_call() -> None:
    """Each _send_command call generates a distinct UUID4 id."""
    ids: list[str] = []
    fake_ws = _FakeWebSocket()

    async def recv() -> str:
        if _last_sent_type(fake_ws) == "connection_init":
            return _connection_ack_json()
        sent = json.loads(fake_ws._send_captured[-1])
        ids.append(sent["id"])
        return json.dumps({"proto": "1", "type": "response", "result": {}, "id": sent["id"]})

    fake_ws.recv = AsyncMock(side_effect=recv)
    client = WsCommandClient("ws://localhost:8765/")

    with _patch_connect(fake_ws):
        await client._send_command("autopilot_status")
        await client._send_command("autopilot_status")

    assert len(ids) == 2
    assert ids[0] != ids[1]
    for rid in ids:
        UUID(rid, version=4)
