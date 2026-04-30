"""Tests for IG-300 tool card elision when args and output carry no information."""

from __future__ import annotations

import pytest

from soothe_cli.shared.tool_card_visibility import (
    should_elide_stream_tool_card_mount,
    should_elide_tool_card_no_info,
    tool_result_display_is_insubstantial,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", True),
        ("  \n  ", True),
        ("[]", True),
        ("{}", True),
        ("```json\n[]\n```", True),
        ('["/a/b"]', False),
        ("total 0", False),
    ],
)
def test_tool_result_display_is_insubstantial(text: str, expected: bool) -> None:
    assert tool_result_display_is_insubstantial(text) is expected


def test_should_elide_tool_card_no_info_errors_shown() -> None:
    assert (
        should_elide_tool_card_no_info(
            tool_name="glob",
            args={},
            formatted_output="",
            is_error=True,
        )
        is False
    )


def test_should_elide_tool_card_no_info_meaningful_args() -> None:
    assert (
        should_elide_tool_card_no_info(
            tool_name="glob",
            args={"pattern": "**/*.go"},
            formatted_output="[]",
            is_error=False,
        )
        is False
    )


def test_should_elide_tool_card_no_info_glob_probe() -> None:
    assert (
        should_elide_tool_card_no_info(
            tool_name="glob",
            args={},
            formatted_output="[]",
            is_error=False,
        )
        is True
    )


def test_should_elide_stream_mount_ls_allowlisted() -> None:
    assert (
        should_elide_stream_tool_card_mount(
            tool_name="ls",
            args={},
            message_terminal_for_tool_args=True,
        )
        is False
    )


def test_should_elide_stream_mount_glob_terminal_empty() -> None:
    assert (
        should_elide_stream_tool_card_mount(
            tool_name="glob",
            args={},
            message_terminal_for_tool_args=True,
        )
        is True
    )


def test_should_elide_stream_mount_non_terminal() -> None:
    assert (
        should_elide_stream_tool_card_mount(
            tool_name="glob",
            args={},
            message_terminal_for_tool_args=False,
        )
        is False
    )
