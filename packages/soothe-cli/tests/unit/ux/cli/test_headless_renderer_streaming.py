"""Tests for ``HeadlessCliRenderer`` (non-TUI / ``--no-tui`` stdout-only mode)."""

from __future__ import annotations

import pytest

from soothe_cli.cli.execution.headless_renderer import HeadlessCliRenderer


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


def test_suppresses_subgraph_assistant_text(capsys: pytest.CaptureFixture[str]) -> None:
    r = HeadlessCliRenderer()
    r.on_assistant_text("subgraph", is_main=False, is_streaming=False)
    out, _ = capsys.readouterr()
    assert out == ""


def test_suppresses_task_scoped_prose(capsys: pytest.CaptureFixture[str]) -> None:
    r = HeadlessCliRenderer()
    r.on_assistant_text(
        "hidden",
        is_main=True,
        is_streaming=False,
        task_scope=("functions.task:0", "claude"),
    )
    out, _ = capsys.readouterr()
    assert out == ""


def test_emits_main_graph_text(capsys: pytest.CaptureFixture[str]) -> None:
    r = HeadlessCliRenderer()
    r.on_assistant_text("Answer", is_main=True, is_streaming=False)
    out, _ = capsys.readouterr()
    assert out == "Answer"
