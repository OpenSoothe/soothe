"""generate_plan station Langfuse parent span + planner pin."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch, LoopRuntimeContext
from soothe.sloop.stages.plan.generate_plan import node_plan_generate
from soothe.sloop.state.schemas import LoopState, PlanResult, StatusAssessment
from soothe.utils.observability.langfuse import generate_plan_langfuse_run_display_name


def test_generate_plan_langfuse_display_name() -> None:
    assert generate_plan_langfuse_run_display_name(None) == "generate-plan"
    assert generate_plan_langfuse_run_display_name("soothe") == "soothe:generate-plan"


def test_planner_maps_generate_plan_langfuse_phase() -> None:
    assert (
        LLMPlanner._planner_langfuse_phase_name("soothe", "generate-plan") == "soothe:generate-plan"
    )
    # Retries keep the phase suffix via the generic ``{trace}:{phase}`` fallback.
    assert LLMPlanner._planner_langfuse_phase_name("soothe", "generate-plan-retry") is None


def test_planner_langfuse_config_pins_generate_plan() -> None:
    cfg = MagicMock()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "demo"
    planner = LLMPlanner(model=MagicMock(), config=cfg, loop_id="loop-1")
    planner._pinned_trace_id = "trace-abc"

    with patch(
        "soothe.sloop.cognition.planner.merge_langfuse_runnable_config",
        return_value={"callbacks": ["h"]},
    ) as merge:
        out = planner._planner_langfuse_run_config(thread_id="thread-1", phase="generate-plan")

    assert out == {"callbacks": ["h"]}
    _args, kwargs = merge.call_args
    assert kwargs["pinned_trace_id"] == "trace-abc"
    assert kwargs["run_name"] == "demo:generate-plan"


@pytest.mark.asyncio
async def test_node_plan_generate_opens_langfuse_span_and_pins_planner() -> None:
    plan_result = PlanResult(
        status="done",
        plan_action="keep",
        goal_progress="complete",
        next_action="Done",
        require_goal_completion=False,
    )
    plan_phase = MagicMock()
    plan_phase.generate_from_assessment = AsyncMock(return_value=plan_result)
    plan_phase.generate_lightweight = AsyncMock(return_value=plan_result)
    plan_phase._loop_planner = MagicMock()
    plan_phase._loop_planner._pinned_trace_id = None

    strange_loop = MagicMock()
    strange_loop.plan_phase = plan_phase
    strange_loop.loop_planner = plan_phase._loop_planner
    strange_loop._build_plan_context = MagicMock(return_value=MagicMock())
    strange_loop.config = MagicMock()

    state = LoopState(goal="g", thread_id="t", iteration=0)
    goal_trace = MagicMock()
    goal_trace.enabled = True
    goal_trace.trace_id = "trace-xyz"

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="L1"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(
            plan_assessment=StatusAssessment(
                status="continue",
                goal_progress="low",
                assessment_reasoning="Need a plan.",
            )
        ),
        ce=None,
        ce_goal_id=None,
        goal_trace=goal_trace,
    )

    span = MagicMock()
    seen_pin: list[str | None] = []

    @contextmanager
    def _fake_span(**_kwargs: object):
        seen_pin.append(plan_phase._loop_planner._pinned_trace_id)
        yield span

    with (
        patch(
            "soothe.utils.observability.langfuse._generate_plan_span.generate_plan_langfuse_span",
            side_effect=_fake_span,
        ),
        patch(
            "soothe.sloop.stages.plan.generate_plan.mid_loop_use_lightweight_generate",
            return_value=False,
        ),
    ):
        out = await node_plan_generate(ctx, {})

    assert out.get("plan_route") == "goal_done"
    plan_phase.generate_from_assessment.assert_awaited_once()
    assert seen_pin == ["trace-xyz"]
    span.update.assert_called_once()
    assert plan_phase._loop_planner._pinned_trace_id is None
