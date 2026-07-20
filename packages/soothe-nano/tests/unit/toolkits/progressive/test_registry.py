"""Tests for ProgressiveToolRegistry."""

from __future__ import annotations

from soothe_nano.toolkits.progressive.registry import (
    DEFAULT_CORE_TOOL_NAMES,
    ProgressiveToolRegistry,
    ToolDescriptor,
    merge_tool_activation,
    snapshot_tool_activation,
)


def _desc(name: str) -> ToolDescriptor:
    return ToolDescriptor(name=name, description=f"desc-{name}")


def test_default_core_includes_surgical_file_ops() -> None:
    assert {"apply_diff", "file_info"}.issubset(DEFAULT_CORE_TOOL_NAMES)
    assert {"run_background", "tail_background_log", "kill_process"}.issubset(
        DEFAULT_CORE_TOOL_NAMES
    )
    assert {"search_skills", "invoke_skill"}.issubset(DEFAULT_CORE_TOOL_NAMES)
    assert {"search_mcp_tools", "mcp_resources_list", "mcp_resources_read"}.issubset(
        DEFAULT_CORE_TOOL_NAMES
    )
    assert len(DEFAULT_CORE_TOOL_NAMES) == 26


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


def test_merge_tool_activation_unions_sets() -> None:
    left = {"sent": {"a"}, "promoted": {"b"}}
    right = {"sent": {"c"}, "promoted": {"d"}}
    merged = merge_tool_activation(left, right)
    assert merged["sent"] == {"a", "c"}
    assert merged["promoted"] == {"b", "d"}


def test_snapshot_tool_activation_copies_sets() -> None:
    activation = {"sent": {"x"}, "promoted": {"y"}}
    snap = snapshot_tool_activation(activation)
    activation["sent"].add("z")
    assert snap["sent"] == {"x"}
    assert snap["promoted"] == {"y"}
