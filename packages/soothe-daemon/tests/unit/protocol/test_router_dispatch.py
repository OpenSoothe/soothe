"""Tests for the registry-based MessageRouter dispatch (RFC-450 §6/§9, Phase 4).

Covers:
- ``HANDLER_REGISTRY`` covers all message types previously dispatched via if-chain
- ``dispatch()`` routes to the correct handler for each registry entry
- Unknown message types receive ``-32601 METHOD_NOT_FOUND``
- Param validation failures receive ``-32602 INVALID_PARAMS``
- Error responses use ``build_error_response()`` wire format (proto, type,
  error:{code, message, data?}, id?)
- ``RpcProtocolError`` raised inside a handler is serialized to the standard error envelope
- ``dispatch()`` source contains no ``if msg_type ==`` branches (static check)
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.protocol import ErrorCode, MessageRouter
from soothe_daemon.protocol.error_codes import RpcProtocolError
from soothe_daemon.protocol.router import PARAMS_REGISTRY

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSessionManager:
    """Minimal session manager stub for dispatch tests."""

    async def get_session(self, client_id: Any) -> Any:
        return SimpleNamespace(subscriptions=set(), detach_requested=False)

    async def get_owned_loop(self, client_id: Any) -> str | None:
        return None


class _FakeDaemon:
    """Bare daemon stub that records sent messages."""

    _session_manager = _FakeSessionManager()

    def __init__(self) -> None:
        self.sent: list[tuple[Any, dict[str, Any]]] = []
        self._started_at: str | None = None

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        self.sent.append((client_id, msg))

    def daemon_ready_message(self) -> dict[str, Any]:
        return {"type": "daemon_ready", "state": "ready"}


def _make_router() -> tuple[MessageRouter, _FakeDaemon]:
    """Create a router backed by a recording fake daemon."""
    daemon = _FakeDaemon()
    router = MessageRouter(daemon)
    # Bypass handshake enforcement for unit tests.
    router._is_handshake_complete = lambda _cid: True  # type: ignore[method-assign]
    return router, daemon


# ---------------------------------------------------------------------------
# HANDLER_REGISTRY completeness
# ---------------------------------------------------------------------------


def test_handler_registry_covers_all_legacy_message_types() -> None:
    """Every operation that was in the old if-chain must still resolve to a handler.

    The daemon now accepts protocol-1 envelopes only. The three control types
    (connection_init/ping/pong) live in ``HANDLER_REGISTRY``; every other
    operation is dispatched by envelope ``method`` via ``_resolve_handler()``
    (the five method-name overrides, or the ``_handle_<method>`` convention).
    The legacy method names below must each resolve to a real handler method.
    """
    control_types = {"connection_init", "ping", "pong"}
    registry_keys = set(MessageRouter.HANDLER_REGISTRY.keys())
    assert registry_keys == control_types, (
        f"HANDLER_REGISTRY must contain exactly the control types: {registry_keys}"
    )

    # Every envelope method must resolve to a handler method on MessageRouter
    # (via _resolve_handler). The five method-name overrides plus the
    # ``_handle_<method>`` convention cover every supported operation.
    envelope_methods = {
        "slash_command",
        "rpc_command",
        "disconnect",
        "auth",
        "auth_refresh",
        "loop_list",
        "loop_get",
        "loop_tree",
        "loop_prune",
        "loop_delete",
        "loop_reattach",
        "loop_events",
        "loop_detach",
        "loop_new",
        "loop_input",
        "loop_messages",
        "loop_state_get",
        "loop_state_update",
        "loop_execution_state_fetch",
        "loop_history_fetch",
        "skills_list",
        "invoke_skill",
        "models_list",
        "mcp_status",
        "daemon_status",
        "daemon_shutdown",
        "config_get",
        "job_create",
        "job_status",
        "job_pause",
        "job_resume",
        "job_cancel",
        "job_dag",
        "job_guidance",
        "autopilot_events",
        "autopilot_unsubscribe",
    }
    unresolved = {m for m in envelope_methods if MessageRouter._resolve_handler(m) is None}
    assert not unresolved, f"No handler resolves for envelope methods: {unresolved}"


def test_handler_registry_values_are_valid_method_names() -> None:
    """Every registry value must name an existing method on MessageRouter."""
    for msg_type, handler_name in MessageRouter.HANDLER_REGISTRY.items():
        assert hasattr(MessageRouter, handler_name), (
            f"HANDLER_REGISTRY[{msg_type!r}] = {handler_name!r} "
            f"but MessageRouter has no such method"
        )
        method = getattr(MessageRouter, handler_name)
        assert callable(method), f"{handler_name} is not callable"


def test_params_registry_covers_all_handler_registry_types() -> None:
    """Every HANDLER_REGISTRY type should have a matching PARAMS_REGISTRY entry."""
    for msg_type in MessageRouter.HANDLER_REGISTRY:
        assert (msg_type, None) in PARAMS_REGISTRY, (
            f"No PARAMS_REGISTRY entry for ({msg_type!r}, None)"
        )


# ---------------------------------------------------------------------------
# Dispatch routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_rejects_removed_daemon_ready() -> None:
    """daemon_ready was removed in the protocol-1 clear cut — rejected."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "notification", "method": "daemon_ready", "params": {}},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == -32601  # METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_dispatch_routes_ping() -> None:
    """ping dispatches to _handle_ping and returns pong."""
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "ping"})
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "pong"


