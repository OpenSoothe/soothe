"""Tests for daemon loop session bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe_sdk.client.session import bootstrap_loop_session


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def request_daemon_ready(self) -> None:
        self.calls.append(("request_daemon_ready", None))

    async def wait_for_daemon_ready(self, *, ready_timeout_s: float) -> None:
        self.calls.append(("wait_for_daemon_ready", ready_timeout_s))

    async def request_response(
        self,
        payload: dict[str, Any],
        *,
        response_type: str,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(("request_response", dict(payload), response_type, timeout))
        req_id = payload.get("request_id")
        if payload.get("type") == "loop_new":
            return {"type": "loop_new_response", "loop_id": "loop-created", "request_id": req_id}
        if payload.get("type") == "loop_subscribe":
            return {"type": "loop_subscribe_response", "success": True, "request_id": req_id}
        msg = f"unexpected request {payload.get('type')}"
        raise AssertionError(msg)


@pytest.mark.asyncio
async def test_bootstrap_new_loop_allocates_and_subscribes(tmp_path: Path) -> None:
    """Fresh session issues ``loop_new`` then ``loop_subscribe``."""
    client = _FakeClient()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        verbosity="normal",
        workspace=str(workspace),
    )

    assert result.get("loop_id") == "loop-created"
    assert result.get("success") is True
    rr = [c for c in client.calls if c[0] == "request_response"]
    assert len(rr) == 2
    assert rr[0][1]["type"] == "loop_new"
    # IG-409: client workspace must be forwarded to the daemon on loop_new so the
    # agent's filesystem tools default to the user's CWD, not the per-loop scratch dir.
    assert rr[0][1]["workspace"] == str(workspace)
    assert rr[1][1]["type"] == "loop_subscribe"
    assert rr[1][1]["loop_id"] == "loop-created"
    assert rr[1][1]["verbosity"] == "normal"


@pytest.mark.asyncio
async def test_bootstrap_new_loop_omits_workspace_when_none() -> None:
    """No ``workspace`` field is sent when caller passes ``None`` (IG-409)."""
    client = _FakeClient()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        verbosity="normal",
        workspace=None,
    )

    assert result.get("loop_id") == "loop-created"
    rr = [c for c in client.calls if c[0] == "request_response"]
    loop_new_payload = rr[0][1]
    assert loop_new_payload["type"] == "loop_new"
    assert "workspace" not in loop_new_payload


@pytest.mark.asyncio
async def test_bootstrap_resume_loop_subscribes_only(tmp_path: Path) -> None:
    """Resuming an existing loop skips ``loop_new``."""
    client = _FakeClient()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    result = await bootstrap_loop_session(
        client,
        resume_loop_id="loop-existing",
        verbosity="normal",
        workspace=str(workspace),
    )

    assert result.get("loop_id") == "loop-existing"
    rr = [c for c in client.calls if c[0] == "request_response"]
    assert len(rr) == 1
    assert rr[0][1]["type"] == "loop_subscribe"
    assert rr[0][1]["loop_id"] == "loop-existing"
    assert rr[0][1]["verbosity"] == "normal"
