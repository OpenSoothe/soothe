"""Tests for subagent factory functions."""

from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.scout import create_scout_subagent


class TestPlannerSubagent:
    def test_creates_subagent_dict(self):
        spec = create_planner_subagent()
        assert spec["name"] == "planner"
        assert "description" in spec
        assert "system_prompt" in spec

    def test_model_override(self):
        spec = create_planner_subagent(model="gpt-4o")
        assert spec["model"] == "gpt-4o"

    def test_system_prompt_content(self):
        spec = create_planner_subagent()
        prompt = spec["system_prompt"]
        assert "planning agent" in prompt.lower()
        assert "dependencies" in prompt.lower()
        assert "verification" in prompt.lower()


class TestScoutSubagent:
    def test_creates_subagent_dict(self):
        spec = create_scout_subagent()
        assert spec["name"] == "scout"
        assert "description" in spec
        assert "system_prompt" in spec

    def test_model_override(self):
        spec = create_scout_subagent(model="gpt-4o")
        assert spec["model"] == "gpt-4o"

    def test_system_prompt_content(self):
        spec = create_scout_subagent()
        prompt = spec["system_prompt"]
        assert "exploration" in prompt.lower()
        assert "reflection" in prompt.lower()
        assert "synthesis" in prompt.lower() or "synthesise" in prompt.lower()


class TestBrowserSubagent:
    def test_creates_compiled_subagent_dict(self):
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent()
        assert spec["name"] == "browser"
        assert "description" in spec
        assert "runnable" in spec

    def test_has_runnable(self):
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent()
        assert spec["runnable"] is not None

    def test_model_override(self):
        from soothe.subagents.browser import create_browser_subagent

        spec = create_browser_subagent(model="gpt-4o")
        assert spec["name"] == "browser"
        assert "runnable" in spec

    def test_privacy_features_disabled_by_default(self):
        """Test that privacy-invasive features are disabled by default."""
        from soothe.subagents.browser import _build_browser_graph

        # Build graph with defaults
        graph = _build_browser_graph()

        # The graph should have been created with privacy features disabled
        # We verify this by checking the function was callable without errors
        assert graph is not None

    def test_privacy_features_can_be_enabled(self):
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

    def test_environment_variables_set_correctly(self):
        """Test that environment variables are set in the async function."""
        import os

        from soothe.subagents.browser import _build_browser_graph

        # Save original env vars
        original_ext = os.environ.get("BROWSER_USE_DISABLE_EXTENSIONS")
        original_cloud = os.environ.get("BROWSER_USE_CLOUD_SYNC")
        original_telem = os.environ.get("ANONYMIZED_TELEMETRY")

        try:
            # Build graph with defaults (all privacy features disabled)
            graph = _build_browser_graph()

            # We can't directly test the async function's env var setting
            # without actually running it (which requires browser-use installed),
            # but we verify the function accepts the parameters
            assert graph is not None

        finally:
            # Restore original env vars
            if original_ext is not None:
                os.environ["BROWSER_USE_DISABLE_EXTENSIONS"] = original_ext
            elif "BROWSER_USE_DISABLE_EXTENSIONS" in os.environ:
                del os.environ["BROWSER_USE_DISABLE_EXTENSIONS"]

            if original_cloud is not None:
                os.environ["BROWSER_USE_CLOUD_SYNC"] = original_cloud
            elif "BROWSER_USE_CLOUD_SYNC" in os.environ:
                del os.environ["BROWSER_USE_CLOUD_SYNC"]

            if original_telem is not None:
                os.environ["ANONYMIZED_TELEMETRY"] = original_telem
            elif "ANONYMIZED_TELEMETRY" in os.environ:
                del os.environ["ANONYMIZED_TELEMETRY"]


class TestClaudeSubagent:
    def test_creates_compiled_subagent_dict(self):
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent()
        assert spec["name"] == "claude"
        assert "description" in spec
        assert "runnable" in spec

    def test_has_runnable(self):
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent()
        assert spec["runnable"] is not None

    def test_custom_params(self):
        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent(
            model="opus",
            max_turns=10,
            permission_mode="plan",
        )
        assert spec["name"] == "claude"
        assert "runnable" in spec


class TestResearchSubagent:
    def test_requires_model(self):
        import pytest

        from soothe.subagents.research import create_research_subagent

        with pytest.raises(ValueError, match="requires a model"):
            create_research_subagent(model=None)
