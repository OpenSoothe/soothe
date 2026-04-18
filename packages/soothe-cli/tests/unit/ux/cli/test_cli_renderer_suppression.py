"""Unit tests for CliRenderer assistant text suppression (IG-143)."""

from io import StringIO
from unittest.mock import patch

from soothe_cli.cli.renderer import CliRenderer


def test_on_tool_call_emits_during_multi_step_suppression():
    """Tool stderr lines must still show when assistant text is suppressed (multi-step)."""
    renderer = CliRenderer(verbosity="normal")
    renderer._state.suppression.multi_step_active = True
    renderer._state.suppression.agentic_stdout_suppressed = True

    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
        renderer.on_tool_call("read_file", {"path": "/tmp/x"}, "tc-arch-1", is_main=True)

    err = mock_stderr.getvalue()
    assert "⚙" in err
    assert "/tmp/x" in err


def test_on_tool_result_emits_during_multi_step_suppression():
    """Tool results on stderr must not be gated by multi-step assistant suppression."""
    renderer = CliRenderer(verbosity="normal")
    renderer._state.suppression.multi_step_active = True
    renderer._state.tool_call_start_times["tc-arch-2"] = 0.0

    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
        renderer.on_tool_result(
            name="glob",
            result="ok",
            tool_call_id="tc-arch-2",
            is_error=False,
            is_main=True,
        )

    assert "✓" in mock_stderr.getvalue()


def test_on_assistant_text_hard_suppress_multi_step():
    """Verify no text leaks during multi_step_active."""
    renderer = CliRenderer(verbosity="normal")

    # Set multi-step active
    renderer._state.suppression.multi_step_active = True

    # Try to emit text
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("This should not appear", is_main=True, is_streaming=False)

        # Verify nothing written to stdout
        assert mock_stdout.getvalue() == ""

    # Verify text accumulated in suppression for final report (IG-143)
    assert renderer._state.suppression.full_response == ["This should not appear"]


def test_on_assistant_text_emits_after_multi_step_clears():
    """Verify text appears after multi_step clears."""
    renderer = CliRenderer(verbosity="normal")

    # Set multi-step active, then clear
    renderer._state.suppression.multi_step_active = True
    renderer._state.suppression.multi_step_active = False

    # Emit text
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Final answer", is_main=True, is_streaming=False)

        # Verify text written
        assert "Final answer" in mock_stdout.getvalue()

    # Verify text accumulated
    assert "Final answer" in "".join(renderer._state.suppression.full_response)


def test_on_assistant_text_suppresses_agentic_loop():
    """Verify agentic_stdout_suppressed blocks text."""
    renderer = CliRenderer(verbosity="normal")

    # Set agentic suppression active
    renderer._state.suppression.agentic_stdout_suppressed = True
    renderer._state.suppression.agentic_final_stdout_emitted = False

    # Try to emit text
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Intermediate text", is_main=True, is_streaming=False)

        # Verify nothing written
        assert mock_stdout.getvalue() == ""

    # Clear suppression flag
    renderer._state.suppression.agentic_final_stdout_emitted = True
    renderer._state.suppression.agentic_stdout_suppressed = False

    # Now text should emit
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Final text", is_main=True, is_streaming=False)

        # Verify text written
        assert "Final text" in mock_stdout.getvalue()


def test_on_assistant_text_suppresses_subagent_text():
    """Verify subagent text (is_main=False) always suppressed."""
    renderer = CliRenderer(verbosity="normal")

    # Try to emit subagent text (even without multi-step flag)
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Subagent output", is_main=False, is_streaming=False)

        # Verify nothing written
        assert mock_stdout.getvalue() == ""


def test_on_assistant_text_accumulates_for_final_display():
    """Verify text accumulation for final output."""
    renderer = CliRenderer(verbosity="normal")

    # Emit multiple chunks
    with patch("sys.stdout"):
        renderer.on_assistant_text("Part 1 ", is_main=True, is_streaming=True)
        renderer.on_assistant_text("Part 2 ", is_main=True, is_streaming=True)
        renderer.on_assistant_text("Part 3", is_main=True, is_streaming=False)

    # Verify full text accumulated in suppression state
    full_text = "".join(renderer._state.suppression.full_response)
    assert "Part 1 Part 2 Part 3" in full_text


def test_on_assistant_text_blocks_during_multi_step_even_with_chunks():
    """Verify hard suppression applies to streaming chunks too."""
    renderer = CliRenderer(verbosity="normal")

    # Set multi-step active
    renderer._state.suppression.multi_step_active = True

    # Try streaming chunks
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Chunk 1", is_main=True, is_streaming=True)
        renderer.on_assistant_text("Chunk 2", is_main=True, is_streaming=True)
        renderer.on_assistant_text("Chunk 3", is_main=True, is_streaming=False)

        # Verify nothing written
        assert mock_stdout.getvalue() == ""

    # Verify chunks accumulated in suppression for final report (IG-143)
    assert renderer._state.suppression.full_response == ["Chunk 1", "Chunk 2", "Chunk 3"]


def test_on_assistant_text_allows_text_in_single_step_mode():
    """Verify text emits normally when multi-step not active."""
    renderer = CliRenderer(verbosity="normal")

    # Ensure multi-step NOT active
    assert not renderer._state.suppression.multi_step_active
    assert not renderer._state.suppression.agentic_stdout_suppressed

    # Emit text
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        renderer.on_assistant_text("Single step answer", is_main=True, is_streaming=False)

        # Verify text written
        assert "Single step answer" in mock_stdout.getvalue()
