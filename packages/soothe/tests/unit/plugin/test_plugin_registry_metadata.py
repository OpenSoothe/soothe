"""Tests for PluginRegistry RFC-210 metadata accessors (IG-194)."""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import Manifest

from soothe.plugin.registry import PluginRegistry


def _minimal_manifest(name: str = "test-plugin") -> Manifest:
    return Manifest(name=name, version="1.0.0", description="test")


def test_get_tool_metadata_matches_decorated_tool() -> None:
    reg = PluginRegistry()
    reg.register(_minimal_manifest(), "built-in")
    entry = reg.get("test-plugin")
    assert entry is not None

    class _Tool:
        _tool_name = "alpha"
        _tool_triggers = ["WORKSPACE"]
        _tool_system_context = "<tool-ctx/>"

    entry.tools = [_Tool()]
    meta = reg.get_tool_metadata("alpha")
    assert meta == {"triggers": ["WORKSPACE"], "system_context": "<tool-ctx/>"}


def test_get_tool_metadata_langchain_like_uses_wrapped_func() -> None:
    reg = PluginRegistry()
    reg.register(_minimal_manifest(), "built-in")
    entry = reg.get("test-plugin")
    assert entry is not None

    class _Inner:
        _tool_triggers = ["SEC"]
        _tool_system_context = None

    class _FakeTool:
        name = "glob"
        func: Any = _Inner()

    entry.tools = [_FakeTool()]
    assert reg.get_tool_metadata("glob") == {"triggers": ["SEC"]}


def test_get_tool_metadata_unknown_returns_none() -> None:
    reg = PluginRegistry()
    reg.register(_minimal_manifest(), "built-in")
    assert reg.get_tool_metadata("nonexistent") is None


def test_get_subagent_metadata_from_factory() -> None:
    reg = PluginRegistry()
    reg.register(_minimal_manifest(), "built-in")
    entry = reg.get("test-plugin")
    assert entry is not None

    class _Factory:
        _subagent_name = "claude"
        _subagent_triggers = ["THREAD"]
        _subagent_system_context = "<sub/>"

    entry.subagents = [_Factory()]
    meta = reg.get_subagent_metadata("claude")
    assert meta == {"triggers": ["THREAD"], "system_context": "<sub/>"}


def test_get_subagent_metadata_unknown_returns_none() -> None:
    reg = PluginRegistry()
    reg.register(_minimal_manifest(), "built-in")
    assert reg.get_subagent_metadata("nope") is None
