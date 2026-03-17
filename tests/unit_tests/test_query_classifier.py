"""Tests for query complexity classifier."""

import pytest

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
        """Test that multi-step tasks are classified as simple or medium based on word count."""
        # These are 6 words each, which falls in simple range (6-15)
        assert classifier.classify("implement a function to parse JSON") == "simple"
        assert classifier.classify("debug the error in my code") == "simple"
        assert classifier.classify("write tests for the auth module") == "simple"
        # 7 words
        assert classifier.classify("can you explain how the planner works") == "simple"

        # Medium requires 16+ words
        query_20_words = " ".join(["implement"] + ["word"] * 19)
        assert classifier.classify(query_20_words) == "medium"  # 7 words

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
        """Test that word count affects classification."""
        # Very short (trivial)
        assert classifier.classify("hi there") == "trivial"

        query_10_words = " ".join(["word"] * 10)
        assert classifier.classify(query_10_words) == "simple"

        query_20_words = " ".join(["word"] * 20)
        assert classifier.classify(query_20_words) == "medium"

        query_40_words = " ".join(["word"] * 40)
        assert classifier.classify(query_40_words) == "complex"

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
        """Test classifier with custom thresholds."""
        custom_classifier = QueryClassifier(
            trivial_word_threshold=3,
            simple_word_threshold=10,
            medium_word_threshold=20,
        )

        # With custom thresholds
        assert custom_classifier.classify("hi") == "trivial"  # 1 word < 3
        assert custom_classifier.classify("hi there friend") == "trivial"  # 3 words = threshold

        query_15_words = " ".join(["word"] * 15)
        assert (
            custom_classifier.classify(query_15_words) == "medium"
        )  # 15 words: between simple (10) and medium (20) thresholds

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
        # 10 words - simple range (6-15)
        assert classifier.classify("Help me implement a REST API endpoint for user authentication") == "simple"
        # Has "refactor" keyword - complex regardless of word count
        assert (
            classifier.classify("I need to refactor the entire authentication system to support OAuth2 and JWT tokens")
            == "complex"
        )

    def test_cjk_word_counting(self, classifier):
        """Test that CJK characters are counted individually as word-equivalents."""
        # "使用浏览器获取最新的美国伊朗战争信息" = 18 CJK chars
        assert classifier._count_words("使用浏览器获取最新的美国伊朗战争信息") == 18
        # Short CJK: 3 chars
        assert classifier._count_words("你好吗") == 3
        # Mixed CJK + ASCII: 6 CJK (使用 + 获取信息) + 1 ASCII word (browser)
        assert classifier._count_words("使用 browser 获取信息") == 7

    def test_cjk_queries_not_trivial(self, classifier):
        """Test that non-trivial CJK queries are not misclassified as trivial."""
        # 18 CJK characters -> medium range (16-30)
        result = classifier.classify("使用浏览器获取最新的美国伊朗战争信息")
        assert result == "medium"

        # Short CJK greeting (2 chars -> trivial)
        assert classifier.classify("你好") == "trivial"

        # Longer CJK query
        result = classifier.classify("请帮我设计一个完整的用户认证系统，包括登录注册和密码重置功能")
        assert result in ("medium", "complex")
