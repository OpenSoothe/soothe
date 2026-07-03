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


def test_resolve_execute_projection_mode_mid_goal_when_ce_bound_ledger_has_plan_steps() -> None:
    """Iteration 0 with empty step_results but prior-wave execute ledger is mid_goal."""
    step_01 = StepAction(id="01", description="first")
    step_02 = StepAction(id="02", description="second", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_01, step_02],
        execution_mode="dependency",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
    ]
    state = LoopState(
        goal="g",
        thread_id="t",
        iteration=0,
        step_results=[],
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
    )
    assert resolve_execute_projection_mode(state) == "mid_goal"


def test_project_execute_step_graph_input_no_slice_a_when_intra_goal_ledger_at_iteration_zero() -> (
    None
):
    """Dependent step 02 at iteration=0 must not replay step 01 via Slice A + Slice B."""
    step_01 = StepAction(id="01", description="first")
    step_02 = StepAction(id="02", description="second", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_01, step_02],
        execution_mode="dependency",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="plan", phase="plan_assess", iteration=0),
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
    ]
    state = LoopState(
        goal="continue goal",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
        iteration=0,
        step_results=[],
    )
    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step_02,
        decision=decision,
    )
    assert result.mode == "mid_goal"
    assert result.cross_goal_projected is False
    assert result.predecessor_projected is True
    assert len(result.messages) == 2
    assert [getattr(m, "step_id", None) for m in result.messages] == ["01", "01"]


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


def test_project_execute_step_graph_input_no_duplicate_when_slice_a_fallback_overlaps_predecessor() -> (
    None
):
    """IG-542: Slice A fallback execute_step pairs should not repeat in Slice B.

    When resolve_goal_completion_unit falls back to execute_step pairs (no goal_completion
    synthesized), and those execute_step pairs have step_ids that are in the current step's
    transitive dependencies, they must NOT be included again by project_predecessor_execute_ledger_for_step.

    This scenario occurs in goal_boundary mode (iteration=0, no step_results) with continue_loop=True,
    where the ledger contains prior goal's execute_step pairs but no synthesized goal_completion.
    """
    # Step-02 depends on step-01 completed in a prior goal (not part of the new plan).
    step_02 = StepAction(id="02", description="Fix", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_02],
        execution_mode="dependency",
        reasoning="r",
    )

    # Ledger has NO goal_completion, so Slice A falls back to last execute_step pair
    # The last execute_step pair (step-01) will be included in Slice A
    # Slice B would normally include step-01 messages again (since step-02 depends on step-01)
    # The fix ensures step-01 is excluded from Slice B to prevent duplicates
    ledger = [
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        # No goal_completion pair - triggers fallback to execute_step in Slice A
    ]

    state = LoopState(
        goal="continue goal",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,  # Triggers Slice A
        iteration=0,
        step_results=[],  # Required for goal_boundary mode
    )

    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step_02,
        decision=decision,
    )

    # Slice A should have projected (fallback to execute_step pair)
    assert result.cross_goal_projected is True
    # Slice B has no messages to add (step-01 was the only predecessor and already in Slice A)
    # predecessor_projected reflects whether messages were actually added, not whether deps exist
    assert result.predecessor_projected is False

    # Total messages should be exactly 2 (the step-01 Human+AI pair from Slice A)
    # NOT 4 (which would happen if step-01 was duplicated in Slice B)
    assert len(result.messages) == 2, (
        f"Expected 2 messages (no duplicates), got {len(result.messages)}: "
        f"{[getattr(m, 'step_id', None) for m in result.messages]}"
    )


def test_project_execute_step_graph_input_predecessor_includes_non_overlapping_steps() -> None:
    """IG-542: Slice B still includes predecessor steps NOT in Slice A.

    When Slice A includes step-01 messages (fallback), and the current step depends on
    BOTH step-01 and step-00 from a prior goal, step-00 messages should still appear in Slice B.
    """
    # step-02 depends on prior-goal steps 00 and 01; only step-02 is in the new plan.
    step_02 = StepAction(id="02", description="Fix", dependencies=["00", "01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_02],
        execution_mode="dependency",
        reasoning="r",
    )

    ledger = [
        LoopHumanMessage(content="h0", phase="execute_step", step_id="00"),
        LoopAIMessage(content="a0", phase="execute_step", step_id="00"),
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        # No goal_completion - Slice A falls back to last execute_step (step-01)
    ]

    state = LoopState(
        goal="continue goal",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        continue_loop=True,
        iteration=0,
        step_results=[],  # Required for goal_boundary mode
    )

    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step_02,
        decision=decision,
    )

    # Slice A projected step-01 (fallback)
    assert result.cross_goal_projected is True
    # Slice B should project step-00 (NOT step-01 since it's excluded)
    assert result.predecessor_projected is True

    # Total: 2 from step-01 (Slice A) + 2 from step-00 (Slice B) = 4
    assert len(result.messages) == 4, (
        f"Expected 4 messages (2 from Slice A, 2 from Slice B for step-00), "
        f"got {len(result.messages)}"
    )
