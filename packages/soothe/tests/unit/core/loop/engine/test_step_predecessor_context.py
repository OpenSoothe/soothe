"""Tests for dependent-step predecessor evidence helpers."""

from __future__ import annotations

from soothe.foundation.sloop.engine.step_predecessor_context import (
    build_dependent_execution_hints,
    build_prior_step_evidence,
    step_needs_brief_hydration,
    template_hydrate_step_brief,
)
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_step_needs_brief_hydration_for_generic_dependent_step() -> None:
    step = StepAction(
        id="02",
        description="Fix identified test or lint failures",
        dependencies=["01"],
    )
    assert step_needs_brief_hydration(step) is True


def test_step_needs_brief_hydration_false_for_concrete_full_description() -> None:
    step = StepAction(
        id="02",
        description="Fix failures",
        full_description=(
            "Using verification output from step 01, edit dreaming_reasoner.py to add the "
            "missing Any import and run ruff --fix on providers_check.py. Do not re-run "
            "verify_finally.sh until both edits are complete, then run it once to confirm."
        ),
        dependencies=["01"],
    )
    assert step_needs_brief_hydration(step) is False


def test_build_prior_step_evidence_from_ledger() -> None:
    step_b = StepAction(
        id="NFZ-02",
        description="Fix identified test or lint failures",
        dependencies=["NFZ-01"],
    )
    step_a = StepAction(
        id="NFZ-01",
        description="Run verification script to identify failures",
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step_b],
        execution_mode="dependency",
        reasoning="test",
    )
    state = LoopState(
        goal="run verify and fix failures",
        thread_id="t1",
        current_decision=decision,
        loop_messages=[
            LoopHumanMessage(
                content="Execute: Run verification script",
                phase="execute_step",
                step_id="NFZ-01",
                thread_id="t1",
            ),
            LoopAIMessage(
                content="verify_finally — pre-commit checks\n✗ F821 undefined name `Any`",
                phase="execute_step",
                step_id="NFZ-01",
                thread_id="t1",
            ),
        ],
    )

    evidence = build_prior_step_evidence(step_b, decision, state)
    assert "NFZ-01" in evidence
    assert "F821" in evidence
    assert "Run verification script" in evidence


def test_build_prior_steps_summaries_from_ledger_and_results() -> None:
    from soothe.foundation.sloop.engine.step_predecessor_context import (
        build_prior_steps_summaries,
    )

    step_b = StepAction(
        id="NFZ-02",
        description="Fix identified test or lint failures",
        dependencies=["NFZ-01"],
    )
    step_a = StepAction(
        id="NFZ-01",
        description="Run verification script to identify failures",
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[step_a, step_b],
        execution_mode="dependency",
        reasoning="test",
    )
    state = LoopState(
        goal="run verify and fix failures",
        thread_id="t1",
        current_decision=decision,
        loop_messages=[
            LoopHumanMessage(
                content="Execute: Run verification script",
                phase="execute_step",
                step_id="NFZ-01",
                thread_id="t1",
            ),
            LoopAIMessage(
                content="verify_finally — pre-commit checks\n✗ F821 undefined name `Any`",
                phase="execute_step",
                step_id="NFZ-01",
                thread_id="t1",
            ),
        ],
    )

    summaries = build_prior_steps_summaries(step_b, decision, state)
    assert len(summaries) == 1
    assert summaries[0].step_id == "NFZ-01"
    assert summaries[0].status == "completed"
    assert "verification script" in summaries[0].description


def test_build_dependent_execution_hints_includes_no_rediscovery_instruction() -> None:
    hints = build_dependent_execution_hints(
        StepAction(id="02", description="Fix failures", dependencies=["01"]),
        has_predecessor_evidence=True,
        wire_subagent=None,
        workspace=None,
        expected_output="All checks pass",
    )
    assert (
        "PRIOR STEPS and prior execute-step ledger turns are authoritative"
        not in hints.instructions
    )
    assert "Prior execute-step ledger turns are authoritative" in hints.instructions
    assert "do not repeat completed discovery steps" in hints.instructions


def test_template_hydrate_step_brief_embeds_evidence() -> None:
    step = StepAction(
        id="02",
        description="Fix identified failures",
        dependencies=["01"],
    )
    brief = template_hydrate_step_brief(
        step,
        "Step 01 — verify (completed)\n---\n✗ lint error in foo.py",
    )
    assert "Do NOT repeat discovery" in brief
    assert "lint error in foo.py" in brief
