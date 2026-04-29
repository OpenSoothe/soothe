"""Tests for CliRenderer stdout/stderr spacing (IG-118 follow-up)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe_cli.cli.renderer import CliRenderer
from soothe_cli.cli.stream.display_line import DisplayLine

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


def test_stderr_icon_block_after_assistant_gets_leading_blank_line(
    capsys: CaptureFixture[str],
) -> None:
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


def test_turn_end_clears_assistant_buffer(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_assistant_text("intermediate step body", is_main=True, is_streaming=True)
    r.on_assistant_text("final step dump", is_main=True, is_streaming=False)
    assert r._state.full_response
    r.on_turn_end()
    assert r._state.full_response == []
    _ = capsys.readouterr()


def test_tool_result_structured_payload_is_summarized(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_tool_result(
        name="glob",
        result="['/a/README.md', '/b/README.md', '/c/README.md']",
        tool_call_id="tc-1",
        is_error=False,
        is_main=True,
    )
    captured = capsys.readouterr()
    assert "structured payload" in captured.err


def test_tool_call_and_result_render_on_same_line_with_call_id(
    capsys: CaptureFixture[str],
) -> None:
    r = CliRenderer()
    r.on_tool_call(
        name="glob",
        args={"path": "/tmp", "glob_pattern": "**/*.py"},
        tool_call_id="tc-join-1",
        is_main=True,
    )
    r.on_tool_result(
        name="glob",
        result="Found 1 file",
        tool_call_id="tc-join-1",
        is_error=False,
        is_main=True,
    )
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "⚙ Glob(" in lines[0]
    assert "-> ✓ Found 1 file" in lines[0]


def test_tool_call_without_id_keeps_separate_result_line(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_tool_call(
        name="glob",
        args={"path": "/tmp", "glob_pattern": "**/*.py"},
        tool_call_id="",
        is_main=True,
    )
    r.on_tool_result(
        name="glob",
        result="Found 1 file",
        tool_call_id="",
        is_error=False,
        is_main=True,
    )
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0].startswith("⚙ Glob(")
    assert lines[1].startswith("✓ Found 1 file")


def test_agentic_loop_completed_keeps_passthrough_stdout(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 8, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_assistant_text("Found 92 README files.", is_main=True, is_streaming=False)
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 5,
        },
        namespace=(),
    )
    captured = capsys.readouterr()
    assert "Found 92 README" in captured.out
    assert not r.presentation_engine.final_answer_locked


def test_agentic_loop_completed_preserves_markdown_and_token_boundaries(
    capsys: CaptureFixture[str],
) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 5, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_assistant_text(
        (
            "# Report\n\n"
            "## 1. Objective\n\n"
            "Read the first 10 lines.\n\n"
            "Methodology: first 10 lines exact."
        ),
        is_main=True,
        is_streaming=False,
    )
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 3,
        },
        namespace=(),
    )
    out = capsys.readouterr().out
    assert "## 1. Objective" in out
    assert "first 10 lines" in out
    assert "##1. Objective" not in out
    assert "first10 lines" not in out


def test_agentic_loop_completed_repairs_concatenated_markdown_headings(
    capsys: CaptureFixture[str],
) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 5, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_assistant_text(
        "# README Coverage Analysis Report## SummaryThis report...\n###1. Documentation Distribution",
        is_main=True,
        is_streaming=False,
    )
    out = capsys.readouterr().out
    assert "Report## Summary" not in out
    assert "## Summary" in out
    assert "### 1. Documentation Distribution" in out
    assert "#\n\n## 1." not in out


def test_agentic_stdout_visible_after_turn_end(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 8, "thread_id": "t", "goal": "count readmes"},
        namespace=(),
    )
    r.on_turn_end()
    r.on_assistant_text("RAW_LIST_SHOULD_LEAK", is_main=True, is_streaming=False)
    assert "RAW_LIST_SHOULD_LEAK" in capsys.readouterr().out
    r.on_assistant_text("Found 12 README.md files (project only).", is_main=True, is_streaming=False)
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 7,
        },
        namespace=(),
    )
    assert "Found 12 README" in capsys.readouterr().out


def test_max_iter_one_no_client_suppression_after_turn_end(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 1, "thread_id": "t", "goal": "count readmes"},
        namespace=(),
    )
    r.on_turn_end()
    r.on_assistant_text("RAW_LIST_SHOULD_LEAK", is_main=True, is_streaming=False)
    assert "RAW_LIST_SHOULD_LEAK" in capsys.readouterr().out
    r.on_assistant_text("Found 12 README.md files (project only).", is_main=True, is_streaming=False)
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 7,
        },
        namespace=(),
    )
    assert "Found 12 README" in capsys.readouterr().out


def test_single_step_goal_output_streams_directly_without_goal_completion_emit(
    capsys: CaptureFixture[str],
) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 1, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_assistant_text("Found 92 README files.", is_main=True, is_streaming=False)
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
        },
        namespace=(),
    )
    assert "92" in capsys.readouterr().out
    assert not r.presentation_engine.final_answer_locked
