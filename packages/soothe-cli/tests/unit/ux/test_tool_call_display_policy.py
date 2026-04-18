"""Tests for TUI tool-call UI policy vs logging verbosity."""

import pytest

from soothe_cli.shared.display_policy import should_show_tool_call_ui


@pytest.mark.parametrize(
    ("verbosity", "expected"),
    [
        ("quiet", False),
        ("normal", True),
        ("detailed", True),
        ("debug", True),
        ("minimal", True),
    ],
)
def test_should_show_tool_call_ui(verbosity: str, expected: bool) -> None:
    assert should_show_tool_call_ui(verbosity) is expected
