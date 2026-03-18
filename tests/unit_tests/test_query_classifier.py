"""Tests for query complexity classifier."""

import pytest

from soothe.config import ComplexityThresholds
from soothe.core.classification import count_tokens
from soothe.core.query_classifier import QueryClassifier


@pytest.fixture
def classifier():
    """Create a default query classifier."""
    return QueryClassifier()


class TestQueryClassifier:
    """Test suite for QueryClassifier."""

    def test_trivial_greetings(self, classifier):
        """Test that common greetings are classified as trivial."""
        assert classifier.classify("hi") == "trivial"
        assert classifier.classify("hello") == "trivial"
        assert classifier.classify("hey") == "trivial"
        assert classifier.classify("thanks") == "trivial"
        assert classifier.classify("thank you") == "trivial"
        assert classifier.classify("ok") == "trivial"
        assert classifier.classify("yes") == "trivial"
        assert classifier.classify("no") == "trivial"
        assert classifier.classify("got it") == "trivial"
        assert classifier.classify("sure") == "trivial"

    def test_trivial_questions(self, classifier):
        """Test that simple questions are classified as trivial."""
        assert classifier.classify("who is your father?") == "trivial"
        assert classifier.classify("what time is it?") == "trivial"
        assert classifier.classify("where is the file?") == "trivial"
        assert classifier.classify("when was this created?") == "trivial"
        assert classifier.classify("who are you?") == "trivial"

    def test_simple_operations(self, classifier):
        """Test that direct operations are classified as simple."""
        assert classifier.classify("read the config file") == "simple"
        assert classifier.classify("show me the logs") == "simple"
        assert classifier.classify("list files in directory") == "simple"
        assert classifier.classify("open the file") == "simple"
        assert classifier.classify("view the output") == "simple"

    def test_simple_searches(self, classifier):
        """Test that basic searches are classified as simple."""
        assert classifier.classify("search for python tutorials") == "simple"
        assert classifier.classify("find the error") == "simple"
        assert classifier.classify("look up the documentation") == "simple"

    def test_simple_executions(self, classifier):
        """Test that direct execution commands are classified as simple."""
        assert classifier.classify("run the tests") == "simple"
        assert classifier.classify("execute the script") == "simple"
        assert classifier.classify("start the server") == "simple"

    def test_medium_tasks(self, classifier):
        """Test that multi-step tasks are classified based on keywords and token count."""
        # These have medium keywords -> medium (not simple)
        assert classifier.classify("implement a function to parse JSON") == "medium"  # "implement" keyword
        assert classifier.classify("debug the error in my code") == "medium"  # "debug" keyword
        assert classifier.classify("write tests for the auth module") == "trivial"  # no keywords, 6 tokens

        # No keywords, just token count
        # 7 tokens, no keywords -> trivial (< 10)
        assert classifier.classify("can you explain how this system works") == "trivial"

        # Medium requires >=30 tokens (no keywords)
        query_31_tokens = "word " * 30  # ~31 tokens
        assert classifier.classify(query_31_tokens) == "medium"

    def test_complex_keywords(self, classifier):
        """Test that queries with complex keywords are classified as complex."""
        assert classifier.classify("architect a new system") == "complex"
        assert classifier.classify("refactor the authentication module") == "complex"
        assert classifier.classify("comprehensive review of security") == "complex"
        assert classifier.classify("migrate the database to postgres") == "complex"
        assert classifier.classify("design a microservices architecture") == "complex"
        assert classifier.classify("create a roadmap for the project") == "complex"
        assert classifier.classify("develop a full-stack application") == "complex"

    def test_word_count_thresholds(self, classifier):
        """Test that token count affects classification (now token-based)."""
        # Very short (trivial)
        assert classifier.classify("hi there") == "trivial"  # 2 tokens

        # 6 tokens -> trivial (< 10)
        query_6_tokens = "word " * 5  # ~6 tokens
        assert classifier.classify(query_6_tokens) == "trivial"

        # 16 tokens -> simple (>= 10, < 30)
        query_16_tokens = "word " * 15  # ~16 tokens
        assert classifier.classify(query_16_tokens) == "simple"

        # 31 tokens -> medium (>= 30, < 60)
        query_31_tokens = "word " * 30  # ~31 tokens
        assert classifier.classify(query_31_tokens) == "medium"

        # 61 tokens -> complex (>= 60)
        query_61_tokens = "word " * 60  # ~61 tokens
        assert classifier.classify(query_61_tokens) == "complex"

    def test_token_thresholds(self, classifier):
        """Test token-based thresholds."""
        # 3 tokens -> trivial (< 10)
        query_3 = "hello world test"  # 3 tokens
        assert classifier.classify(query_3) == "trivial"

        # 16 tokens -> simple (>= 10, < 30)
        query_16 = "word " * 15  # ~16 tokens
        assert classifier.classify(query_16) == "simple"

        # 31 tokens -> medium (>= 30, < 60)
        query_31 = "word " * 30  # ~31 tokens
        assert classifier.classify(query_31) == "medium"

        # 61 tokens -> complex (>= 60)
        query_61 = "word " * 60  # ~61 tokens
        assert classifier.classify(query_61) == "complex"

    def test_empty_query(self, classifier):
        """Test handling of empty queries."""
        assert classifier.classify("") == "simple"
        assert classifier.classify("   ") == "simple"

    def test_case_insensitive(self, classifier):
        """Test that classification is case-insensitive."""
        assert classifier.classify("HELLO") == "trivial"
        assert classifier.classify("Hi") == "trivial"
        assert classifier.classify("READ the file now") == "simple"  # 4 words, matches pattern
        assert classifier.classify("ARCHITECT a system") == "complex"

    def test_punctuation_handling(self, classifier):
        """Test that punctuation is handled correctly."""
        assert classifier.classify("hello!") == "trivial"
        assert classifier.classify("who is your father???") == "trivial"
        assert classifier.classify("read the file please") == "simple"  # 4 words, matches simple pattern

    def test_custom_thresholds(self):
        """Test classifier with custom token thresholds."""
        custom_classifier = QueryClassifier(
            trivial_token_threshold=2,
            simple_token_threshold=10,
            medium_token_threshold=20,
            use_tiktoken=True,
        )

        # With custom thresholds
        assert custom_classifier.classify("hi") == "trivial"  # 1 token < 2

        # 3 tokens = >= trivial threshold (2) -> simple
        query_3_tokens = "hello world test"  # 3 tokens
        result = custom_classifier.classify(query_3_tokens)
        assert result == "simple"

        query_16_tokens = "word " * 15  # ~16 tokens
        # 16 tokens: >= simple threshold (10), < medium threshold (20) -> medium
        assert custom_classifier.classify(query_16_tokens) == "medium"

    def test_edge_cases(self, classifier):
        """Test edge cases and boundary conditions."""
        # Single word
        assert classifier.classify("test") == "trivial"

        # Multiple greetings - matches trivial pattern
        assert classifier.classify("hello hi hey") == "trivial"  # matches pattern

        # Mixed patterns
        assert classifier.classify("can you read the file") == "simple"  # has "read" pattern

        # Questions with complex words
        assert classifier.classify("how do I refactor this?") == "complex"  # has "refactor"

    def test_performance_trivial(self, classifier):
        """Test that trivial classification is fast (< 1ms)."""
        import time

        queries = ["hello", "thanks", "who are you?"] * 100
        start = time.perf_counter()

        for query in queries:
            classifier.classify(query)

        duration_ms = (time.perf_counter() - start) * 1000
        avg_ms = duration_ms / len(queries)

        assert avg_ms < 1.0, f"Classification too slow: {avg_ms:.2f}ms per query"

    def test_real_world_queries(self, classifier):
        """Test classification of real-world queries."""
        # Actual user queries
        assert classifier.classify("What's the current date?") == "trivial"
        assert classifier.classify("Show me the main config file") == "simple"
        assert classifier.classify("Search for all Python files in the project") == "simple"
        # Has "implement" keyword -> medium (not simple)
        assert classifier.classify("Help me implement a REST API endpoint for user authentication") == "medium"
        # Has "refactor" keyword - complex regardless of word count
        assert (
            classifier.classify("I need to refactor the entire authentication system to support OAuth2 and JWT tokens")
            == "complex"
        )

    def test_cjk_queries_not_trivial(self, classifier):
        """Test that non-trivial CJK queries are not misclassified as trivial."""
        # 21 tokens -> simple range (>= 10, < 30)
        result = classifier.classify("使用浏览器获取最新的美国伊朗战争信息")
        assert result == "simple"

        # Short CJK greeting (2 chars -> 2 tokens -> trivial)
        assert classifier.classify("你好") == "trivial"

        # Longer CJK query -> 24 tokens -> simple (>= 10, < 30)
        result = classifier.classify("请帮我设计一个完整的用户认证系统，包括登录注册和密码重置功能")
        assert result == "simple"

    def test_planning_query_is_medium(self, classifier):
        """Test that planning queries are classified as medium.

        Bug fix: "create a plan for tests/task-download-skills.md" was incorrectly
        classified as "trivial" because "plan" keyword was missing from QueryClassifier.
        """
        # The original bug case
        assert classifier.classify("create a plan for tests/task-download-skills.md") == "medium"

        # Additional planning queries
        # "migration" is a complex keyword, so this is complex (complex > medium priority)
        assert classifier.classify("plan the migration strategy") == "complex"
        assert classifier.classify("create a comprehensive plan") == "complex"  # "comprehensive" is complex
        assert classifier.classify("plan the implementation") == "medium"  # "plan" and "implement" both medium

    def test_boundary_fix(self, classifier):
        """Test that boundary conditions use >= instead of >.

        Bug fix: Exactly 10 tokens should be "simple" (not trivial).
        """
        # Create a classifier where we can test exact boundaries
        custom = QueryClassifier(trivial_token_threshold=3, use_tiktoken=True)

        # Exactly 3 tokens -> simple (>= trivial threshold)
        query_3 = "hello world test"  # 3 tokens
        result = custom.classify(query_3)
        assert result == "simple"

        # For default classifier: >= 10 tokens -> simple
        # 16 tokens -> simple (>= 10, < 30)
        query_16 = "word " * 15  # ~16 tokens
        assert classifier.classify(query_16) == "simple"

        # 31 tokens -> medium (>= 30)
        query_31 = "word " * 30  # ~31 tokens
        assert classifier.classify(query_31) == "medium"

        # 61 tokens -> complex (>= 60)
        query_61 = "word " * 60  # ~61 tokens
        assert classifier.classify(query_61) == "complex"

    def test_medium_keywords(self, classifier):
        """Test that medium keywords from shared module are recognized."""
        assert classifier.classify("implement a new feature") == "medium"
        assert classifier.classify("build a REST API") == "medium"
        assert classifier.classify("debug the issue") == "medium"
        assert classifier.classify("review the code changes") == "medium"
        assert classifier.classify("analyze the performance") == "medium"
        assert classifier.classify("optimize the query") == "medium"

    def test_unified_complex_keywords(self, classifier):
        """Test that complex keywords from shared module are recognized."""
        assert classifier.classify("architect a new system") == "complex"
        assert classifier.classify("refactor the module") == "complex"
        assert classifier.classify("migrate to the new platform") == "complex"
        assert classifier.classify("redesign the architecture") == "complex"
        assert classifier.classify("overhaul the system") == "complex"

    def test_keyword_priority_over_word_count(self, classifier):
        """Test that keywords take priority over token count heuristics."""
        # Short query with complex keyword -> complex
        assert classifier.classify("refactor this") == "complex"

        # Short query with medium keyword -> medium
        assert classifier.classify("plan it") == "medium"

        # Long query without keywords -> simple (token count: 21 tokens)
        query_21_tokens = "the " * 20  # ~21 tokens
        assert classifier.classify(query_21_tokens) == "simple"

    def test_uses_shared_token_count(self, classifier):
        """Test that QueryClassifier uses shared count_tokens function."""
        # Verify it's using the shared function from classification module
        from soothe.core.classification import count_tokens as shared_count_tokens

        test_text = "hello world"
        # Both should give the same result
        assert count_tokens(test_text) == shared_count_tokens(test_text)

        # Test with CJK text
        cjk_text = "使用浏览器获取最新的美国伊朗战争信息"
        assert count_tokens(cjk_text) == shared_count_tokens(cjk_text)

    def test_backward_compat_word_config(self):
        """Test backward compatibility with word-based config."""
        thresholds = ComplexityThresholds(
            trivial_words=5,
            simple_words=15,
            medium_words=30,
        )

        # Should convert to tokens (words * 2)
        assert thresholds.get_trivial_threshold() == 10
        assert thresholds.get_simple_threshold() == 30
        assert thresholds.get_medium_threshold() == 60

    def test_token_config_preferred(self):
        """Test that token-based config is used when words are not set."""
        # When only tokens are set, use them
        thresholds = ComplexityThresholds(
            trivial_tokens=15,
            simple_tokens=40,
            medium_tokens=80,
        )

        # Should use token values
        assert thresholds.get_trivial_threshold() == 15
        assert thresholds.get_simple_threshold() == 40
        assert thresholds.get_medium_threshold() == 80

    def test_word_config_overrides_tokens(self):
        """Test that word-based config overrides token config for backward compat."""
        # When both are set, word-based takes precedence (backward compat)
        thresholds = ComplexityThresholds(
            trivial_tokens=15,
            simple_tokens=40,
            medium_tokens=80,
            trivial_words=5,  # Overrides trivial_tokens
        )

        # Should use word values converted to tokens
        assert thresholds.get_trivial_threshold() == 10  # 5 * 2
        assert thresholds.get_simple_threshold() == 40  # No word override
        assert thresholds.get_medium_threshold() == 80  # No word override
