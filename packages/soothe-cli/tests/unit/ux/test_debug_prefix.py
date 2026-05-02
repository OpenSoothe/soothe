"""Tests for stream line source prefix (IG-343: single UX tier, no debug prefixes)."""

from soothe_cli.cli.stream.formatter import _derive_source_prefix, format_goal_header


class TestDeriveSourcePrefix:
    """Source prefixes are disabled for the fixed client display mode."""

    def test_always_none(self) -> None:
        assert _derive_source_prefix(()) is None
        assert _derive_source_prefix(("research",)) is None


class TestFormatWithSourcePrefix:
    """Goal headers never embed namespace debug prefixes."""

    def test_goal_header_no_prefix(self) -> None:
        line = format_goal_header("test goal", namespace=())
        assert line.source_prefix is None
        assert "[main]" not in line.format()
