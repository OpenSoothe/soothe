"""PlanPhase full_output handling (IG-370)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe.core.agent_loop.core.plan_phase import PlanPhase
from soothe.core.agent_loop.state.schemas import LoopState, PlanResult, StepResult
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
async def test_done_falls_back_to_step_evidence_when_full_output_empty() -> None:
    """When done but full_output is empty, join successful step evidence strings."""
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

    assert out.full_output is not None
    assert "s1" in out.full_output
    assert "read_file" in out.full_output
