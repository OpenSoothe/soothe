"""Tests for execute tool filtering when security.sandbox is disabled."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.core.agent.execute_tool_filter import (
    tool_entry_name,
    without_execute_tool_when_sandbox_disabled,
)


def test_tool_entry_name_dict() -> None:
    assert tool_entry_name({"name": "execute"}) == "execute"
    assert tool_entry_name({"foo": 1}) is None


def test_tool_entry_name_mock() -> None:
    m = MagicMock()
    m.name = "glob"
    assert tool_entry_name(m) == "glob"


def test_without_execute_when_sandbox_off() -> None:
    execute = MagicMock(name="execute")
    execute.name = "execute"
    glob = MagicMock(name="glob")
    glob.name = "glob"
    out = without_execute_tool_when_sandbox_disabled(
        [execute, glob], security_sandbox_enabled=False
    )
    assert [tool_entry_name(x) for x in out] == ["glob"]


def test_without_execute_keeps_list_when_sandbox_on() -> None:
    execute = MagicMock(name="execute")
    execute.name = "execute"
    glob = MagicMock(name="glob")
    glob.name = "glob"
    out = without_execute_tool_when_sandbox_disabled([execute, glob], security_sandbox_enabled=True)
    assert len(out) == 2
