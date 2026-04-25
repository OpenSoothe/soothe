"""Tests for debug mode source prefix."""

from soothe_sdk.core.verbosity import VerbosityTier

from soothe_cli.cli.stream.formatter import _derive_source_prefix, format_goal_header


class TestDeriveSourcePrefix:
    """Tests for source prefix derivation."""

    def test_main_agent_at_debug(self) -> None:
        """Should return [main] for empty namespace at DEBUG."""
        result = _derive_source_prefix((), VerbosityTier.DEBUG)
        assert result == "[main]"

    def test_subagent_at_debug(self) -> None:
        """Should return [subagent:name] at DEBUG."""
        result = _derive_source_prefix(("research",), VerbosityTier.DEBUG)
        assert result == "[subagent:research]"

    def test_nested_subagent_at_debug(self) -> None:
        """Should handle nested subagent namespaces."""
        result = _derive_source_prefix(("browser", "nested"), VerbosityTier.DEBUG)
        assert result == "[subagent:browser:nested]"

    def test_hidden_at_normal(self) -> None:
        """Should return None at NORMAL verbosity."""
        result = _derive_source_prefix((), VerbosityTier.NORMAL)
        assert result is None

    def test_hidden_at_quiet(self) -> None:
        """Should return None at QUIET verbosity."""
        result = _derive_source_prefix(("research",), VerbosityTier.QUIET)
        assert result is None

    def test_hidden_at_detailed(self) -> None:
        """Should return None at DETAILED verbosity (only DEBUG shows prefixes)."""
        result = _derive_source_prefix((), VerbosityTier.DETAILED)
        assert result is None


class TestFormatWithSourcePrefix:
    """Tests for formatter functions with source prefix."""

    def test_goal_header_includes_prefix_at_debug(self) -> None:
        """Goal header should include source prefix at DEBUG."""
        line = format_goal_header(
            "test goal",
            namespace=(),
            verbosity_tier=VerbosityTier.DEBUG,
        )
        assert line.source_prefix == "[main]"
        assert "[main]" in line.format()

    def test_goal_header_no_prefix_at_normal(self) -> None:
        """Goal header should NOT include source prefix at NORMAL."""
        line = format_goal_header(
            "test goal",
            namespace=(),
            verbosity_tier=VerbosityTier.NORMAL,
        )
        assert line.source_prefix is None
        assert "[main]" not in line.format()

    def test_subagent_goal_header(self) -> None:
        """Subagent goal should show subagent prefix."""
        line = format_goal_header(
            "research task",
            namespace=("research",),
            verbosity_tier=VerbosityTier.DEBUG,
        )
        assert line.source_prefix == "[subagent:research]"
        assert "[subagent:research]" in line.format()
