"""Tests for headless daemon worker-subprocess retry."""

from __future__ import annotations

from typing import Any

import pytest

from soothe_cli.cli.execution import daemon as daemon_exec


@pytest.mark.asyncio
async def test_run_headless_retries_once_on_worker_subprocess_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient pool worker exit should trigger one automatic retry."""
    calls: list[int] = []

    async def _fake_session(*_args: Any, **_kwargs: Any) -> tuple[int, bool]:
        calls.append(1)
        if len(calls) == 1:
            return 1, True
        return 0, False

    monkeypatch.setattr(daemon_exec, "_run_headless_session_once", _fake_session)

    code = await daemon_exec.run_headless_via_daemon(object(), "hello")

    assert code == 0
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_headless_does_not_retry_non_worker_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated daemon failures should not loop retries."""
    calls: list[int] = []

    async def _fake_session(*_args: Any, **_kwargs: Any) -> tuple[int, bool]:
        calls.append(1)
        return 1, False

    monkeypatch.setattr(daemon_exec, "_run_headless_session_once", _fake_session)

    code = await daemon_exec.run_headless_via_daemon(object(), "hello")

    assert code == 1
    assert len(calls) == 1
