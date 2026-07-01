"""Welcome banner no longer shows daemon connection status in the chat area."""

from __future__ import annotations

from pathlib import Path


def test_welcome_banner_source_does_not_define_connecting_footer() -> None:
    source = Path(__file__).resolve().parents[4] / "src/soothe_cli/tui/widgets/welcome.py"
    text = source.read_text(encoding="utf-8")
    assert "build_connecting_footer" not in text
    assert "_connecting" not in text
    assert "Connecting to daemon" not in text
