"""Tests for StepPlanManagerAdapter.format_completion_dag_report (goal-end DAG log text)."""

from __future__ import annotations

from soothe.context import StepPlanManagerAdapter
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.planning_models import CompletionStrategy
from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepExecutionRecord,
)


def _make_adapter(goal_description: str) -> StepPlanManagerAdapter:
    ce = ContextEngine()
    goal = GoalNode(description=goal_description)
    ce._dag.add_goal(goal)
    return StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)


def test_format_completion_dag_report_empty_steps() -> None:
    adapter = _make_adapter("example")
    text = adapter.format_completion_dag_report()
    assert "Context Engine Goal DAG" in text
    assert "Step DAG" not in text


def test_format_completion_dag_report_omits_attachment_bodies() -> None:
    body = "FULL_PDF_" + ("Z" * 4000)
    description = (
        "Deep research on world models\n\n"
        "--- Context ---\n"
        "Attached files: 2512.23676v1.pdf (material)\n\n"
        "--- Triarch attachments (extracted content) ---\n"
        f"--- Attachment: 2512.23676v1.pdf (application/pdf) ---\n{body}"
    )
    adapter = _make_adapter(description)
    text = adapter.format_completion_dag_report()
    assert "Deep research on world models" in text
    assert "Attached files: 2512.23676v1.pdf (material)" in text
    assert "Triarch attachments" not in text
    assert body not in text
    assert "FULL_PDF_" not in text


def test_format_completion_dag_report_lists_steps_and_stats() -> None:
    adapter = _make_adapter("ship feature")
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="KFA-01", description="Design API", dependencies=None),
            StepAction(id="KFA-02", description="Implement handler", dependencies=["KFA-01"]),
        ],
        execution_mode="dependency",
    )
    adapter.ingest_plan(
        PlanResult(status="done", goal_progress="complete", decision=decision),
        "KFA",
        3,
    )
    adapter.record_step_outcomes(
        [
            StepExecutionRecord(
                step_id="KFA-01",
                success=True,
                outcome={"type": "generic"},
                error=None,
                duration_ms=10,
                thread_id="t1",
            ),
            StepExecutionRecord(
                step_id="KFA-02",
                success=True,
                outcome={"type": "generic"},
                error=None,
                duration_ms=20,
                thread_id="t1",
            ),
        ]
    )
    text = adapter.format_completion_dag_report()
    assert "KFA-01" in text
    assert "KFA-02" in text
    assert "Depends on: KFA-01" in text
    assert "COMPLETED" in text
    assert "Step DAG" in text
    assert "Design API" in text

    assert CompletionStrategy.LEDGER_DIRECT  # import sanity for moved enum
