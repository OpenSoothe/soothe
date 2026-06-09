"""PlanPhase full_output handling (IG-370)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe.foundation.loop.planning.phase import PlanPhase
from soothe.foundation.loop.state.schemas import LoopState, PlanResult, StepResult
from soothe.protocols.planner import PlanContext


@pytest.mark.asyncio
async def test_done_preserves_planner_full_output() -> None:
    """When status is done, do not overwrite non-empty full_output with step evidence."""
    mock_lp = AsyncMock()
    mock_lp.plan = AsyncMock(
        return_value=PlanResult(
            status="done",
            goal_progress="complete",
            plan_action="keep",
            decision=None,
            next_action="Goal achieved successfully",
            full_output="Visible assistant answer from execute wave.",
        )
    )
    phase = PlanPhase(mock_lp)
    state = LoopState(goal="g", thread_id="t")
    state.step_results.append(
        StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic", "tool_name": "read_file", "size_bytes": 12},
            duration_ms=1,
            thread_id="t",
        )
    )
    ctx = PlanContext()

    out = await phase.plan(goal="g", state=state, context=ctx)

    assert out.full_output == "Visible assistant answer from execute wave."
    mock_lp.plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_done_does_not_populate_full_output_from_step_evidence() -> None:
    """When done but full_output is empty, it remains empty — goal completion uses the ledger."""
    mock_lp = AsyncMock()
    mock_lp.plan = AsyncMock(
        return_value=PlanResult(
            status="done",
            goal_progress="complete",
            plan_action="keep",
            decision=None,
            next_action="done",
            full_output=None,
        )
    )
    phase = PlanPhase(mock_lp)
    state = LoopState(goal="g", thread_id="t")
    state.step_results.append(
        StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "generic", "tool_name": "read_file", "size_bytes": 99},
            duration_ms=1,
            thread_id="t",
        )
    )
    ctx = PlanContext()

    out = await phase.plan(goal="g", state=state, context=ctx)

    # full_output is no longer populated from step evidence; goal_completion uses the ledger
    assert out.full_output is None
