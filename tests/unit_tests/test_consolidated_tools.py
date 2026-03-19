"""Tests for RFC-0014 consolidated capability tools."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from soothe.tools.data import DataTool, create_data_tools
from soothe.tools.execute import ExecuteTool, create_execute_tools
from soothe.tools.websearch import WebSearchTool, create_websearch_tools
from soothe.tools.workspace import WorkspaceTool, create_workspace_tools


def _has_pandas() -> bool:
    """Check if pandas is available."""
    return importlib.util.find_spec("pandas") is not None


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """Tests for the websearch capability tool."""

    def test_create_returns_single_tool(self) -> None:
        tools = create_websearch_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], WebSearchTool)

    def test_tool_name(self) -> None:
        tool = WebSearchTool()
        assert tool.name == "websearch"

    def test_description_mentions_search(self) -> None:
        tool = WebSearchTool()
        assert "search" in tool.description.lower()
        assert "research" in tool.description.lower()


# ---------------------------------------------------------------------------
# WorkspaceTool
# ---------------------------------------------------------------------------


class TestWorkspaceTool:
    """Tests for the workspace capability tool."""

    def test_create_returns_single_tool(self) -> None:
        tools = create_workspace_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], WorkspaceTool)

    def test_tool_name(self) -> None:
        tool = WorkspaceTool()
        assert tool.name == "workspace"

    def test_unknown_action(self) -> None:
        tool = WorkspaceTool()
        result = tool._run(action="fly")
        assert "Error" in result
        assert "Unknown action" in result

    def test_read_action(self, tmp_path: Path) -> None:
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="read", path="hello.txt")
        assert "hello world" in result

    def test_write_action(self, tmp_path: Path) -> None:
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="write", path="new.txt", content="new content")
        assert "Created" in result
        assert (tmp_path / "new.txt").read_text() == "new content"

    def test_delete_action(self, tmp_path: Path) -> None:
        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("delete me")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="delete", path="to_delete.txt")
        assert "Deleted" in result
        assert not test_file.exists()

    def test_list_action(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="list", pattern="*.py")
        assert "a.py" in result
        assert "b.py" in result

    def test_search_action(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("def hello_world():\n    pass\n")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="search", pattern="hello_world")
        assert "hello_world" in result

    def test_search_requires_pattern(self) -> None:
        tool = WorkspaceTool()
        result = tool._run(action="search")
        assert "Error" in result
        assert "pattern" in result.lower()

    def test_info_action(self, tmp_path: Path) -> None:
        test_file = tmp_path / "info.txt"
        test_file.write_text("some content")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="info", path="info.txt")
        assert "Size" in result or "Path" in result

    def test_action_case_insensitive(self, tmp_path: Path) -> None:
        test_file = tmp_path / "case.txt"
        test_file.write_text("test")
        tool = WorkspaceTool(work_dir=str(tmp_path))
        result = tool._run(action="READ", path="case.txt")
        assert "test" in result


# ---------------------------------------------------------------------------
# ExecuteTool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    """Tests for the execute capability tool."""

    def test_create_returns_single_tool(self) -> None:
        tools = create_execute_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], ExecuteTool)

    def test_tool_name(self) -> None:
        tool = ExecuteTool()
        assert tool.name == "execute"

    def test_unknown_mode(self) -> None:
        tool = ExecuteTool()
        result = tool._run(code="echo hi", mode="teleport")
        assert "Error" in result
        assert "Unknown mode" in result

    def test_description_mentions_modes(self) -> None:
        tool = ExecuteTool()
        desc = tool.description.lower()
        assert "shell" in desc
        assert "python" in desc
        assert "background" in desc


# ---------------------------------------------------------------------------
# DataTool
# ---------------------------------------------------------------------------


class TestDataTool:
    """Tests for the data capability tool."""

    def test_create_returns_single_tool(self) -> None:
        tools = create_data_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], DataTool)

    def test_tool_name(self) -> None:
        tool = DataTool()
        assert tool.name == "data"

    def test_detect_domain_csv(self) -> None:
        tool = DataTool()
        assert tool._detect_domain("data.csv") == "tabular"
        assert tool._detect_domain("data.xlsx") == "tabular"
        assert tool._detect_domain("data.parquet") == "tabular"

    def test_detect_domain_document(self) -> None:
        tool = DataTool()
        assert tool._detect_domain("doc.pdf") == "document"
        assert tool._detect_domain("doc.docx") == "document"
        assert tool._detect_domain("readme.txt") == "document"
        assert tool._detect_domain("notes.md") == "document"

    def test_detect_domain_unknown(self) -> None:
        tool = DataTool()
        assert tool._detect_domain("binary.exe") == "unknown"

    def test_unsupported_format(self) -> None:
        tool = DataTool()
        result = tool._run(file_path="binary.exe", operation="inspect")
        assert "Error" in result
        assert "Unsupported" in result

    def test_ask_requires_question(self) -> None:
        tool = DataTool()
        result = tool._run(file_path="data.csv", operation="ask")
        assert "Error" in result
        assert "question" in result.lower()

    @pytest.mark.skipif(not _has_pandas(), reason="pandas not installed")
    def test_tabular_inspect(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")
        tool = DataTool()
        result = tool._run(file_path=str(csv_file), operation="inspect")
        assert "name" in result
        assert "age" in result

    @pytest.mark.skipif(not _has_pandas(), reason="pandas not installed")
    def test_tabular_summary(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")
        tool = DataTool()
        result = tool._run(file_path=str(csv_file), operation="summary")
        assert "2 rows" in result or "Shape" in result

    @pytest.mark.skipif(not _has_pandas(), reason="pandas not installed")
    def test_tabular_quality(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")
        tool = DataTool()
        result = tool._run(file_path=str(csv_file), operation="quality")
        assert isinstance(result, str)

    def test_document_extract(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Hello document world")
        tool = DataTool()
        result = tool._run(file_path=str(txt_file), operation="extract")
        assert "Hello document world" in result


# ---------------------------------------------------------------------------
# Research tool (renamed inquiry)
# ---------------------------------------------------------------------------


class TestResearchToolRename:
    """Tests for the inquiry-to-research rename."""

    def test_tool_name_is_research(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        assert tool.name == "research"

    def test_description_mentions_research(self) -> None:
        from soothe.tools.inquiry import InquiryTool

        tool = InquiryTool()
        assert "research" in tool.description.lower()


# ---------------------------------------------------------------------------
# UnifiedClassification with capability_domains
# ---------------------------------------------------------------------------


class TestUnifiedClassificationDomains:
    """Tests for the capability_domains extension."""

    def test_default_domains_empty(self) -> None:
        from soothe.core.unified_classifier import UnifiedClassification

        c = UnifiedClassification(task_complexity="chitchat", is_plan_only=False)
        assert c.capability_domains == []

    def test_domains_can_be_set(self) -> None:
        from soothe.core.unified_classifier import UnifiedClassification

        c = UnifiedClassification(
            task_complexity="medium",
            is_plan_only=False,
            capability_domains=["research", "workspace"],
        )
        assert "research" in c.capability_domains
        assert "workspace" in c.capability_domains

    async def test_default_classification_has_domains(self) -> None:
        from soothe.core.unified_classifier import UnifiedClassifier

        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        result = await classifier.classify("test")
        assert len(result.capability_domains) > 0


# ---------------------------------------------------------------------------
# Resolver: consolidated names resolve, old names rejected
# ---------------------------------------------------------------------------


class TestResolverConsolidatedNames:
    """Consolidated tool names resolve; legacy names are rejected."""

    def test_research_resolves(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("research")
        assert len(tools) == 1
        assert tools[0].name == "research"

    def test_websearch_resolves(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("websearch")
        assert len(tools) == 1
        assert tools[0].name == "websearch"

    def test_workspace_resolves(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("workspace")
        assert len(tools) == 1
        assert tools[0].name == "workspace"

    def test_execute_resolves(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("execute")
        assert len(tools) == 1
        assert tools[0].name == "execute"

    def test_data_resolves(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("data")
        assert len(tools) == 1
        assert tools[0].name == "data"

    def test_old_names_rejected(self) -> None:
        from soothe.core._resolver_tools import _resolve_single_tool_group_uncached

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
            _EXECUTE_GUIDE,
            _RESEARCH_GUIDE,
            _SUBAGENT_GUIDE,
            _WORKSPACE_GUIDE,
        )

        assert "websearch" in _RESEARCH_GUIDE
        assert "research" in _RESEARCH_GUIDE
        assert "workspace" in _WORKSPACE_GUIDE
        assert "execute" in _EXECUTE_GUIDE.lower()
        assert "data" in _DATA_GUIDE.lower()
        assert "browser" in _SUBAGENT_GUIDE.lower()

    def test_orchestration_guide_has_all_domains(self) -> None:
        from soothe.config.prompts import _TOOL_ORCHESTRATION_GUIDE

        assert "workspace" in _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "execute" in _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "data" in _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "websearch" in _TOOL_ORCHESTRATION_GUIDE.lower()
        assert "research" in _TOOL_ORCHESTRATION_GUIDE.lower()

    def test_no_old_tool_names_in_guide(self) -> None:
        from soothe.config.prompts import _TOOL_ORCHESTRATION_GUIDE

        assert "file_edit" not in _TOOL_ORCHESTRATION_GUIDE
        assert "run_cli" not in _TOOL_ORCHESTRATION_GUIDE
        assert "python_executor" not in _TOOL_ORCHESTRATION_GUIDE
        assert "wizsearch" not in _TOOL_ORCHESTRATION_GUIDE
        assert "inquiry" not in _TOOL_ORCHESTRATION_GUIDE
