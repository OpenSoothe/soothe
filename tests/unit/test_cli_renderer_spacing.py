"""Tests for CliRenderer stdout/stderr spacing (IG-118 follow-up)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.ux.cli.renderer import CliRenderer
from soothe.ux.cli.stream.display_line import DisplayLine

if TYPE_CHECKING:
    from pytest import CaptureFixture


def test_assistant_text_after_stderr_has_no_extra_blank_line(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    line = DisplayLine(level=1, content="Goal: x", icon="●", indent="")
    r.write_lines([line])
    r.on_assistant_text("hello", is_main=True, is_streaming=True)
    captured = capsys.readouterr()
    assert captured.out == "hello"
    assert "\n\n" not in captured.out
    assert "● Goal: x" in captured.err


def test_stderr_icon_block_after_assistant_gets_leading_blank_line(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_assistant_text("done", is_main=True, is_streaming=False)
    line = DisplayLine(level=1, content="Goal: next", icon="●", indent="")
    r.write_lines([line])
    captured = capsys.readouterr()
    assert captured.out.endswith("\n")
    assert captured.err.startswith("\n")
    assert "● Goal: next" in captured.err


def test_consecutive_stderr_icon_lines_no_blank_between_blocks(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.write_lines([DisplayLine(level=1, content="Goal: a", icon="●", indent="")])
    r.write_lines([DisplayLine(level=2, content="Step", icon="○", indent="")])
    captured = capsys.readouterr()
    assert captured.err.count("\n\n") == 0
    assert "● Goal: a" in captured.err
    assert "○ Step" in captured.err
