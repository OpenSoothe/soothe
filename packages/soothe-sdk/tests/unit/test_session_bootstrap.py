"""Tests for daemon thread bootstrap workspace propagation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe_sdk.client.session import bootstrap_thread_session


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._events: list[dict[str, Any]] = [{"type": "status", "thread_id": "thread-1"}]

    async def request_daemon_ready(self) -> None:
        self.calls.append(("request_daemon_ready", None))

    async def wait_for_daemon_ready(self, *, ready_timeout_s: float) -> None:
        self.calls.append(("wait_for_daemon_ready", ready_timeout_s))

    async def send_new_thread(self, workspace: str | None = None) -> None:
        self.calls.append(("send_new_thread", workspace))

    async def send_resume_thread(self, thread_id: str, workspace: str | None = None) -> None:
        self.calls.append(("send_resume_thread", (thread_id, workspace)))

    async def read_event(self) -> dict[str, Any]:
        return self._events.pop(0)

    async def subscribe_thread(self, thread_id: str, *, verbosity: str) -> None:
        self.calls.append(("subscribe_thread", (thread_id, verbosity)))

    async def wait_for_subscription_confirmed(
        self,
        thread_id: str,
        *,
        verbosity: str,
        timeout: float,
    ) -> None:
        self.calls.append(("wait_for_subscription_confirmed", (thread_id, verbosity, timeout)))


@pytest.mark.asyncio
async def test_bootstrap_new_thread_uses_workspace_override(tmp_path: Path) -> None:
    """Explicit workspace is forwarded to ``new_thread``."""
    client = _FakeClient()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    await bootstrap_thread_session(
        client,
        resume_thread_id=None,
        verbosity="normal",
        workspace=str(workspace),
    )

    assert ("send_new_thread", str(workspace)) in client.calls


@pytest.mark.asyncio
async def test_bootstrap_resume_thread_uses_workspace_override(tmp_path: Path) -> None:
    """Explicit workspace is forwarded to ``resume_thread``."""
    client = _FakeClient()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    await bootstrap_thread_session(
        client,
        resume_thread_id="thread-1",
        verbosity="normal",
        workspace=str(workspace),
    )

    assert ("send_resume_thread", ("thread-1", str(workspace))) in client.calls
