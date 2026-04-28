"""Unit tests for CliRenderer assistant text passthrough behavior."""

from io import StringIO
from unittest.mock import patch

from soothe_cli.cli.renderer import CliRenderer


def test_on_assistant_text_passthrough_main_agent() -> None:
    renderer = CliRenderer(verbosity="normal")
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Visible text", is_main=True, is_streaming=False)
    assert "Visible text" in mock_stdout.getvalue()


def test_on_assistant_text_suppresses_subagent_text() -> None:
    renderer = CliRenderer(verbosity="normal")
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Hidden subagent", is_main=False, is_streaming=False)
    assert mock_stdout.getvalue() == ""


def test_on_assistant_text_accumulates_turn_buffer() -> None:
    renderer = CliRenderer(verbosity="normal")
    with patch("sys.stdout"):
        renderer.on_assistant_text("Part 1 ", is_main=True, is_streaming=True)
        renderer.on_assistant_text("Part 2", is_main=True, is_streaming=False)
    assert "".join(renderer._state.full_response).startswith("Part 1")


def test_on_turn_end_clears_turn_buffer() -> None:
    renderer = CliRenderer(verbosity="normal")
    with patch("sys.stdout"):
        renderer.on_assistant_text("some text", is_main=True, is_streaming=False)
    assert renderer._state.full_response
    renderer.on_turn_end()
    assert renderer._state.full_response == []
