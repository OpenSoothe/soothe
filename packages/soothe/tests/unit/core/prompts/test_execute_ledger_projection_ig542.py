"""Execute-step ledger projection (IG-542)."""

from __future__ import annotations

from soothe.prompts.plan_ledger_projection import (
    collect_cross_goal_completion_units,
    project_cross_goal_completion_tail,
    project_execute_step_graph_input,
    resolve_execute_projection_mode,
)
from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_resolve_execute_projection_mode_goal_boundary() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    assert resolve_execute_projection_mode(state) == "goal_boundary"


def test_resolve_execute_projection_mode_mid_goal() -> None:
    from soothe.sloop.state.schemas import StepResult

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


def test_collect_units_requires_goal_completion_pair() -> None:
    ledger = [
        LoopHumanMessage(content="step-1", phase="execute_step"),
        LoopAIMessage(content="first", phase="execute_step"),
        LoopHumanMessage(content="step-2", phase="execute_step"),
        LoopAIMessage(content="final answer", phase="execute_step"),
    ]
    units = collect_cross_goal_completion_units(ledger, k=1)
    assert units == []


def test_project_cross_goal_completion_tail_k2() -> None:
    ledger = [
        LoopHumanMessage(content="g1", phase="goal_completion"),
        LoopAIMessage(content="report one", phase="goal_completion"),
        LoopHumanMessage(content="plan", phase="plan_assess", iteration=0),
        LoopHumanMessage(content="g2", phase="goal_completion"),
        LoopAIMessage(content="report two", phase="goal_completion"),
        LoopHumanMessage(content="plan2", phase="plan_assess", iteration=0),
    ]
    projected = project_cross_goal_completion_tail(ledger, k=2, ledger_cfg=None)
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
    from soothe.sloop.state.schemas import StepResult

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


def test_execute_step_ids_subsumed_by_cross_goal_completion() -> None:
    from soothe.prompts.plan_ledger_projection import (
        execute_step_ids_subsumed_by_cross_goal_completion,
    )

    ledger = [
        LoopHumanMessage(content="h0", phase="execute_step", step_id="00"),
        LoopAIMessage(content="a0", phase="execute_step", step_id="00"),
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        LoopHumanMessage(content="finalize", phase="goal_completion"),
        LoopAIMessage(content="terminal report", phase="goal_completion"),
    ]
    subsumed = execute_step_ids_subsumed_by_cross_goal_completion(ledger, k=1)
    assert subsumed == frozenset({"00", "01"})


def test_project_execute_step_graph_input_prior_wave_replan_without_deps() -> None:
    """Replan wave step with no deps receives prior-wave execute ledger (Slice B′)."""
    step = StepAction(id="AMH-07", description="Check if soothe daemon is running")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="dependency",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(content="h1", phase="execute_step", step_id="WLW-01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="WLW-01"),
        LoopHumanMessage(content="plan", phase="plan_generate", iteration=1),
    ]
    state = LoopState(
        goal="g",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        iteration=1,
    )
    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step,
        decision=decision,
    )
    assert result.mode == "mid_goal"
    assert result.predecessor_projected is True
    assert len(result.messages) == 2
    assert [getattr(m, "step_id", None) for m in result.messages] == ["WLW-01", "WLW-01"]


def test_project_execute_step_graph_input_no_duplicate_when_slice_a_overlaps_predecessor() -> None:
    """Slice A goal_completion must not replay subsumed execute_step rows in Slice B."""
    step_02 = StepAction(id="02", description="Fix", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_02],
        execution_mode="dependency",
        reasoning="r",
    )

    ledger = [
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        LoopHumanMessage(content="finalize", phase="goal_completion"),
        LoopAIMessage(content="prior goal completion report", phase="goal_completion"),
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

    assert result.cross_goal_projected is True
    assert result.predecessor_projected is False
    assert len(result.messages) == 2
    assert "prior goal completion report" in str(result.messages[1].content)
    assert "a1" not in " ".join(str(getattr(m, "content", "")) for m in result.messages)


def test_project_execute_step_graph_input_ledger_direct_subsumed_execute_not_replayed() -> None:
    """ledger_direct completion copies execute text; projection must not replay both."""
    step = StepAction(id="bootstrap", description="Continue")
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    answer = "Same final answer from execute and completion rows."
    ledger = [
        LoopHumanMessage(content="Execute task", phase="execute_step", step_id="01"),
        LoopAIMessage(content=answer, phase="execute_step", step_id="01"),
        LoopHumanMessage(content="finalize", phase="goal_completion"),
        LoopAIMessage(content=answer, phase="goal_completion"),
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
    bodies = [str(getattr(m, "content", "")) for m in result.messages]
    assert result.cross_goal_projected is True
    assert len(result.messages) == 2
    assert answer in bodies
    assert bodies.count(answer) == 1


def test_project_execute_step_graph_input_predecessor_includes_non_overlapping_steps() -> None:
    """When deps reference execute rows outside subsumed segments, Slice B still projects them."""
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
        LoopHumanMessage(content="intent h", phase="intent_classify"),
        LoopAIMessage(content='{"intake":"complex"}', phase="intent_classify"),
        LoopHumanMessage(content="h1", phase="execute_step", step_id="01"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="01"),
        LoopHumanMessage(content="finalize", phase="goal_completion"),
        LoopAIMessage(content="prior completion", phase="goal_completion"),
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

    assert result.cross_goal_projected is True
    assert result.predecessor_projected is True
    assert len(result.messages) == 4
    assert "a0" in str(result.messages[-1].content)
    assert "a1" not in " ".join(str(getattr(m, "content", "")) for m in result.messages)


def test_project_execute_step_graph_input_skips_checkpoint_present_rows() -> None:
    """RFC-214: do not replay ledger rows already on the CoreAgent branch checkpoint."""
    step_02 = StepAction(id="02", description="second", dependencies=["01"])
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="01", description="first"), step_02],
        execution_mode="dependency",
        reasoning="r",
    )
    ledger = [
        LoopHumanMessage(
            content="h1",
            phase="execute_step",
            step_id="01",
            core_agent_message_id="human-01",
        ),
        LoopAIMessage(
            content="a1",
            phase="execute_step",
            step_id="01",
            core_agent_message_id="ai-01",
        ),
    ]
    state = LoopState(
        goal="g",
        thread_id="t",
        current_decision=decision,
        loop_messages=ledger,
        iteration=0,
        step_results=[],
    )
    result = project_execute_step_graph_input(
        ledger,
        state=state,
        step=step_02,
        decision=decision,
        checkpoint_message_ids=frozenset({"human-01", "ai-01"}),
    )
    assert result.messages == []
    assert result.predecessor_projected is False
