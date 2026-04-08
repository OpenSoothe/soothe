"""Unit tests for dynamic system context injection (RFC-104)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.config.models import MODEL_KNOWLEDGE_CUTOFFS, get_knowledge_cutoff
from soothe.core.middleware import SystemPromptOptimizationMiddleware
from soothe.core.prompts.context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_protocols_section,
    build_soothe_thread_section,
    build_soothe_workspace_section,
)


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
    """Tests for nested <SOOTHE_ENVIRONMENT> (context_xml)."""

    def test_environment_section_format(self) -> None:
        """Environment section has nested XML structure."""
        section = build_soothe_environment_section(model="claude-opus-4-6")

        # RFC-207: Removed SOOTHE_ prefix from ENVIRONMENT tag
        assert '<ENVIRONMENT version="1">' in section
        assert "</ENVIRONMENT>" in section
        assert "<platform>" in section
        assert "<shell>" in section
        assert "<os_version>" in section
        assert "<model>" in section
        assert "<knowledge_cutoff>" in section

    def test_environment_section_contains_model(self) -> None:
        """Environment section contains configured model."""
        section = build_soothe_environment_section(model="claude-opus-4-6")
        assert "claude-opus-4-6" in section


class TestWorkspaceSection:
    """Tests for nested <SOOTHE_WORKSPACE> (context_xml)."""

    def test_workspace_section_non_git(self) -> None:
        """Workspace section handles non-git directory."""
        section = build_soothe_workspace_section(Path("/tmp/test"), None)

        # RFC-207: Removed SOOTHE_ prefix from WORKSPACE tag
        assert '<WORKSPACE version="1">' in section
        assert "</WORKSPACE>" in section
        assert "<root>" in section
        assert "/tmp/test" in section
        assert 'present="false"' in section
        assert "<branch>" not in section

    def test_workspace_section_with_git(self) -> None:
        """Workspace section includes git status when available."""
        git_status = {
            "branch": "feature/test",
            "main_branch": "main",
            "status": "M src/file.py",
            "recent_commits": "abc123 fix: something",
        }

        section = build_soothe_workspace_section(Path("/project"), git_status)

        assert 'present="true"' in section
        assert "feature/test" in section
        assert "main" in section
        assert "M src/file.py" in section
        assert "abc123" in section

    def test_workspace_section_no_workspace_uses_cwd(self) -> None:
        """Workspace section uses cwd when workspace is None."""
        with patch.object(Path, "cwd", return_value=Path("/current/working/dir")):
            section = build_soothe_workspace_section(None, None)
            assert "/current/working/dir" in section


class TestThreadSection:
    """Tests for <SOOTHE_THREAD> (context_xml)."""

    def test_thread_section_basic(self) -> None:
        """Thread section has basic fields."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 3,
        }

        section = build_soothe_thread_section(thread_context)

        assert '<SOOTHE_THREAD version="1">' in section
        assert "</SOOTHE_THREAD>" in section
        assert "abc123" in section
        assert "<conversation_turns>3</conversation_turns>" in section

    def test_thread_section_with_goals(self) -> None:
        """Thread section includes active goals."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 5,
            "active_goals": ["Implement feature", "Write tests"],
        }

        section = build_soothe_thread_section(thread_context)

        assert "active_goals" in section
        assert "Implement feature" in section

    def test_thread_section_with_plan(self) -> None:
        """Thread section includes current plan."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 2,
            "current_plan": "Phase 1: Design the API",
        }

        section = build_soothe_thread_section(thread_context)

        assert "Phase 1: Design the API" in section

    def test_thread_section_limits_goals(self) -> None:
        """Thread section limits goals to 5 items."""
        thread_context = {
            "thread_id": "abc123",
            "conversation_turns": 1,
            "active_goals": [f"Goal {i}" for i in range(10)],
        }

        section = build_soothe_thread_section(thread_context)

        assert "Goal 0" in section
        assert "Goal 4" in section


class TestProtocolsSection:
    """Tests for <SOOTHE_PROTOCOLS> (context_xml)."""

    def test_protocols_section_with_all(self) -> None:
        """Protocols section shows all active protocols."""
        protocol_summary = {
            "context": {"type": "VectorContext", "stats": "8 entries"},
            "memory": {"type": "KeywordMemory", "stats": "3 recalled"},
            "planner": {"type": "ClaudePlanner"},
            "policy": {"type": "ConfigDrivenPolicy"},
        }

        section = build_soothe_protocols_section(protocol_summary)

        assert '<SOOTHE_PROTOCOLS version="1">' in section
        assert 'id="context"' in section
        assert "VectorContext" in section
        assert 'id="memory"' in section
        assert 'id="planner"' in section
        assert 'id="policy"' in section

    def test_protocols_section_empty(self) -> None:
        """Empty protocol summary returns empty string."""
        section = build_soothe_protocols_section({})

        assert section == ""

    def test_protocols_section_partial(self) -> None:
        """Protocols section handles partial availability."""
        protocol_summary = {
            "context": {"type": "VectorContext"},
            "memory": None,
            "planner": {"type": "ClaudePlanner"},
            "policy": None,
        }

        section = build_soothe_protocols_section(protocol_summary)

        assert 'id="context"' in section
        assert 'id="planner"' in section
        assert 'id="memory"' not in section


