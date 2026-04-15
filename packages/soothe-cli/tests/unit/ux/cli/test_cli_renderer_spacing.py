"""Tests for CliRenderer stdout/stderr spacing (IG-118 follow-up)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.protocols.planner import Plan, PlanStep
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


def test_multi_step_suppresses_assistant_text_and_no_turn_end_replay(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r._state.suppression.multi_step_active = True

    r.on_assistant_text("intermediate step body", is_main=True, is_streaming=True)
    r.on_assistant_text("final step dump", is_main=True, is_streaming=False)
    r.on_turn_end()

    captured = capsys.readouterr()
    assert captured.out == ""


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


def test_agentic_loop_completed_writes_final_stdout_when_multi_step(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 8, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "final_stdout_message": "Found 92 README files.",
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
    assert r.presentation_engine.final_answer_locked


def test_agentic_stdout_stays_suppressed_after_turn_end_until_loop_completed(
    capsys: CaptureFixture[str],
) -> None:
    """Idle/on_turn_end clears multi_step but must not unlock agentic stdout early (test-case1)."""
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 8, "thread_id": "t", "goal": "count readmes"},
        namespace=(),
    )
    r.on_turn_end()
    assert not r._state.suppression.multi_step_active
    r.on_assistant_text("RAW_LIST_SHOULD_NOT_LEAK", is_main=True, is_streaming=False)
    assert "RAW_LIST" not in capsys.readouterr().out
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "final_stdout_message": "Found 12 README.md files (project only).",
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 7,
        },
        namespace=(),
    )
    assert "Found 12 README" in capsys.readouterr().out


def test_max_iter_one_multi_step_plan_suppresses_stdout_after_turn_end(
    capsys: CaptureFixture[str],
) -> None:
    """max_iterations=1 does not arm suppression in loop.started; multi-step plan must (test-case1)."""
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 1, "thread_id": "t", "goal": "count readmes"},
        namespace=(),
    )
    plan = Plan(
        goal="count readmes",
        steps=[
            PlanStep(id="1", description="glob"),
            PlanStep(id="2", description="summarize"),
        ],
    )
    r.on_plan_created(plan)
    r.on_turn_end()
    assert not r._state.suppression.multi_step_active
    assert r._state.suppression.agentic_stdout_suppressed
    r.on_assistant_text("RAW_LIST_SHOULD_NOT_LEAK", is_main=True, is_streaming=False)
    assert "RAW_LIST" not in capsys.readouterr().out
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "final_stdout_message": "Found 12 README.md files (project only).",
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
            "total_steps": 7,
        },
        namespace=(),
    )
    assert "Found 12 README" in capsys.readouterr().out


def test_agentic_loop_completed_skips_final_stdout_without_multi_step(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_progress_event(
        "soothe.cognition.agent_loop.started",
        {"max_iterations": 1, "thread_id": "t", "goal": "g"},
        namespace=(),
    )
    r.on_progress_event(
        "soothe.cognition.agent_loop.completed",
        {
            "final_stdout_message": "Found 92 README files.",
            "thread_id": "t",
            "status": "done",
            "goal_progress": 1.0,
            "evidence_summary": "",
        },
        namespace=(),
    )
    assert "92" not in capsys.readouterr().out
    assert not r.presentation_engine.final_answer_locked
