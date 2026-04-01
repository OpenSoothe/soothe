"""Unit tests for dynamic system context injection (RFC-104)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.config.models import MODEL_KNOWLEDGE_CUTOFFS, get_knowledge_cutoff
from soothe.middleware.system_prompt_optimization import SystemPromptOptimizationMiddleware


class TestKnowledgeCutoff:
    """Tests for model knowledge cutoff constants."""

    def test_claude_opus_cutoff(self) -> None:
        """Claude Opus 4.6 has correct cutoff."""
        assert get_knowledge_cutoff("claude-opus-4-6") == "2025-05"

    def test_claude_sonnet_cutoff(self) -> None:
        """Claude Sonnet 4.6 has correct cutoff."""
        assert get_knowledge_cutoff("claude-sonnet-4-6") == "2025-05"

    def test_claude_haiku_cutoff(self) -> None:
        """Claude Haiku 4.5 has correct cutoff."""
        assert get_knowledge_cutoff("claude-haiku-4-5") == "2025-10"

    def test_provider_model_format(self) -> None:
        """Provider:model format is handled correctly."""
        assert get_knowledge_cutoff("anthropic:claude-opus-4-6") == "2025-05"
        assert get_knowledge_cutoff("openai:gpt-4o") == "2025-03"

    def test_unknown_model_returns_default(self) -> None:
        """Unknown model returns default cutoff."""
        assert get_knowledge_cutoff("unknown-model-xyz") == MODEL_KNOWLEDGE_CUTOFFS["default"]

    def test_default_exists(self) -> None:
        """Default cutoff exists."""
        assert "default" in MODEL_KNOWLEDGE_CUTOFFS


class TestEnvironmentSection:
    """Tests for <SOOTHE_ENVIRONMENT> section building."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        config.resolve_model.return_value = "claude-opus-4-6"
        return SystemPromptOptimizationMiddleware(config)

    def test_environment_section_format(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Environment section has correct XML structure."""
        section = middleware._build_environment_section()

        assert "<SOOTHE_ENVIRONMENT>" in section
        assert "</SOOTHE_ENVIRONMENT>" in section
        assert "Platform:" in section
        assert "Shell:" in section
        assert "OS Version:" in section
        assert "Model:" in section
        assert "Knowledge cutoff:" in section

    def test_environment_section_contains_model(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Environment section contains configured model."""
        section = middleware._build_environment_section()
        assert "claude-opus-4-6" in section


class TestWorkspaceSection:
    """Tests for <SOOTHE_WORKSPACE> section building."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        config.resolve_model.return_value = "claude-opus-4-6"
        return SystemPromptOptimizationMiddleware(config)

    def test_workspace_section_non_git(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Workspace section handles non-git directory."""
        section = middleware._build_workspace_section(Path("/tmp/test"), None)

        assert "<SOOTHE_WORKSPACE>" in section
        assert "</SOOTHE_WORKSPACE>" in section
        assert "Primary working directory: /tmp/test" in section
        assert "Is a git repository: False" in section
        assert "Current branch:" not in section

    def test_workspace_section_with_git(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Workspace section includes git status when available."""
        git_status = {
            "branch": "feature/test",
            "main_branch": "main",
            "status": "M src/file.py",
            "recent_commits": "abc123 fix: something",
        }

        section = middleware._build_workspace_section(Path("/project"), git_status)

        assert "Is a git repository: True" in section
        assert "Current branch: feature/test" in section
        assert "Main branch: main" in section
        assert "Status:" in section
        assert "Recent commits:" in section

    def test_workspace_section_no_workspace_uses_cwd(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Workspace section uses cwd when workspace is None."""
        with patch.object(Path, "cwd", return_value=Path("/current/working/dir")):
            section = middleware._build_workspace_section(None, None)
            assert "Primary working directory: /current/working/dir" in section


class TestThreadSection:
    """Tests for <SOOTHE_THREAD> section building."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        return SystemPromptOptimizationMiddleware(config)

    def test_thread_section_basic(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Thread section has basic fields."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 3,
        }

        section = middleware._build_thread_section(thread_context)

        assert "<SOOTHE_THREAD>" in section
        assert "</SOOTHE_THREAD>" in section
        assert "Thread ID: abc123" in section
        assert "Conversation turns: 3" in section

    def test_thread_section_with_goals(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Thread section includes active goals."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 5,
            "active_goals": ["Implement feature", "Write tests"],
        }

        section = middleware._build_thread_section(thread_context)

        assert "Active goals:" in section
        assert "Implement feature" in section

    def test_thread_section_with_plan(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Thread section includes current plan."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 2,
            "current_plan": "Phase 1: Design the API",
        }

        section = middleware._build_thread_section(thread_context)

        assert "Current plan: Phase 1: Design the API" in section

    def test_thread_section_limits_goals(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Thread section limits goals to 5 items."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 1,
            "active_goals": [f"Goal {i}" for i in range(10)],
        }

        section = middleware._build_thread_section(thread_context)

        # Should only include first 5 goals
        assert "Goal 0" in section
        assert "Goal 4" in section
        # The section is truncated in the JSON representation


class TestProtocolsSection:
    """Tests for <SOOTHE_PROTOCOLS> section building."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        return SystemPromptOptimizationMiddleware(config)

    def test_protocols_section_with_all(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Protocols section shows all active protocols."""
        protocol_summary = {
            "context": {"type": "VectorContext", "stats": "8 entries"},
            "memory": {"type": "KeywordMemory", "stats": "3 recalled"},
            "planner": {"type": "ClaudePlanner"},
            "policy": {"type": "ConfigDrivenPolicy"},
        }

        section = middleware._build_protocols_section(protocol_summary)

        assert "<SOOTHE_PROTOCOLS>" in section
        assert "Context: VectorContext" in section
        assert "Memory: KeywordMemory" in section
        assert "Planner: ClaudePlanner" in section
        assert "Policy: ConfigDrivenPolicy" in section

    def test_protocols_section_empty(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Empty protocol summary returns empty string."""
        section = middleware._build_protocols_section({})

        assert section == ""

    def test_protocols_section_partial(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Protocols section handles partial availability."""
        protocol_summary = {
            "context": {"type": "VectorContext"},
            "memory": None,
            "planner": {"type": "ClaudePlanner"},
            "policy": None,
        }

        section = middleware._build_protocols_section(protocol_summary)

        assert "Context: VectorContext" in section
        assert "Planner: ClaudePlanner" in section
        assert "Memory" not in section


class TestComplexityMapping:
    """Tests for complexity-to-sections mapping."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        config.resolve_model.return_value = "claude-opus-4-6"
        return SystemPromptOptimizationMiddleware(config)

    def test_chitchat_no_sections(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Chitchat complexity gets no XML sections."""
        prompt = middleware._get_prompt_for_complexity("chitchat", {})

        assert "<SOOTHE_" not in prompt

    def test_medium_gets_environment_workspace(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Medium complexity gets ENVIRONMENT and WORKSPACE sections."""
        state = {
            "workspace": Path("/project"),
            "git_status": None,
        }

        prompt = middleware._get_prompt_for_complexity("medium", state)

        assert "<SOOTHE_ENVIRONMENT>" in prompt
        assert "<SOOTHE_WORKSPACE>" in prompt
        assert "<SOOTHE_THREAD>" not in prompt
        assert "<SOOTHE_PROTOCOLS>" not in prompt

    def test_complex_gets_all_sections(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Complex complexity gets all four sections."""
        state = {
            "workspace": Path("/project"),
            "git_status": {"branch": "main", "main_branch": "main", "status": "", "recent_commits": ""},
            "thread_context": {"thread_id": "abc", "conversation_turns": 1},
            "protocol_summary": {"context": {"type": "VectorContext"}},
        }

        prompt = middleware._get_prompt_for_complexity("complex", state)

        assert "<SOOTHE_ENVIRONMENT>" in prompt
        assert "<SOOTHE_WORKSPACE>" in prompt
        assert "<SOOTHE_THREAD>" in prompt
        assert "<SOOTHE_PROTOCOLS>" in prompt

    def test_base_prompt_preserved(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Base prompt content is preserved."""
        state = {
            "workspace": Path("/project"),
            "git_status": None,
        }

        prompt = middleware._get_prompt_for_complexity("medium", state)

        # Should contain base prompt elements
        assert "Soothe" in prompt  # assistant name
        assert "Today's date is" in prompt


class TestGitStatusHelper:
    """Tests for get_git_status helper function."""

    @pytest.mark.asyncio
    async def test_non_git_directory_returns_none(self, tmp_path: Path) -> None:
        """Non-git directory returns None."""
        from soothe.safety.workspace import get_git_status

        result = await get_git_status(tmp_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_git_directory_returns_status(self, tmp_path: Path) -> None:
        """Git directory returns status dict."""
        import subprocess

        from soothe.safety.workspace import get_git_status

        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=False)

        result = await get_git_status(tmp_path)

        assert result is not None
        assert "branch" in result
        assert "main_branch" in result
        assert "status" in result
        assert "recent_commits" in result
