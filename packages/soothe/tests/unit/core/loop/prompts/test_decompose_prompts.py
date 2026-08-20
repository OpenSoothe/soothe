"""Unit tests for do-or-decompose THREAD prompt copy (RFC-904)."""

from __future__ import annotations

from soothe.prompts import (
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    user_finish_or_split_hint_lines,
)
from soothe.prompts.user_message import UserMessageBuilder
from soothe.sloop.engine.execute.step_predecessor_context import build_dependent_execution_hints
from soothe.sloop.state.schemas import StepAction


def test_thread_policy_system_addendum_avoids_host_jargon() -> None:
    text = THREAD_POLICY_SYSTEM_ADDENDUM
    assert "FINISH HERE" in text
    assert "SPLIT" in text
    assert "decompose_task" in text
    assert "write_todos" in text
    assert "StepDAG" not in text
    assert "StrangeLoop" not in text
    assert " CE " not in f" {text} "


def test_decompose_tool_description_leads_with_decision() -> None:
    assert "First decide" in DECOMPOSE_TASK_TOOL_DESCRIPTION
    assert "TERMINAL" in DECOMPOSE_TASK_TOOL_DESCRIPTION
    assert "StepDAG" not in DECOMPOSE_TASK_TOOL_DESCRIPTION


def test_root_vs_child_instruction_lines() -> None:
    root = user_finish_or_split_hint_lines(is_dag_root=True)
    child = user_finish_or_split_hint_lines(is_dag_root=False)
    assert any("full goal" in line for line in root)
    assert any("Prefer finish" in line for line in child)
    assert not any("StepDAG" in line for line in root + child)


def test_execute_envelope_keeps_policy_out_of_user() -> None:
    """User envelope is instance work; finish/split policy lives in system."""
    msg = UserMessageBuilder().build_execute_step_message("Do the thing", step_id="S1")
    assert "FINISH HERE" not in msg
    assert "DECOMPOSITION vs TODOS" not in msg
    assert "StepDAG" not in msg


def test_hints_include_root_do_or_decompose() -> None:
    step = StepAction(description="root goal", is_dag_root=True)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done"
    )
    assert "full goal" in (body.instructions or "")
    assert "decompose_task" in (body.instructions or "")
    assert "FINISH HERE" not in (body.instructions or "")
    assert "StepDAG" not in (body.instructions or "")


def test_hints_include_child_prefer_complete() -> None:
    step = StepAction(description="child work", is_dag_root=False)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done"
    )
    assert "Prefer finish" in (body.instructions or "")
    assert "Prefer one broad native search" not in (body.instructions or "")


def test_root_complex_task_prompts_decompose_first() -> None:
    step = StepAction(description="review arch", is_dag_root=True)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done", task_complexity="complex"
    )
    assert "multi-step task" in (body.instructions or "")
    assert "call decompose_task" in (body.instructions or "")


def test_root_medium_task_prompts_decompose_first() -> None:
    step = StepAction(description="review arch", is_dag_root=True)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done", task_complexity="medium"
    )
    assert "multi-step task" in (body.instructions or "")
    assert "call decompose_task" in (body.instructions or "")


def test_root_simple_task_does_not_force_decompose() -> None:
    step = StepAction(description="apply fix", is_dag_root=True)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done", task_complexity="simple"
    )
    assert "multi-step task" not in (body.instructions or "")
    assert "full goal" in (body.instructions or "")


def test_child_complex_task_does_not_force_decompose() -> None:
    step = StepAction(description="child work", is_dag_root=False)
    body = build_dependent_execution_hints(
        step, has_predecessor_evidence=False, expected_output="done", task_complexity="complex"
    )
    assert "multi-step task" not in (body.instructions or "")
