"""Unit tests for soothe-nano agent catalog helpers."""

from soothe_nano.agent.subagent_catalog import (
    INTAKE_ONLY_WIRE_SUBAGENTS,
    is_intake_only_wire_subagent,
    partition_subagent_specs,
    spec_subagent_name,
)
from soothe_nano.agent.execute_stream import ephemeral_execute_stream_enabled


def test_intake_only_set_excludes_planner() -> None:
    assert "planner" not in INTAKE_ONLY_WIRE_SUBAGENTS
    assert "explorer" in INTAKE_ONLY_WIRE_SUBAGENTS


def test_partition_subagent_specs_splits_intake_only() -> None:
    specs = [
        {"name": "planner"},
        {"name": "explorer"},
        {"name": "deep_research"},
    ]
    catalog, intake = partition_subagent_specs(specs)
    assert [spec_subagent_name(s) for s in catalog] == ["planner"]
    assert {spec_subagent_name(s) for s in intake} == {"explorer", "deep_research"}


def test_is_intake_only_wire_subagent() -> None:
    assert is_intake_only_wire_subagent("explorer") is True
    assert is_intake_only_wire_subagent("planner") is False
    assert is_intake_only_wire_subagent(None) is False


def test_ephemeral_execute_stream_enabled_default(monkeypatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    assert ephemeral_execute_stream_enabled() is True
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "0")
    assert ephemeral_execute_stream_enabled() is False
