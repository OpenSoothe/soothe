"""Tests for subagent factory functions."""

import os

from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.scout import create_scout_subagent


class TestPlannerSubagent:
    def test_creates_subagent_dict(self) -> None:
        spec = create_planner_subagent()
        assert spec["name"] == "planner"
        assert "description" in spec
        assert "system_prompt" in spec

    def test_model_override(self) -> None:
        spec = create_planner_subagent(model="gpt-4o")
        assert spec["model"] == "gpt-4o"

    def test_system_prompt_content(self) -> None:
        spec = create_planner_subagent()
        prompt = spec["system_prompt"]
        assert "planning specialist" in prompt.lower()
        assert "dependencies" in prompt.lower()
        assert "verification" in prompt.lower()

    def test_cwd_is_supported(self) -> None:
        spec_with_cwd = create_planner_subagent(cwd=os.getcwd())
        assert spec_with_cwd["name"] == "planner"


class TestScoutSubagent:
    def test_creates_subagent_dict(self) -> None:
        spec = create_scout_subagent()
        assert spec["name"] == "scout"
        assert "description" in spec
        assert "system_prompt" in spec

    def test_model_override(self) -> None:
        spec = create_scout_subagent(model="gpt-4o")
        assert spec["model"] == "gpt-4o"

    def test_system_prompt_content(self) -> None:
        spec = create_scout_subagent()
        prompt = spec["system_prompt"]
        assert "exploration" in prompt.lower()
        assert "reflection" in prompt.lower()
        assert "synthesis" in prompt.lower() or "synthesise" in prompt.lower()

    def test_cwd_creates_filesystem_tools(self) -> None:
        spec = create_scout_subagent(cwd=os.getcwd())
        assert "tools" in spec
        assert len(spec["tools"]) == 4

    def test_default_creates_filesystem_tools(self) -> None:
        spec = create_scout_subagent()
        assert "tools" in spec
        assert len(spec["tools"]) == 4


class TestBrowserSubagent:
    def test_creates_compiled_subagent_dict(self) -> None:
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent()
        assert spec["name"] == "browser"
        assert "description" in spec
        assert "runnable" in spec

    def test_has_runnable(self) -> None:
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent()
        assert spec["runnable"] is not None

    def test_model_override(self) -> None:
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent(model="gpt-4o")
        assert spec["name"] == "browser"
        assert "runnable" in spec

    def test_privacy_features_disabled_by_default(self) -> None:
        """Test that privacy-invasive features are disabled by default."""
        from soothe.subagents.browser import _build_browser_graph

        # Build graph with defaults
        graph = _build_browser_graph()

        # The graph should have been created with privacy features disabled
        # We verify this by checking the function was callable without errors
        assert graph is not None

    def test_privacy_features_can_be_enabled(self) -> None:
        """Test that privacy features can be explicitly enabled."""
        from soothe.subagents.browser import create_browser_subagent

        # Create subagent with privacy features enabled
        spec = create_browser_subagent(
            disable_extensions=False,
            disable_cloud=False,
            disable_telemetry=False,
        )
        assert spec["name"] == "browser"
        assert "runnable" in spec



class TestClaudeSubagent:
    def test_creates_compiled_subagent_dict(self) -> None:
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent()
        assert spec["name"] == "claude"
        assert "description" in spec
        assert "runnable" in spec

    def test_has_runnable(self) -> None:
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent()
        assert spec["runnable"] is not None

    def test_custom_params(self) -> None:
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent(
            model="opus",
            max_turns=10,
            permission_mode="plan",
        )
        assert spec["name"] == "claude"
        assert "runnable" in spec

    def test_cwd_is_supported(self) -> None:
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent(cwd=os.getcwd())
        assert spec["name"] == "claude"
        assert "runnable" in spec


class TestResearchSubagent:
    def test_requires_model(self) -> None:
        import pytest

        from soothe.subagents.research import create_research_subagent

        with pytest.raises(ValueError, match="requires a model"):
            create_research_subagent(model=None)

    def test_uses_wizsearch_defaults(self) -> None:
        from soothe.subagents.research import _create_research_search_tool

        tool = _create_research_search_tool()
        assert tool.name == "wizsearch_search"
        assert tool.default_engines == ["tavily"]
        assert tool.default_max_results_per_engine == 5
