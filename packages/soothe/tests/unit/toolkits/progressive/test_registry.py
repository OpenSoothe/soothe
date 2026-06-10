"""Tests for ProgressiveToolRegistry."""

from __future__ import annotations

from soothe.toolkits.progressive.registry import ProgressiveToolRegistry, ToolDescriptor


def _desc(name: str) -> ToolDescriptor:
    return ToolDescriptor(name=name, description=f"desc-{name}")


def test_partition_core_and_deferred() -> None:
    registry = ProgressiveToolRegistry(core_tools=["run_command", "read_file"])
    descriptors = [_desc("run_command"), _desc("wizsearch_search"), _desc("read_file")]
    core, deferred = registry.partition(descriptors)
    assert {d.name for d in core} == {"run_command", "read_file"}
    assert {d.name for d in deferred} == {"wizsearch_search"}


def test_bound_tool_names_includes_promoted() -> None:
    registry = ProgressiveToolRegistry(core_tools=["run_command"])
    activation = {"sent": set(), "promoted": {"wizsearch_search"}}
    assert registry.bound_tool_names(activation) == {"run_command", "wizsearch_search"}


def test_new_for_thread_excludes_sent_and_promoted() -> None:
    registry = ProgressiveToolRegistry(core_tools=["run_command"])
    activation = {"sent": {"data_tool"}, "promoted": {"http_get"}}
    deferred = [_desc("data_tool"), _desc("http_get"), _desc("wizsearch_search")]
    new = registry.new_for_thread(activation, deferred)
    assert [d.name for d in new] == ["wizsearch_search"]
