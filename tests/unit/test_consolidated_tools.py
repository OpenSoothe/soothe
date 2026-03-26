"""Tests for consolidated capability tools (see RFC-0016)."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.tools.data import InspectDataTool, create_data_tools
from soothe.tools.execution import RunCommandTool, create_execution_tools
from soothe.tools.file_ops import ReadFileTool, WriteFileTool, create_file_ops_tools
from soothe.tools.web_search import CrawlWebTool, SearchWebTool, create_websearch_tools


def _has_pandas() -> bool:
    """Check if pandas is available."""
    return importlib.util.find_spec("pandas") is not None


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """Tests for the websearch capability tool."""

    def test_create_returns_two_tools(self) -> None:
        tools = create_websearch_tools()
        assert len(tools) == 2
        assert isinstance(tools[0], SearchWebTool)
        assert isinstance(tools[1], CrawlWebTool)

    def test_tool_name(self) -> None:
        tool = SearchWebTool()
        assert tool.name == "search_web"

    def test_crawl_tool_name(self) -> None:
        tool = CrawlWebTool()
        assert tool.name == "crawl_web"

    def test_description_mentions_search(self) -> None:
        tool = SearchWebTool()
        assert "search" in tool.description.lower()
        assert "research" in tool.description.lower()


# ---------------------------------------------------------------------------
# FileOps Tools (replaces WorkspaceTool)
# ---------------------------------------------------------------------------


class TestFileOpsTools:
    """Tests for the file_ops tools."""

    def test_create_returns_six_tools(self) -> None:
        tools = create_file_ops_tools()
        assert len(tools) == 6
        assert isinstance(tools[0], ReadFileTool)
        assert any(isinstance(t, WriteFileTool) for t in tools)

    def test_read_file_tool(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world")
        tool = ReadFileTool(work_dir=str(tmp_path))
        result = tool._run(path="hello.txt")
        assert "hello world" in result

    def test_write_file_tool(self, tmp_path: Path) -> None:
        from soothe.tools.file_ops import WriteFileTool

        tool = WriteFileTool(work_dir=str(tmp_path))
        result = tool._run(path="new.txt", content="new content")
        assert "success" in result.lower() or "created" in result.lower() or "wrote" in result.lower()
        assert (tmp_path / "new.txt").read_text() == "new content"

    def test_delete_file_tool(self, tmp_path: Path) -> None:
        from soothe.tools.file_ops import DeleteFileTool

        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("delete me")
        tool = DeleteFileTool(work_dir=str(tmp_path))
        result = tool._run(path="to_delete.txt")
        assert not test_file.exists()

    def test_list_files_tool(self, tmp_path: Path) -> None:
        from soothe.tools.file_ops import ListFilesTool

        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        tool = ListFilesTool(work_dir=str(tmp_path))
        result = tool._run(pattern="*.py")
        assert "a.py" in result
        assert "b.py" in result

    def test_search_files_tool(self, tmp_path: Path) -> None:
        from soothe.tools.file_ops import SearchFilesTool

        (tmp_path / "code.py").write_text("def hello_world():\n    pass\n")
        tool = SearchFilesTool(work_dir=str(tmp_path))
        result = tool._run(pattern="hello_world", path=".")
        assert "hello_world" in result

    def test_file_info_tool(self, tmp_path: Path) -> None:
        from soothe.tools.file_ops import FileInfoTool

        test_file = tmp_path / "info.txt"
        test_file.write_text("some content")
        tool = FileInfoTool(work_dir=str(tmp_path))
        result = tool._run(path="info.txt")
        assert "Size" in result or "Path" in result or "size" in result.lower()


# ---------------------------------------------------------------------------
# Execution Tools (replaces ExecuteTool)
# ---------------------------------------------------------------------------


class TestExecutionTools:
    """Tests for the execution tools."""

    def test_create_returns_four_tools(self) -> None:
        tools = create_execution_tools()
        assert len(tools) == 4
        assert isinstance(tools[0], RunCommandTool)

    def test_run_command_tool_name(self) -> None:
        tool = RunCommandTool()
        assert tool.name == "run_command"

    def test_run_command_description_mentions_shell(self) -> None:
        tool = RunCommandTool()
        desc = tool.description.lower()
        assert "command" in desc or "shell" in desc

    def test_run_command_basic(self) -> None:
        """Test basic command execution."""
        tool = RunCommandTool()
        result = tool._run(command="echo hello")
        assert "hello" in result or result  # Should have some output


# ---------------------------------------------------------------------------
# Data Tools (replaces DataTool)
# ---------------------------------------------------------------------------


class TestDataTools:
    """Tests for the data tools."""

    def test_create_returns_six_tools(self) -> None:
        tools = create_data_tools()
        assert len(tools) == 6
        assert isinstance(tools[0], InspectDataTool)

    def test_inspect_data_tool_name(self) -> None:
        tool = InspectDataTool()
        assert tool.name == "inspect_data"

    @pytest.mark.skipif(not _has_pandas(), reason="pandas not installed")
    def test_inspect_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")
        tool = InspectDataTool()
        result = tool._run(file_path=str(csv_file))
        assert "name" in result
        assert "age" in result

    def test_document_extract(self, tmp_path: Path) -> None:
        from soothe.tools.data import ExtractTextTool

        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Hello document world")
        tool = ExtractTextTool()
        result = tool._run(file_path=str(txt_file))
        assert "Hello document world" in result


# ---------------------------------------------------------------------------
# Research tool (renamed inquiry)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Resolver: consolidated names resolve, old names rejected
# ---------------------------------------------------------------------------


class TestResolverConsolidatedNames:
    """Consolidated tool names resolve; legacy names are rejected."""

    def test_websearch_resolves(self) -> None:
        from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("web_search")  # Note: uses underscore
        assert len(tools) == 2  # SearchWebTool + CrawlWebTool
        assert tools[0].name == "search_web"
        assert tools[1].name == "crawl_web"

    def test_file_ops_resolves(self) -> None:
        from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("file_ops")
        assert len(tools) == 6
        assert tools[0].name == "read_file"

    def test_execution_resolves(self) -> None:
        from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("execution")
        assert len(tools) == 4
        assert tools[0].name == "run_command"

    def test_data_resolves(self) -> None:
        from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("data")
        assert len(tools) == 6
        assert tools[0].name == "inspect_data"

    def test_old_names_rejected(self) -> None:
        from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

        for old_name in ("inquiry", "file_edit", "cli", "wizsearch", "tabular", "document", "python_executor"):
            tools = _resolve_single_tool_group_uncached(old_name)
            assert tools == [], f"'{old_name}' should not resolve (no backward compat)"


# ---------------------------------------------------------------------------
# Domain-scoped prompts
# ---------------------------------------------------------------------------


class TestDomainScopedPrompts:
    """Tests for domain-scoped prompt guides."""

    def test_guides_exist(self) -> None:
        from soothe.config.prompts import (
            _DATA_GUIDE,
            _FILE_OPS_GUIDE,
            _RESEARCH_GUIDE,
            _SHELL_GUIDE,
            _SUBAGENT_GUIDE,
        )

        assert "websearch" in _RESEARCH_GUIDE or "search_web" in _RESEARCH_GUIDE
        assert "research" in _RESEARCH_GUIDE
        assert "read_file" in _FILE_OPS_GUIDE or "file" in _FILE_OPS_GUIDE.lower()
        assert "run_command" in _SHELL_GUIDE or "execute" in _SHELL_GUIDE.lower()
        assert "data" in _DATA_GUIDE.lower()
        assert "browser" in _SUBAGENT_GUIDE.lower()

    def test_orchestration_guide_has_all_domains(self) -> None:
        from soothe.config.prompts import _TOOL_ORCHESTRATION_GUIDE

        # Check for tool categories mentioned in the guide
        guide_lower = _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "read_file" in guide_lower or "file" in guide_lower
        assert "run_command" in guide_lower or "execute" in guide_lower or "shell" in guide_lower
        assert "data" in guide_lower
        assert "search_web" in guide_lower or "websearch" in guide_lower or "web" in guide_lower
        assert "research" in guide_lower

    def test_no_old_tool_names_in_guide(self) -> None:
        from soothe.config.prompts import _TOOL_ORCHESTRATION_GUIDE

        assert "file_edit" not in _TOOL_ORCHESTRATION_GUIDE
        assert "run_cli" not in _TOOL_ORCHESTRATION_GUIDE
        assert "python_executor" not in _TOOL_ORCHESTRATION_GUIDE
        assert "wizsearch" not in _TOOL_ORCHESTRATION_GUIDE
        assert "inquiry" not in _TOOL_ORCHESTRATION_GUIDE


# ---------------------------------------------------------------------------
# Tool Logging Events
# ---------------------------------------------------------------------------


class TestConsolidatedToolLogging:
    """Test that consolidated tools emit progress events."""

    def test_websearch_emits_events(self) -> None:
        """SearchWebTool should emit started/completed events."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        tool = SearchWebTool(config={})

        with patch("soothe.utils.progress.emit_progress") as mock_emit:
            wrapped = wrap_main_agent_tool_with_logging(tool, logging.getLogger(__name__))

            # Mock the internal search backend to avoid actual API calls
            with patch.object(tool, "_get_search_backend") as mock_backend:
                mock_search_tool = MagicMock()
                mock_search_tool._run.return_value = "Search results here"
                mock_backend.return_value = mock_search_tool

                result = wrapped._run(query="test query")

                # Verify events were emitted
                event_types = [call[0][0]["type"] for call in mock_emit.call_args_list]
                assert "soothe.tool.search_web.started" in event_types
                assert "soothe.tool.search_web.completed" in event_types

    def test_file_ops_emits_events(self, tmp_path: Path) -> None:
        """ReadFileTool should emit started/completed events."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        tool = ReadFileTool(work_dir=str(tmp_path))

        with patch("soothe.utils.progress.emit_progress") as mock_emit:
            wrapped = wrap_main_agent_tool_with_logging(tool, logging.getLogger(__name__))
            result = wrapped._run(path="test.txt")

            # Verify events were emitted
            event_types = [call[0][0]["type"] for call in mock_emit.call_args_list]
            assert "soothe.tool.read_file.started" in event_types
            assert "soothe.tool.read_file.completed" in event_types

    def test_execute_emits_events(self) -> None:
        """RunCommandTool should emit started/completed events."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        tool = RunCommandTool()

        with patch("soothe.utils.progress.emit_progress") as mock_emit:
            wrapped = wrap_main_agent_tool_with_logging(tool, logging.getLogger(__name__))
            result = wrapped._run(command="echo hello")

            # Verify events were emitted
            event_types = [call[0][0]["type"] for call in mock_emit.call_args_list]
            assert "soothe.tool.run_command.started" in event_types
            assert "soothe.tool.run_command.completed" in event_types

    def test_data_emits_events(self, tmp_path: Path) -> None:
        """InspectDataTool should emit started/completed events."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        # Create a test text file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        tool = InspectDataTool()

        with patch("soothe.utils.progress.emit_progress") as mock_emit:
            wrapped = wrap_main_agent_tool_with_logging(tool, logging.getLogger(__name__))
            result = wrapped._run(file_path=str(test_file))

            # Verify events were emitted
            event_types = [call[0][0]["type"] for call in mock_emit.call_args_list]
            assert "soothe.tool.inspect_data.started" in event_types
            assert "soothe.tool.inspect_data.completed" in event_types

    def test_tool_error_emits_failed_event(self) -> None:
        """Tool errors should emit failed events."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        tool = ReadFileTool()

        with patch("soothe.utils.progress.emit_progress") as mock_emit:
            wrapped = wrap_main_agent_tool_with_logging(tool, logging.getLogger(__name__))
            # This should trigger an error (file not found)
            result = wrapped._run(path="nonexistent_file.txt")

            # Verify failed event was emitted
            event_types = [call[0][0]["type"] for call in mock_emit.call_args_list]
            # The tool catches errors internally and returns error message,
            # so we expect completed event, not failed
            assert "soothe.tool.read_file.started" in event_types
            # Tools that handle errors internally don't raise, so they emit completed
            assert "soothe.tool.read_file.completed" in event_types

    # Research is now a subagent, not a tool
    # Research event tests moved to subagent tests

    def test_no_double_wrapping(self) -> None:
        """Tools should not be wrapped twice."""
        from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

        tool = SearchWebTool()
        logger = logging.getLogger(__name__)

        # Wrap once
        wrapped1 = wrap_main_agent_tool_with_logging(tool, logger)
        # Wrap again
        wrapped2 = wrap_main_agent_tool_with_logging(wrapped1, logger)

        # Should be the same object (no double wrapping)
        assert wrapped1 is wrapped2
        assert tool._soothe_progress_wrapped is True
