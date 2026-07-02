"""Execute-step ledger projection (IG-542)."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    collect_cross_goal_completion_units,
    project_cross_goal_completion_tail,
    project_execute_step_graph_input,
    resolve_execute_projection_mode,
)
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_resolve_execute_projection_mode_goal_boundary() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    assert resolve_execute_projection_mode(state) == "goal_boundary"


def test_resolve_execute_projection_mode_mid_goal() -> None:
    from soothe.foundation.sloop.state.schemas import StepResult

    state = LoopState(
        goal="g",
        thread_id="t",
        iteration=1,
        step_results=[
            StepResult(
                step_id="01",
                success=True,
                duration_ms=1,
                thread_id="t",
            )
        ],
    )
    assert resolve_execute_projection_mode(state) == "mid_goal"


def test_collect_units_synthesized_goal_completion() -> None:
    ledger = [
        LoopHumanMessage(content="step", phase="execute_step"),
        LoopAIMessage(content="step output", phase="execute_step"),
        LoopHumanMessage(content="finalize", phase="goal_completion"),
        LoopAIMessage(content="synthesized report", phase="goal_completion"),
    ]
    units = collect_cross_goal_completion_units(ledger, k=1)
    assert len(units) == 1
    assert len(units[0]) == 2
    assert units[0][-1].content == "synthesized report"


def test_collect_units_ledger_direct_execute_step() -> None:
    ledger = [
        LoopHumanMessage(content="step-1", phase="execute_step"),
        LoopAIMessage(content="first", phase="execute_step"),
        LoopHumanMessage(content="step-2", phase="execute_step"),
        LoopAIMessage(content="final answer", phase="execute_step"),
    ]
    units = collect_cross_goal_completion_units(ledger, k=1)
    assert len(units) == 1
    assert units[0][0].content == "step-2"
    assert units[0][1].content == "final answer"


def test_project_cross_goal_completion_tail_k2() -> None:
    ledger = [
        LoopHumanMessage(content="g1", phase="goal_completion"),
        LoopAIMessage(content="report one", phase="goal_completion"),
        LoopHumanMessage(content="plan", phase="plan_assess", iteration=0),
        LoopHumanMessage(content="g2", phase="goal_completion"),
        LoopAIMessage(content="report two", phase="goal_completion"),
        LoopHumanMessage(content="plan2", phase="plan_assess", iteration=0),
    ]
    projected = project_cross_goal_completion_tail(ledger, k=2, ledger_cfg=None, checkpoint=None)
    assert len(projected) == 4
    bodies = [str(getattr(m, "content", "")) for m in projected]
    assert "report one" in bodies
    assert "report two" in bodies


def test_project_execute_step_graph_input_slice_a_on_continue() -> None:
    step = StepAction(id="bootstrap", description="Continue")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    ledger = [
        LoopAIMessage(content="prior completion body", phase="goal_completion"),
        LoopHumanMessage(content="plan", phase="plan_assess", iteration=0),
    ]
    state = LoopState(
        goal="continue",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
        iteration=0,
    )
    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step,
        decision=decision,
    )
    assert result.cross_goal_projected is True
    assert len(result.messages) >= 1
    assert "prior completion body" in str(result.messages[-1].content)


def test_project_execute_step_graph_input_mid_goal_no_slice_a() -> None:
    from soothe.foundation.sloop.state.schemas import StepResult

    step = StepAction(id="02", description="Fix", dependencies=["01"])
    step_a = StepAction(id="01", description="Verify")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step],
        execution_mode="dependency",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="old goal completion", phase="goal_completion"),
    ]
    state = LoopState(
        goal="g",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
        iteration=1,
        step_results=[
            StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"),
        ],
    )
    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step,
        decision=decision,
    )
    assert result.cross_goal_projected is False
    assert result.predecessor_projected is True
    assert len(result.messages) == 2


def test_project_execute_step_graph_input_predecessor_false_when_ledger_empty() -> None:
    step = StepAction(id="02", description="Fix", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step, StepAction(id="01", description="Verify")],
        execution_mode="dependency",
        reasoning="r",
    )
    state = LoopState(
        goal="g",
        thread_id="t",
        current_decision=decision,
        loop_messages=[],
        iteration=1,
    )
    result = project_execute_step_graph_input(
        [],
        state=state,
        step=step,
        decision=decision,
    )
    assert result.predecessor_projected is False
    assert result.messages == []