@pytest.mark.asyncio
async def test_dispatch_routes_pong() -> None:
    """pong dispatches to _handle_pong (no response sent)."""
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "pong"})
    assert len(daemon.sent) == 0  # pong is an ack, no response


@pytest.mark.asyncio
async def test_dispatch_routes_detach() -> None:
    """detach (disconnect notification) dispatches to _handle_detach."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "notification", "method": "disconnect", "params": {}},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "status"
    assert msg["state"] == "detached"


@pytest.mark.asyncio
async def test_dispatch_routes_command_exit() -> None:
    """slash_command notification with /exit dispatches and sends detached status."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/exit"},
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "status"
    assert msg["state"] == "detached"


@pytest.mark.asyncio
async def test_dispatch_routes_daemon_status() -> None:
    """daemon_status dispatches to _handle_daemon_status."""
    router, daemon = _make_router()

    # The handler accesses many daemon attributes; stub them minimally.
    daemon._running = True
    daemon._channel_manager = None
    daemon._active_threads = set()
    daemon._readiness_state = "ready"
    daemon._readiness_message = ""
    daemon._started_at = "2026-01-01T00:00:00+00:00"

    import os

    from soothe import __version__ as core_version

    from soothe_daemon import __version__ as daemon_version

    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "request", "method": "daemon_status", "params": {}, "id": "r1"},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "response"
    assert msg["id"] == "r1"
    assert msg["result"]["running"] is True
    assert msg["result"]["daemon_pid"] == os.getpid()
    assert msg["result"]["started_at"] == "2026-01-01T00:00:00+00:00"
    assert msg["result"]["daemon_version"] == daemon_version
    assert msg["result"]["core_version"] == core_version


# ---------------------------------------------------------------------------
# Protocol-1 envelope unwrapping (request/notification/subscribe/unsubscribe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_unwraps_request_envelope() -> None:
    """A ``type="request"`` envelope is unwrapped to ``type=method`` flat format."""
    router, daemon = _make_router()
    # Stub the daemon_status handler dependencies
    daemon._running = True
    daemon._channel_manager = None
    daemon._active_threads = set()
    daemon._readiness_state = "ready"
    daemon._readiness_message = ""
    daemon._started_at = "2026-01-01T00:00:00+00:00"

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "daemon_status",
            "params": {},
            "id": "req-42",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "response"
    assert msg["id"] == "req-42"


