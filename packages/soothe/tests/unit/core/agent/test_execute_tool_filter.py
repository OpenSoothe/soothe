"""Tests for soothe_deepagents execute tool removal."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_deepagents.backends import FilesystemBackend
from soothe_deepagents.middleware.filesystem import FilesystemMiddleware

from soothe.foundation.core.agent._execute_filter import (
    apply_execute_tool_removal_patch,
    tool_entry_name,
    without_deepagents_execute_tool,
)


def test_tool_entry_name_dict() -> None:
    assert tool_entry_name({"name": "execute"}) == "execute"
    assert tool_entry_name({"foo": 1}) is None


def test_tool_entry_name_mock() -> None:
    m = MagicMock()
    m.name = "glob"
    assert tool_entry_name(m) == "glob"


def test_without_deepagents_execute_tool() -> None:
    execute = MagicMock(name="execute")
    execute.name = "execute"
    glob = MagicMock(name="glob")
    glob.name = "glob"
    out = without_deepagents_execute_tool([execute, glob])
    assert [tool_entry_name(x) for x in out] == ["glob"]


def test_filesystem_middleware_patch_strips_execute(tmp_path) -> None:
    apply_execute_tool_removal_patch()
    middleware = FilesystemMiddleware(backend=FilesystemBackend(root_dir=tmp_path))
    tool_names = {t.name for t in middleware.tools}
    assert "execute" not in tool_names
    assert {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}.issubset(tool_names)
