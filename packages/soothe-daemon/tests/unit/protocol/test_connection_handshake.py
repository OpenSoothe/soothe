"""Unit tests for the connection_init / connection_ack handshake (RFC-450 §8.2, phase 3).

Covers:
- ``connection_init`` with valid params → ``connection_ack`` with ``readiness_state: "ready"``
- ``connection_init`` with unsupported ``accept_proto`` → ``readiness_state: "incompatible"``
- Messages sent before the handshake completes → ``-32600 INVALID_REQUEST``
- Capability intersection (client declares subset → server echoes only those)
- Bidirectional heartbeat ``ping`` / ``pong`` round-trip
- Handshake state is tracked per-connection on the daemon / router
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.protocol import ErrorCode, MessageRouter, build_error_response
from soothe_daemon.protocol.router import _DAEMON_CAPABILITIES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_daemon(*, readiness_state: str = "ready", heartbeat_ms: int = 30000) -> SimpleNamespace:
    """Build a minimal daemon stub satisfying the router's attribute access."""
    from soothe_daemon.server.core import SootheDaemon

    sent: list[dict] = []

    async def _send_client_message(_client_id: object, msg: dict) -> None:
        sent.append(msg)

    ws_config = SimpleNamespace(heartbeat_interval_ms=heartbeat_ms)
    daemon_config = SimpleNamespace(transports=SimpleNamespace(websocket=ws_config))
    daemon = SimpleNamespace(
        _readiness_state=readiness_state,
        _readiness_message=None,
        _daemon_config=daemon_config,
        _session_manager=MagicMock(),
        _send_client_message=AsyncMock(side_effect=_send_client_message),
    )
    # Bind the real build_connection_ack method (unbound) so the mock has
    # the same negotiation logic as the daemon without a full SootheDaemon.
    daemon.build_connection_ack = SootheDaemon.build_connection_ack.__get__(daemon)  # type: ignore[method-assign]
    daemon._sent = sent  # type: ignore[attr-defined]
    return daemon


def _connection_init_msg(
    *,
    accept_proto: list[str] | None = None,
    capabilities: list[str] | None = None,
    client_version: str = "0.5.0",
) -> dict:
    return {
        "proto": "1",
        "type": "connection_init",
        "params": {
            "client_version": client_version,
            "client_name": "soothe-cli",
            "accept_proto": accept_proto if accept_proto is not None else ["1"],
            "capabilities": capabilities
            if capabilities is not None
            else ["streaming", "batch", "heartbeat"],
        },
    }


# ---------------------------------------------------------------------------
# Handshake success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_init_success_returns_ack_with_ready_state() -> None:
    """A valid connection_init produces a connection_ack with readiness_state 'ready'."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    await router.dispatch("client-1", _connection_init_msg())

    assert len(daemon._sent) == 1
    ack = daemon._sent[0]
    assert ack["proto"] == "1"
    assert ack["type"] == "connection_ack"
    result = ack["result"]
    assert result["readiness_state"] == "ready"
    assert result["protocol_version"] == "1"
    assert "streaming" in result["capabilities"]
    assert "batch" in result["capabilities"]
    assert "heartbeat" in result["capabilities"]
    assert result["heartbeat_interval_ms"] == 30000
    assert result["server_version"]  # non-empty


@pytest.mark.asyncio
async def test_connection_init_marks_handshake_complete() -> None:
    """After connection_ack, the router marks the connection's handshake as complete."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    # Before handshake, the client is not in the handshake-state dict.
    assert "client-1" not in router._handshake_state
    await router.dispatch("client-1", _connection_init_msg())
    # After handshake, the client is tracked with proto version "1".
    assert router._is_handshake_complete("client-1")
    assert router._get_proto_version("client-1") == "1"


# ---------------------------------------------------------------------------
# Proto mismatch rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_init_unsupported_proto_returns_incompatible() -> None:
    """Client declaring only proto '2' → readiness_state 'incompatible'."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    msg = _connection_init_msg(accept_proto=["2"])
    await router.dispatch("client-2", msg)

    assert len(daemon._sent) == 1
    ack = daemon._sent[0]
    assert ack["type"] == "connection_ack"
    assert ack["result"]["readiness_state"] == "incompatible"
    assert ack["result"]["capabilities"] == []


@pytest.mark.asyncio
async def test_connection_init_empty_accept_proto_returns_incompatible() -> None:
    """An empty accept_proto list yields incompatible (no common version)."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    msg = _connection_init_msg(accept_proto=[])
    await router.dispatch("client-3", msg)

    ack = daemon._sent[0]
    assert ack["result"]["readiness_state"] == "incompatible"


