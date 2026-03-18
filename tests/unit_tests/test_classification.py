"""Unit tests for shared classification module."""

import pytest

from soothe.core.classification import (
    COMPLEX_KEYWORDS,
    MEDIUM_KEYWORDS,
    classify_by_keywords,
    count_words,
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


class TestWordCounting:
    """Test word counting with CJK support."""

    def test_ascii_words(self):
        """ASCII text should use space-based counting."""
        assert count_words("hello world") == 2
        assert count_words("the quick brown fox") == 4
        assert count_words("") == 0
        assert count_words("single") == 1

    def test_cjk_characters(self):
        """CJK characters should be counted individually."""
        # Chinese: 18 characters
        assert count_words("使用浏览器获取最新的美国伊朗战争信息") == 18

        # Japanese: mix of hiragana and kanji
        # Each CJK ideograph counts as one word
        text = "今日は良い天気です"
        cjk_count = sum(1 for ch in text if ord(ch) >= 0x4E00)
        assert count_words(text) >= cjk_count

    def test_mixed_cjk_ascii(self):
        """Mixed CJK and ASCII should count both."""
        # 6 CJK + 1 ASCII word
        result = count_words("使用 browser 获取信息")
        assert result == 7

    def test_whitespace_normalization(self):
        """Multiple spaces should not affect count."""
        assert count_words("hello  world") == 2
        assert count_words("hello   world   test") == 3