@pytest.mark.asyncio
async def test_dispatch_unwraps_request_envelope_with_params() -> None:
    """A ``request`` envelope spreads ``params`` into the flat message."""
    router, daemon = _make_router()

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "command",
            "params": {"cmd": "/exit"},
            "id": "req-1",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "status"
    assert msg["state"] == "detached"


@pytest.mark.asyncio
async def test_dispatch_unwraps_request_envelope_missing_params() -> None:
    """A ``request`` envelope with ``params=None`` is treated as empty dict."""
    router, daemon = _make_router()
    daemon._running = True
    daemon._channel_manager = None
    daemon._active_threads = set()
    daemon._readiness_state = "ready"
    daemon._readiness_message = ""

    # SDK drops empty params dicts, so params may be absent entirely.
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "daemon_status",
            "id": "req-3",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "response"


@pytest.mark.asyncio
async def test_dispatch_unwraps_notification_envelope() -> None:
    """A ``type="notification"`` envelope is unwrapped to ``type=method``."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/exit"},
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "status"
    assert msg["state"] == "detached"


@pytest.mark.asyncio
async def test_dispatch_unwraps_notification_disconnect_to_detach() -> None:
    """A ``notification`` with ``method="disconnect"`` maps to ``detach``."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "notification",
            "method": "disconnect",
            "params": {},
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "status"
    assert msg["state"] == "detached"


@pytest.mark.asyncio
async def test_dispatch_unwraps_subscribe_envelope() -> None:
    """A ``type="subscribe"`` envelope with ``method="loop_events"`` maps to
    ``loop_subscribe`` flat type and reaches the handler."""
    router, daemon = _make_router()
    called: list[dict[str, Any]] = []

    async def _stub_handler(client_id, msg):
        called.append(msg)

    router._handle_loop_subscribe = _stub_handler  # type: ignore[method-assign]

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "subscribe",
            "method": "loop_events",
            "params": {"loop_id": "loop-1"},
            "id": "sub-1",
        },
    )
    assert len(called) == 1
    assert called[0]["type"] == "loop_events"
    assert called[0]["loop_id"] == "loop-1"
    assert called[0]["request_id"] == "sub-1"


@pytest.mark.asyncio
async def test_dispatch_unwraps_unsubscribe_envelope_with_loop_id() -> None:
    """An ``unsubscribe`` envelope with ``loop_id`` in params maps to
    ``loop_detach`` flat type and reaches the handler."""
    router, daemon = _make_router()
    called: list[dict[str, Any]] = []

    async def _stub_handler(client_id, msg):
        called.append(msg)

    router._handle_loop_detach = _stub_handler  # type: ignore[method-assign]

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "unsubscribe",
            "params": {"loop_id": "loop-1"},
            "id": "sub-1",
        },
    )
    assert len(called) == 1
    assert called[0]["type"] == "loop_detach"
    assert called[0]["loop_id"] == "loop-1"
    assert called[0]["request_id"] == "sub-1"


@pytest.mark.asyncio
async def test_dispatch_unwraps_unsubscribe_envelope_without_loop_id() -> None:
    """An ``unsubscribe`` envelope without ``loop_id`` maps to
    ``autopilot_unsubscribe`` flat type and reaches the handler."""
    router, daemon = _make_router()
    called: list[dict[str, Any]] = []

    async def _stub_handler(client_id, msg):
        called.append(msg)

    router._handle_autopilot_unsubscribe = _stub_handler  # type: ignore[method-assign]

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "unsubscribe",
            "params": {},
            "id": "sub-1",
        },
    )
    assert len(called) == 1
    assert called[0]["type"] == "autopilot_unsubscribe"
    assert called[0]["request_id"] == "sub-1"


