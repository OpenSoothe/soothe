"""Tests for ephemeral execute-stream env gate."""

from __future__ import annotations

import pytest

from soothe_nano.agent.core_agent import ephemeral_execute_stream_enabled


def test_ephemeral_execute_stream_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    assert ephemeral_execute_stream_enabled() is True


def test_ephemeral_execute_stream_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "0")
    assert ephemeral_execute_stream_enabled() is False
