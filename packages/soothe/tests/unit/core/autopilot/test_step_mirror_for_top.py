"""Tests for mirroring worker StepDAG progress onto Autopilot CE (IG-689)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.consensus import ConsensusVerdict
from soothe.autopilot.context_store import InMemoryGoalDispatchContextStore
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus


class _ProgressRunner:
    """Emits plan_decision + step_completed then a successful completion."""

    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id
        self._cancelled = False
        self.last_request = None

    async def run(self, request):  # noqa: ANN001
        self.last_request = request
        gid = request.autopilot_job.goal_id
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.progress.plan_decision",
                "goal_id": gid,
                "payload": {
                    "iteration": 0,
                    "steps": [
                        {
                            "id": "XLT-01",
                            "description": "Read job spec",
                            "dependencies": [],
                        },
                        {
                            "id": "XLT-02",
                            "description": "Write milestones",
                            "dependencies": ["XLT-01"],
                        },
                    ],
                },
            },
        )
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.progress.step_started",
                "goal_id": gid,
                "payload": {"step_id": "XLT-02", "description": "Write milestones"},
            },
        )
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.progress.step_completed",
                "goal_id": gid,
                "payload": {
                    "step_id": "XLT-01",
                    "success": True,
                    "duration_ms": 12,
                    "tool_call_count": 2,
                },
            },
        )
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.goal_completion",
                "goal_id": gid,
                "outcome": "completed",
                "attempt": 1,
                "context_contribution": {
                    "plan_steps_executed": [],
                    "files_touched": {},
                    "findings": [],
                    "tool_call_stats": {"counts_by_name": {}, "failures_by_name": {}},
                },
                "plan_result_status": "complete",
                "evidence_summary": (
                    "Goal completed successfully with substantive evidence and verified outputs."
                ),
            },
        )

    async def cancel(self) -> None:
        self._cancelled = True


class _ProgressFactory:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create_runner(self, loop_id: str):  # noqa: ANN001
        self.created.append(loop_id)
        return _ProgressRunner(loop_id)


def _mock_consensus_model() -> MagicMock:
    verdict = ConsensusVerdict(decision="accept", reasoning="ok")  # type: ignore[arg-type]
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


async def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_worker_progress_mirrors_steps_onto_autopilot_ce() -> None:
    """plan_decision / step_completed land on Autopilot GoalNode.steps for top."""
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        runner_factory=_ProgressFactory(),
        consensus_model=_mock_consensus_model(),
    )
    svc._context_store = InMemoryGoalDispatchContextStore()

    goal = await svc.submit_task("Mirror steps for top", priority=50)
    await svc._schedule_ready_goals()
    assert await _wait_until(
        lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done())
    )
    node = ce.get_goal_sync(goal.id)
    assert node is not None
    assert "XLT-01" in node.steps.nodes
    assert "XLT-02" in node.steps.nodes
    assert node.steps.nodes["XLT-01"].status == "completed"
    # step_started fired before XLT-01 completed; XLT-02 remains active
    assert node.steps.nodes["XLT-02"].status == "active"
    assert node.steps.nodes["XLT-02"].dependencies == ["XLT-01"]

    dag = await svc.dag_snapshot(goal.id)
    by_id = {n["id"]: n for n in dag["nodes"]}
    assert by_id[goal.id]["steps_total"] == 2
    assert by_id[goal.id]["steps_completed"] == 1
    assert by_id[goal.id]["steps"]["nodes"][0]["id"] in {"XLT-01", "XLT-02"}

    top = await svc.top_snapshot(include_terminal=True)
    job = next(j for j in top["jobs"] if j["id"] == goal.id)
    top_node = next(n for n in job["dag"]["nodes"] if n["id"] == goal.id)
    assert top_node["steps"]["nodes"]
    step_by_id = {s["id"]: s for s in top_node["steps"]["nodes"]}
    assert step_by_id["XLT-02"]["status"] == "active"


@pytest.mark.asyncio
async def test_mirror_plan_decision_helper_is_idempotent() -> None:
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1),
        internal_bus=InternalEventBus(),
        runner_factory=_ProgressFactory(),
    )
    goal = await ce.create_goal("g", priority=50)
    await svc._mirror_plan_decision(
        goal.id,
        {
            "iteration": 0,
            "steps": [{"id": "A-01", "description": "one", "dependencies": []}],
        },
    )
    await svc._mirror_plan_decision(
        goal.id,
        {
            "iteration": 1,
            "steps": [
                {"id": "A-01", "description": "one", "dependencies": []},
                {"id": "A-02", "description": "two", "dependencies": ["A-01"]},
            ],
        },
    )
    node = ce.get_goal_sync(goal.id)
    assert node is not None
    assert set(node.steps.nodes) == {"A-01", "A-02"}
    assert node.steps.nodes["A-01"].status == "pending"