# ---------------------------------------------------------------------------
# Pre-handshake message rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_handshake_message_rejected_with_invalid_request() -> None:
    """A message sent before connection_init is rejected with -32600."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    await router.dispatch("client-pre-handshake", {"proto": "1", "type": "loop_list"})

    assert len(daemon._sent) == 1
    err = daemon._sent[0]
    assert err["type"] == "error"
    assert err["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert "handshake" in err["error"]["message"].lower()


@pytest.mark.asyncio
async def test_message_allowed_after_handshake_completes() -> None:
    """After the handshake, a normal message is dispatched (not rejected)."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    # Complete handshake
    await router.dispatch("client-5", _connection_init_msg())
    assert len(daemon._sent) == 1  # only the ack so far

    # Now a ping should be accepted (pong sent)
    await router.dispatch("client-5", {"proto": "1", "type": "ping"})
    # The second sent message should be a pong
    assert len(daemon._sent) == 2
    assert daemon._sent[1]["type"] == "pong"


# ---------------------------------------------------------------------------
# Capability intersection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_intersection_returns_only_declared() -> None:
    """Server echoes only capabilities the client declared."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    msg = _connection_init_msg(capabilities=["streaming"])
    await router.dispatch("client-6", msg)

    ack = daemon._sent[0]
    caps = ack["result"]["capabilities"]
    assert caps == ["streaming"]
    assert "batch" not in caps


@pytest.mark.asyncio
async def test_capability_intersection_empty_client_capabilities() -> None:
    """A client declaring no capabilities gets an empty intersection."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    msg = _connection_init_msg(capabilities=[])
    await router.dispatch("client-7", msg)

    ack = daemon._sent[0]
    assert ack["result"]["capabilities"] == []


# ---------------------------------------------------------------------------
# Heartbeat ping/pong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_pong_round_trip() -> None:
    """A ping message produces a pong response."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    # Complete handshake first
    await router.dispatch("client-8", _connection_init_msg())
    # Send ping
    await router.dispatch("client-8", {"proto": "1", "type": "ping"})

    pong = daemon._sent[-1]
    assert pong["proto"] == "1"
    assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_pong_is_accepted_without_error() -> None:
    """A pong message (response to our ping) is accepted without sending anything."""
    daemon = _make_daemon(readiness_state="ready")
    router = MessageRouter(daemon)

    await router.dispatch("client-9", _connection_init_msg())
    sent_before = len(daemon._sent)
    await router.dispatch("client-9", {"proto": "1", "type": "pong"})
    assert len(daemon._sent) == sent_before  # no new message sent


# ---------------------------------------------------------------------------
# Transitional readiness states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_init_starting_state_reflected_in_ack() -> None:
    """When daemon is starting, readiness_state in the ack is 'starting'."""
    daemon = _make_daemon(readiness_state="starting")
    router = MessageRouter(daemon)

    await router.dispatch("client-10", _connection_init_msg())

    ack = daemon._sent[0]
    assert ack["result"]["readiness_state"] == "starting"
    # Handshake still completes — the client can bounded-retry
    assert router._is_handshake_complete("client-10")


# ---------------------------------------------------------------------------
# Error envelope structure
# ---------------------------------------------------------------------------


def test_build_error_response_invalid_request_structure() -> None:
    """The INVALID_REQUEST error envelope has the correct wire structure."""
    err = build_error_response(
        ErrorCode.INVALID_REQUEST,
        "Handshake must complete before sending messages",
        data={"type": "loop_list"},
    )
    assert err["proto"] == "1"
    assert err["type"] == "error"
    assert err["error"]["code"] == -32600
    assert err["error"]["data"] == {"type": "loop_list"}


# ---------------------------------------------------------------------------
# Daemon capabilities constant
# ---------------------------------------------------------------------------


def test_daemon_capabilities_include_streaming_batch_heartbeat() -> None:
    """The daemon declares streaming, batch, and heartbeat capabilities."""
    assert set(_DAEMON_CAPABILITIES) >= {"streaming", "batch", "heartbeat"}