@pytest.mark.asyncio
async def test_dispatch_request_envelope_missing_method_returns_error() -> None:
    """A ``request`` envelope without a ``method`` field returns an error."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "params": {},
            "id": "req-x",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_dispatch_request_envelope_unknown_method_returns_not_found() -> None:
    """A ``request`` envelope with an unknown method returns -32601."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "nonexistent_method",
            "params": {},
            "id": "req-y",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_dispatch_legacy_flat_message_is_rejected() -> None:
    """Legacy flat-form messages (no envelope) are rejected with METHOD_NOT_FOUND.

    The daemon accepts protocol-1 envelopes only; a flat message like
    ``{"type": "command", "cmd": "/exit"}`` no longer dispatches — clients must
    send the envelope form (e.g. a ``slash_command`` notification).
    """
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "command", "cmd": "/exit"})
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value
    assert msg["error"]["code"] == -32601
    assert msg["error"]["data"]["method"] == "command"


# ---------------------------------------------------------------------------
# Unknown method → -32601 METHOD_NOT_FOUND
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found() -> None:
    """An unrecognized type produces a -32601 METHOD_NOT_FOUND error."""
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "nonexistent_method", "request_id": "r-unk"})
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value
    assert msg["error"]["code"] == -32601
    assert "nonexistent_method" in msg["error"]["message"]
    assert msg.get("id") == "r-unk"
    assert msg["proto"] == "1"


@pytest.mark.asyncio
async def test_unknown_method_without_request_id_omits_id() -> None:
    """Unknown method without request_id omits the id field."""
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "bogus"})
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["error"]["code"] == -32601
    assert "id" not in msg


# ---------------------------------------------------------------------------
# Invalid params → -32602 INVALID_PARAMS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_loop_id_returns_invalid_params() -> None:
    """loop_get without loop_id fails param validation → -32602."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "request", "method": "loop_get", "params": {}, "id": "r-missing"},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == ErrorCode.INVALID_PARAMS.value
    assert msg["error"]["code"] == -32602
    assert msg.get("id") == "r-missing"
    assert "errors" in msg["error"].get("data", {})


@pytest.mark.asyncio
async def test_missing_job_id_returns_invalid_params() -> None:
    """job_status without job_id fails param validation → -32602."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "request", "method": "job_status", "params": {}, "id": "r-job"},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == ErrorCode.INVALID_PARAMS.value
    assert msg["error"]["code"] == -32602
    assert "errors" in msg["error"].get("data", {})
    assert isinstance(msg["error"]["data"]["errors"], list)
    assert len(msg["error"]["data"]["errors"]) > 0


@pytest.mark.asyncio
async def test_missing_auth_credentials_returns_domain_error() -> None:
    """auth without access_key/secret_key passes param validation (fields are
    optional in _AuthParams) and the handler returns its own domain-specific
    ``auth_response`` error rather than a generic -32602."""
    from soothe_daemon.server.auth_handler import AuthHandler

    class _StubIdentity:
        """Identity that never authenticates — handler still checks creds first."""

        def authenticate(self, access_key: str, secret_key: str) -> Any:
            return None

        def refresh_token(self, refresh_token: str) -> Any:
            return None

    router, daemon = _make_router()
    daemon._auth_handler = AuthHandler(_StubIdentity())
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "request", "method": "auth", "params": {}, "id": "r-auth"},
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "response"
    assert msg["result"]["success"] is False
    assert msg["result"]["error"] == "missing_credentials"


@pytest.mark.asyncio
async def test_valid_params_passes_validation_and_reaches_handler() -> None:
    """A message with valid params should reach the handler (not be rejected)."""
    router, daemon = _make_router()

    daemon._persistence_manager = SimpleNamespace(
        get_loop_metadata=AsyncMock(return_value=None),
        get_failed_branches_for_loop=AsyncMock(return_value=[]),
        get_checkpoint_anchors_for_range=AsyncMock(return_value=[]),
    )

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_get",
            "params": {"loop_id": "loop-abc"},
            "id": "r-ok",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    # The handler should produce a LOOP_NOT_FOUND error (not INVALID_PARAMS).
    assert msg["error"]["code"] == ErrorCode.LOOP_NOT_FOUND.value
    assert msg["error"]["code"] == -32200
    assert "loop-abc" in msg["error"]["message"]