class TestBuildContextSectionsForComplexity:
    """Sanity checks for ordered block builder."""

    def test_medium_order(self) -> None:
        config = MagicMock()
        config.resolve_model.return_value = "m"
        state = {"workspace": "/tmp", "git_status": None}
        blocks = build_context_sections_for_complexity(
            config=config, complexity="medium", state=state, include_workspace_extras=False
        )
        assert len(blocks) == 2
        # RFC-207: Removed SOOTHE_ prefix from ENVIRONMENT and WORKSPACE tags
        assert "ENVIRONMENT" in blocks[0]
        assert "WORKSPACE" in blocks[1]


class TestComplexityMapping:
    """Tests for complexity-to-sections mapping (middleware)."""

    @pytest.fixture
    def middleware(self) -> SystemPromptOptimizationMiddleware:
        """Create middleware instance for testing."""
        config = MagicMock()
        config.assistant_name = "Soothe"
        config.resolve_model.return_value = "claude-opus-4-6"
        config.system_prompt = None
        config.performance.enabled = True
        config.performance.optimize_system_prompts = True
        config.performance.unified_classification = True
        return SystemPromptOptimizationMiddleware(config)

    def test_chitchat_no_sections(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Chitchat complexity gets no XML context sections."""
        prompt = middleware._get_prompt_for_complexity("chitchat", {})

        assert "<SOOTHE_" not in prompt
        assert "Today's date is" in prompt

    def test_medium_gets_environment_workspace(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Medium complexity gets ENVIRONMENT and WORKSPACE sections."""
        state = {
            "workspace": Path("/project"),
            "git_status": None,
        }

        prompt = middleware._get_prompt_for_complexity("medium", state)

        # RFC-207: Removed SOOTHE_ prefix from ENVIRONMENT and WORKSPACE tags
        assert "<ENVIRONMENT" in prompt
        assert "<WORKSPACE" in prompt
        assert "<SOOTHE_THREAD" not in prompt
        assert "<SOOTHE_PROTOCOLS" not in prompt
        assert prompt.strip().endswith(middleware._current_date_line())

    def test_complex_gets_all_sections(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Complex complexity gets all four sections."""
        state = {
            "workspace": Path("/project"),
            "git_status": {"branch": "main", "main_branch": "main", "status": "", "recent_commits": ""},
            "thread_context": {"thread_id": "abc", "conversation_turns": 1},
            "protocol_summary": {"context": {"type": "VectorContext"}},
        }

        prompt = middleware._get_prompt_for_complexity("complex", state)

        # RFC-207: Removed SOOTHE_ prefix from ENVIRONMENT and WORKSPACE tags
        assert "<ENVIRONMENT" in prompt
        assert "<WORKSPACE" in prompt
        assert "<SOOTHE_THREAD" in prompt
        assert "<SOOTHE_PROTOCOLS" in prompt

    def test_base_prompt_preserved(self, middleware: SystemPromptOptimizationMiddleware) -> None:
        """Base prompt content is preserved before context blocks."""
        state = {
            "workspace": Path("/project"),
            "git_status": None,
        }

        prompt = middleware._get_prompt_for_complexity("medium", state)

        assert "Soothe" in prompt
        assert "Today's date is" in prompt
        core = middleware._get_base_prompt_core("medium")
        assert core in prompt


class TestGitStatusHelper:
    """Tests for get_git_status helper function."""

    @pytest.mark.asyncio
    async def test_non_git_directory_returns_none(self, tmp_path: Path) -> None:
        """Non-git directory returns None."""
        from soothe.core.workspace import get_git_status

        result = await get_git_status(tmp_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_git_directory_returns_status(self, tmp_path: Path) -> None:
        """Git directory returns status dict."""
        import subprocess

        from soothe.core.workspace import get_git_status

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=False)

        result = await get_git_status(tmp_path)

        assert result is not None
        assert "branch" in result
        assert "main_branch" in result
        assert "status" in result
        assert "recent_commits" in result
