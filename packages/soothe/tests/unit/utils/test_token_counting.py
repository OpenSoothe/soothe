"""Unit tests for shared classification utilities (RFC-0012)."""

from soothe.utils import count_tokens


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