# ---------------------------------------------------------------------------
# Error response format consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_responses_have_consistent_wire_format() -> None:
    """All error responses must include proto, type, code, message fields."""
    router, daemon = _make_router()

    # Trigger METHOD_NOT_FOUND (flat-form unknown type is rejected)
    await router.dispatch("client-1", {"type": "nope", "request_id": "r1"})

    # Trigger INVALID_PARAMS (envelope loop_get missing loop_id)
    await router.dispatch(
        "client-2",
        {"proto": "1", "type": "request", "method": "loop_get", "params": {}, "id": "r2"},
    )

    assert len(daemon.sent) == 2

    for _cid, msg in daemon.sent:
        assert msg["proto"] == "1"
        assert msg["type"] == "error"
        assert isinstance(msg["error"]["code"], int)
        assert isinstance(msg["error"]["message"], str)
        assert msg["error"]["code"] < 0  # All error codes are negative


@pytest.mark.asyncio
async def test_method_not_found_error_includes_method_in_data() -> None:
    """METHOD_NOT_FOUND error data contains the method string."""
    router, daemon = _make_router()
    await router.dispatch("client-1", {"type": "frobnicate"})
    _, msg = daemon.sent[0]
    assert msg["error"]["data"]["method"] == "frobnicate"


@pytest.mark.asyncio
async def test_invalid_params_error_includes_errors_list() -> None:
    """INVALID_PARAMS error data contains a list of validation error strings."""
    router, daemon = _make_router()
    await router.dispatch(
        "client-1",
        {"proto": "1", "type": "request", "method": "job_create", "params": {}, "id": "r-jc"},
    )
    _, msg = daemon.sent[0]
    assert "errors" in msg["error"]["data"]
    assert isinstance(msg["error"]["data"]["errors"], list)
    # job_create requires "goal" field
    assert any("goal" in e for e in msg["error"]["data"]["errors"])


# ---------------------------------------------------------------------------
# RpcProtocolError raised in handler → serialized to error envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protocol_error_raised_in_handler_is_serialized() -> None:
    """When a handler raises RpcProtocolError, dispatch serializes it."""
    router, daemon = _make_router()

    async def _raising_handler(self, client_id: Any, msg: dict[str, Any]) -> None:
        raise RpcProtocolError(
            ErrorCode.LOOP_NOT_FOUND,
            "Loop xyz not found",
            data={"loop_id": "xyz"},
        )

    # Monkey-patch one handler to raise RpcProtocolError.
    router._handle_loop_get = _raising_handler.__get__(router)  # type: ignore[method-assign]

    await router.dispatch(
        "client-1",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_get",
            "params": {"loop_id": "xyz"},
            "id": "r-pe",
        },
    )
    assert len(daemon.sent) == 1
    _, msg = daemon.sent[0]
    assert msg["type"] == "error"
    assert msg["error"]["code"] == ErrorCode.LOOP_NOT_FOUND.value
    assert msg["error"]["code"] == -32200
    assert "xyz" in msg["error"]["message"]
    assert msg.get("id") == "r-pe"
    assert msg["error"]["data"]["loop_id"] == "xyz"


# ---------------------------------------------------------------------------
# Static analysis: no if-chain in dispatch()
# ---------------------------------------------------------------------------


def test_dispatch_method_has_no_if_chain() -> None:
    """dispatch() source must not contain ``if msg_type ==`` branches."""
    source = inspect.getsource(MessageRouter.dispatch)
    assert "if msg_type ==" not in source, (
        "dispatch() still contains if-chain branches; use HANDLER_REGISTRY lookup instead"
    )


def test_dispatch_uses_handler_registry() -> None:
    """dispatch() source must reference HANDLER_REGISTRY."""
    source = inspect.getsource(MessageRouter.dispatch)
    assert "HANDLER_REGISTRY" in source


def test_dispatch_uses_build_error_response() -> None:
    """dispatch() source must use build_error_response for error responses."""
    source = inspect.getsource(MessageRouter.dispatch)
    assert "build_error_response" in source
