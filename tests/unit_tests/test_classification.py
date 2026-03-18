"""Unit tests for shared classification module."""

import pytest

from soothe.core.classification import (
    COMPLEX_KEYWORDS,
    MEDIUM_KEYWORDS,
    classify_by_keywords,
    count_tokens,
    is_plan_only_request,
)


class TestKeywordSets:
    """Test unified keyword sets."""

    def test_complex_keywords_coverage(self):
        """Complex keywords should include architectural terms."""
        assert "architect" in COMPLEX_KEYWORDS
        assert "architecture" in COMPLEX_KEYWORDS
        assert "refactor" in COMPLEX_KEYWORDS
        assert "migrate" in COMPLEX_KEYWORDS
        assert "migration" in COMPLEX_KEYWORDS
        assert "infrastructure" in COMPLEX_KEYWORDS

    def test_medium_keywords_coverage(self):
        """Medium keywords should include planning and implementation terms."""
        assert "plan" in MEDIUM_KEYWORDS
        assert "planning" in MEDIUM_KEYWORDS
        assert "implement" in MEDIUM_KEYWORDS
        assert "build" in MEDIUM_KEYWORDS
        assert "debug" in MEDIUM_KEYWORDS
        assert "review" in MEDIUM_KEYWORDS

    def test_keywords_disjoint(self):
        """Complex and medium keywords should be disjoint."""
        assert COMPLEX_KEYWORDS.isdisjoint(MEDIUM_KEYWORDS)

    def test_plan_is_medium_not_complex(self):
        """'plan' should be medium, not complex."""
        assert "plan" in MEDIUM_KEYWORDS
        assert "plan" not in COMPLEX_KEYWORDS


class TestClassifyByKeywords:
    """Test keyword-based classification."""

    def test_complex_keywords(self):
        """Queries with complex keywords should classify as complex."""
        assert classify_by_keywords("architect a new system") == "complex"
        assert classify_by_keywords("refactor the module") == "complex"
        assert classify_by_keywords("migrate the database") == "complex"
        assert classify_by_keywords("design system for UI") == "complex"

    def test_medium_keywords(self):
        """Queries with medium keywords should classify as medium."""
        assert classify_by_keywords("create a plan for tests") == "medium"
        assert classify_by_keywords("implement a REST API") == "medium"
        assert classify_by_keywords("build a feature") == "medium"
        assert classify_by_keywords("review the code") == "medium"

    def test_no_keywords(self):
        """Queries without keywords should return None."""
        assert classify_by_keywords("hello world") is None
        assert classify_by_keywords("read the file") is None
        assert classify_by_keywords("what is the time") is None

    def test_case_insensitive(self):
        """Classification should be case-insensitive."""
        assert classify_by_keywords("ARCHITECT a system") == "complex"
        assert classify_by_keywords("PLAN the implementation") == "medium"

    def test_complex_overrides_medium(self):
        """Complex keywords should take priority over medium keywords."""
        # Both keywords present
        result = classify_by_keywords("plan the migration")
        assert result == "complex"  # "migration" is complex, "plan" is medium


class TestPlanOnlyIntent:
    """Test plan-only request detection."""

    def test_plan_only_phrases(self):
        """Planning prompts should be detected as plan-only requests."""
        assert is_plan_only_request("create a plan for tests/task-download-skills.md")
        assert is_plan_only_request("draft a plan to migrate services")
        assert is_plan_only_request("write a plan only for this task")

    def test_non_plan_only_phrases(self):
        """Execution prompts should not be treated as plan-only."""
        assert not is_plan_only_request("implement source-specific downloaders")
        assert not is_plan_only_request("run tests and fix failing cases")


class TestTokenCounting:
    """Test token counting with tiktoken and estimation."""

    def test_count_tokens_tiktoken(self):
        """Test token counting with tiktoken."""
        tokens = count_tokens("Hello world", use_tiktoken=True)
        # tiktoken is accurate: "Hello world" = 2 tokens
        assert tokens == 2

    def test_count_tokens_estimation(self):
        """Test estimation fallback."""
        tokens = count_tokens("Hello world", use_tiktoken=False)
        # Estimation: len("Hello world") // 4 = 11 // 4 = 2
        assert tokens == 2

    def test_count_tokens_cjk(self):
        """Test CJK text handling."""
        text = "使用浏览器获取信息"

        # tiktoken handles CJK correctly
        tokens_tiktoken = count_tokens(text, use_tiktoken=True)
        assert tokens_tiktoken > 0

        # Estimation also works
        tokens_est = count_tokens(text, use_tiktoken=False)
        assert tokens_est > 0

    def test_count_tokens_auto_fallback(self):
        """Test automatic fallback when tiktoken unavailable."""
        # Should gracefully fall back to estimation
        # Even if tiktoken import fails
        tokens = count_tokens("Hello world")  # Default use_tiktoken=True
        assert tokens > 0  # Either 2 (tiktoken) or 2 (estimation)

    def test_count_tokens_empty_string(self):
        """Test empty string handling."""
        assert count_tokens("") == 0
        assert count_tokens("", use_tiktoken=False) == 0

    def test_count_tokens_longer_text(self):
        """Test token counting for longer text."""
        text = "This is a longer piece of text that should have more tokens"

        tokens_tiktoken = count_tokens(text, use_tiktoken=True)
        tokens_est = count_tokens(text, use_tiktoken=False)

        # Both should return positive integers
        assert tokens_tiktoken > 0
        assert tokens_est > 0

        # tiktoken should be more accurate (not just len // 4)
        # For this text, tiktoken will give a more precise count
