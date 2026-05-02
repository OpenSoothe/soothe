"""Headless CLI stdout: streaming chunks must concatenate without spurious newlines."""

from __future__ import annotations

import pytest

from soothe_cli.cli.headless_renderer import HeadlessCliRenderer


def test_streaming_chunks_do_not_insert_newlines_between_parts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    r = HeadlessCliRenderer()
    r.on_assistant_text("Hello", is_main=True, is_streaming=True)
    r.on_assistant_text(" world", is_main=True, is_streaming=True)
    r.on_assistant_text(".", is_main=True, is_streaming=False)

    out, _ = capsys.readouterr()
    assert out == "Hello world."


def test_non_streaming_concatenates_without_extra_newlines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    r = HeadlessCliRenderer()
    r.on_assistant_text("Line", is_main=True, is_streaming=False)
    r.on_assistant_text("Next", is_main=True, is_streaming=False)
    out, _ = capsys.readouterr()
    assert out == "LineNext"
