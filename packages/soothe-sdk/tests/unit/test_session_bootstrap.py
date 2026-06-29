"""Tests for daemon loop session bootstrap (protocol-1 flow, IG-522 Phase 7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe_sdk.client.session import bootstrap_loop_session
from soothe_sdk.client.wire import ProtocolError


class _FakeClient:
    """Fake WebSocketClient recording protocol-1 method calls.

    Mimics the real ``WebSocketClient`` API surface used by
    ``bootstrap_loop_session``: ``request_connection_init``,
    ``wait_for_connection_ack``, ``request``, and ``subscribe``.
    """

    def __init__(self, *, loop_id: str = "loop-created") -> None:
        self.calls: list[tuple[str, Any]] = []
        self._loop_id = loop_id

    async def request_connection_init(self) -> None:
        self.calls.append(("request_connection_init", None))

    async def wait_for_connection_ack(self, *, ack_timeout_s: float) -> dict[str, Any]:
        self.calls.append(("wait_for_connection_ack", ack_timeout_s))
        return {
            "proto": "1",
            "type": "connection_ack",
            "result": {"readiness_state": "ready", "protocol_version": "1"},
        }

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        self.calls.append(("request", method, dict(params or {}), timeout))
        if method == "loop_new":
            return {"loop_id": self._loop_id, "autopilot_mode": "solo"}
        if method == "loop_reattach":
            return {"autopilot_mode": "autopilot"}
        msg = f"unexpected request method {method}"
        raise AssertionError(msg)

    async def subscribe(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> str:
        self.calls.append(("subscribe", method, dict(params or {}), timeout))
        return "sub-1"


@pytest.mark.asyncio
async def test_bootstrap_new_loop_uses_protocol1_request_and_subscribe(tmp_path: Path) -> None:
    """Fresh session issues ``request('loop_new')`` then ``subscribe('loop_events')``."""
    client = _FakeClient()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        workspace=str(workspace),
    )

    assert result.get("loop_id") == "loop-created"
    assert result.get("success") is True

    # Handshake
    assert ("request_connection_init", None) in client.calls
    assert any(c[0] == "wait_for_connection_ack" for c in client.calls)

    # loop_new via request()
    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][1] == "loop_new"
    # RFC-450 §10.1: field renamed from ``client_workspace`` to ``workspace``.
    assert reqs[0][2].get("workspace") == str(workspace)
    assert "client_workspace" not in reqs[0][2]

    # subscribe via subscribe() — not request_response()
    subs = [c for c in client.calls if c[0] == "subscribe"]
    assert len(subs) == 1
    assert subs[0][1] == "loop_events"
    assert subs[0][2].get("loop_id") == "loop-created"
    # Verbosity is owned by the daemon — clients never send it.
    assert "verbosity" not in subs[0][2]
    # IG-441: ``adaptive`` is the bootstrap default — best UX for most clients.
    assert subs[0][2].get("stream_delivery") == "adaptive"
    # Protocol-1 includes ``wire_tier`` in the subscription params.
    assert subs[0][2].get("wire_tier") == "full"


@pytest.mark.asyncio
async def test_bootstrap_new_loop_omits_workspace_when_none() -> None:
    """No ``workspace`` field is sent when caller passes ``None`` (IG-409)."""
    client = _FakeClient()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        workspace=None,
    )

    assert result.get("loop_id") == "loop-created"
    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][1] == "loop_new"
    assert "workspace" not in reqs[0][2]
    assert "client_workspace" not in reqs[0][2]


@pytest.mark.asyncio
async def test_bootstrap_resume_loop_uses_reattach_then_subscribe(tmp_path: Path) -> None:
    """Resuming an existing loop issues ``request('loop_reattach')`` then ``subscribe``."""
    client = _FakeClient()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id="loop-existing",
        workspace=str(tmp_path),
    )

    assert result.get("loop_id") == "loop-existing"

    # Should NOT call request('loop_new')
    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][1] == "loop_reattach"
    assert reqs[0][2].get("loop_id") == "loop-existing"

    # Should still subscribe
    subs = [c for c in client.calls if c[0] == "subscribe"]
    assert len(subs) == 1
    assert subs[0][1] == "loop_events"
    assert subs[0][2].get("loop_id") == "loop-existing"
    assert subs[0][2].get("stream_delivery") == "adaptive"


@pytest.mark.asyncio
async def test_bootstrap_loop_new_protocol_error_propagates() -> None:
    """A ``ProtocolError`` from ``loop_new`` must propagate (bootstrap fails)."""

    class _ErrorClient(_FakeClient):
        async def request(
            self, method: str, params: Any = None, *, timeout: float = 5.0
        ) -> dict[str, Any]:
            if method == "loop_new":
                raise ProtocolError(code=-32602, message="invalid params")
            return await super().request(method, params, timeout=timeout)

    client = _ErrorClient()
    with pytest.raises(ProtocolError):
        await bootstrap_loop_session(client, resume_loop_id=None)


@pytest.mark.asyncio
async def test_bootstrap_subscribe_protocol_error_propagates() -> None:
    """A ``ProtocolError`` from ``subscribe`` must propagate (bootstrap fails)."""

    class _ErrorClient(_FakeClient):
        async def subscribe(self, method: str, params: Any = None, *, timeout: float = 5.0) -> str:
            raise ProtocolError(code=-32602, message="subscription rejected")

    client = _ErrorClient()
    with pytest.raises(ProtocolError):
        await bootstrap_loop_session(client, resume_loop_id=None)


@pytest.mark.asyncio
async def test_bootstrap_reattach_failure_is_non_fatal() -> None:
    """A ``ProtocolError`` from ``loop_reattach`` logs and continues (graceful degrade)."""

    class _ReattachErrorClient(_FakeClient):
        async def request(
            self, method: str, params: Any = None, *, timeout: float = 5.0
        ) -> dict[str, Any]:
            if method == "loop_reattach":
                raise ProtocolError(code=-32601, message="loop not found")
            return await super().request(method, params, timeout=timeout)

    client = _ReattachErrorClient()
    # Should NOT raise — reattach failure is non-fatal.
    result = await bootstrap_loop_session(client, resume_loop_id="loop-gone")
    assert result.get("loop_id") == "loop-gone"
    # Subscription should still proceed.
    subs = [c for c in client.calls if c[0] == "subscribe"]
    assert len(subs) == 1


@pytest.mark.asyncio
async def test_bootstrap_forwards_user_id_and_ephemeral() -> None:
    """``user_id`` and ``is_ephemeral`` are forwarded in ``loop_new`` params."""
    client = _FakeClient()

    await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        user_id="alice",
        is_ephemeral=True,
    )

    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][2].get("user_id") == "alice"
    assert reqs[0][2].get("is_ephemeral") is True


@pytest.mark.asyncio
async def test_bootstrap_workspace_mapping_stored_on_client(tmp_path: Path) -> None:
    """RFC-621: workspace mapping from ``loop_new`` is stored on the client."""

    class _MappingClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.workspace_mapping = None  # type: ignore[assignment]

        async def request(
            self, method: str, params: Any = None, *, timeout: float = 5.0
        ) -> dict[str, Any]:
            if method == "loop_new":
                return {
                    "loop_id": "loop-mapped",
                    "workspace_mapping": {
                        "host_root": "/host",
                        "container_root": "/container",
                    },
                }
            return await super().request(method, params, timeout=timeout)

    client = _MappingClient()
    result = await bootstrap_loop_session(client, resume_loop_id=None)

    assert result.get("loop_id") == "loop-mapped"
    assert result.get("workspace_mapping", {}).get("host_root") == "/host"
    assert client.workspace_mapping is not None
