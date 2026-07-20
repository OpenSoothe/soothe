"""Unit tests for soothe-nano agent catalog helpers."""

from soothe_nano.agent.core_agent import ephemeral_execute_stream_enabled
from soothe_nano.agent.subagent_catalog import spec_subagent_name


def test_spec_subagent_name_from_dict() -> None:
    assert spec_subagent_name({"name": "planner"}) == "planner"
    assert spec_subagent_name({"name": "  "}) is None
    assert spec_subagent_name({}) is None


def test_spec_subagent_name_from_object() -> None:
    assert spec_subagent_name(type("S", (), {"name": "explorer"})()) == "explorer"
    assert spec_subagent_name(type("S", (), {"name": None})()) is None


def test_ephemeral_execute_stream_enabled_default(monkeypatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    assert ephemeral_execute_stream_enabled() is True
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "0")
    assert ephemeral_execute_stream_enabled() is False
