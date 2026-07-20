"""Unit tests for ProgressiveMCPRegistry."""

from langchain_core.tools import StructuredTool

from soothe_nano.mcp.mcp_progressive import (
    ProgressiveMCPRegistry,
    merge_mcp_activation,
)
from soothe_nano.mcp.mcp_utils import MCPToolDescriptor


def _descriptor(name: str, *, essential: bool = False) -> MCPToolDescriptor:
    return MCPToolDescriptor(
        name=name,
        bare_name=name.split("__")[-1],
        description=f"desc for {name}",
        server="github",
        is_essential=essential,
    )


def test_merge_mcp_activation_unions_sets() -> None:
    left = {"sent": {"a"}, "promoted": {"b"}}
    right = {"sent": {"c"}, "promoted": {"d"}}
    merged = merge_mcp_activation(left, right)
    assert merged["sent"] == {"a", "c"}
    assert merged["promoted"] == {"b", "d"}


def test_new_for_thread_excludes_sent_and_promoted() -> None:
    reg = ProgressiveMCPRegistry(always_loaded_names=frozenset({"mcp__core__tool"}))
    activation = {"sent": {"mcp__gh__a"}, "promoted": {"mcp__gh__b"}}
    deferred = [
        _descriptor("mcp__gh__a"),
        _descriptor("mcp__gh__b"),
        _descriptor("mcp__gh__c"),
    ]
    new = reg.new_for_thread(activation, deferred)
    assert [d.name for d in new] == ["mcp__gh__c"]


def test_search_deferred_substring_match() -> None:
    reg = ProgressiveMCPRegistry()
    deferred = [
        _descriptor("mcp__gh__create_issue"),
        _descriptor("mcp__fs__read_file"),
    ]
    matches = reg.search_deferred("create", deferred, limit=5)
    assert len(matches) == 1
    assert matches[0].name == "mcp__gh__create_issue"


def test_bound_tools_filters_deferred_until_promoted() -> None:
    reg = ProgressiveMCPRegistry(always_loaded_names=frozenset({"mcp__core__always"}))
    core_tool = StructuredTool.from_function(
        func=lambda: "ok",
        name="mcp__core__always",
        description="core",
    )
    deferred_tool = StructuredTool.from_function(
        func=lambda: "ok",
        name="mcp__gh__deferred",
        description="deferred",
    )
    builtin = StructuredTool.from_function(
        func=lambda: "ok",
        name="read_file",
        description="read",
    )
    activation = {"sent": set(), "promoted": set()}
    bound = reg.bound_tools([builtin, core_tool, deferred_tool], activation)
    names = {t.name for t in bound}
    assert names == {"read_file", "mcp__core__always"}

    reg.mark_promoted(activation, ["mcp__gh__deferred"])
    bound2 = reg.bound_tools([builtin, core_tool, deferred_tool], activation)
    assert "mcp__gh__deferred" in {t.name for t in bound2}


def test_bound_tools_respects_disabled_server() -> None:
    reg = ProgressiveMCPRegistry(always_loaded_names=frozenset())
    tool = StructuredTool.from_function(
        func=lambda: "ok",
        name="mcp__github__create_issue",
        description="x",
    )
    activation = {"sent": set(), "promoted": {"mcp__github__create_issue"}}
    bound = reg.bound_tools([tool], activation, disabled_servers={"github"})
    assert bound == []
