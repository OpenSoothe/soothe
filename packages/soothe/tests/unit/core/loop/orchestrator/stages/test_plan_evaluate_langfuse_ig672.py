"""IG-672: evaluate station Langfuse parent span + child run names."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.plan.evaluate import node_plan_evaluate
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord
from soothe.utils.observability.langfuse import (
    evaluate_assess_langfuse_run_display_name,
    evaluate_gap_langfuse_run_display_name,
    evaluate_gap_leg_langfuse_run_display_name,
    evaluate_langfuse_run_display_name,
)


def test_evaluate_langfuse_display_names() -> None:
    assert evaluate_langfuse_run_display_name(None) == "evaluate"
    assert evaluate_langfuse_run_display_name("soothe") == "soothe:evaluate"
    assert evaluate_gap_langfuse_run_display_name("soothe") == "soothe:evaluate-gap"
    assert (
        evaluate_gap_leg_langfuse_run_display_name("soothe", leg_index=2)
        == "soothe:evaluate-gap-leg-2"
    )
    assert evaluate_assess_langfuse_run_display_name("soothe") == "soothe:evaluate-assess"


def test_planner_maps_evaluate_langfuse_phases() -> None:
    assert (
        LLMPlanner._evaluate_langfuse_phase_name("soothe", "evaluate-assess")
        == "soothe:evaluate-assess"
    )
    assert (
        LLMPlanner._evaluate_langfuse_phase_name("soothe", "evaluate-gap") == "soothe:evaluate-gap"
    )
    assert (
        LLMPlanner._evaluate_langfuse_phase_name("soothe", "evaluate-gap-leg-1")
        == "soothe:evaluate-gap-leg-1"
    )
    assert LLMPlanner._evaluate_langfuse_phase_name("soothe", "assess") is None
    assert LLMPlanner._evaluate_langfuse_phase_name("soothe", "analyze-gaps") is None


def test_planner_langfuse_config_pins_trace() -> None:
    cfg = MagicMock()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "demo"
    planner = LLMPlanner(model=MagicMock(), config=cfg, loop_id="loop-1")
    planner._pinned_trace_id = "trace-abc"

    with patch(
        "soothe.sloop.cognition.planner.merge_langfuse_runnable_config",
        return_value={"callbacks": ["h"]},
    ) as merge:
        out = planner._planner_langfuse_run_config(thread_id="thread-1", phase="evaluate-gap")

    assert out == {"callbacks": ["h"]}
    _args, kwargs = merge.call_args
    assert kwargs["pinned_trace_id"] == "trace-abc"
    assert kwargs["run_name"] == "demo:evaluate-gap"


@pytest.mark.asyncio
async def test_node_plan_evaluate_opens_langfuse_span_and_pins_planner() -> None:
    gap = MagicMock()
    gap.distance_from_goal = "moderate"
    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(return_value=gap)
    plan_phase._loop_planner = MagicMock()
    plan_phase._loop_planner._pinned_trace_id = None

    strange_loop = MagicMock()
    strange_loop.plan_phase = plan_phase
    strange_loop.loop_planner = plan_phase._loop_planner
    strange_loop._build_plan_context = MagicMock(return_value=MagicMock())
    strange_loop.config = MagicMock()
    loop = MagicMock()
    loop.plan_evaluate_gap_mode = "sequential"
    loop.plan_evaluate_gap_wall_clock_seconds = 90.0
    loop.plan_evaluate_gap_leg_timeout_seconds = 45.0
    loop.plan_evaluate_gap_max_concurrency = 4
    loop.plan_evaluate_gap_min_facets = 2
    strange_loop.config.agent.loop = loop

    state = LoopState(goal="g", thread_id="t", iteration=1)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    goal_trace = MagicMock()
    goal_trace.enabled = True
    goal_trace.trace_id = "trace-xyz"

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id=None,
        goal_trace=goal_trace,
    )

    span = MagicMock()

    @contextmanager
    def _fake_span(**_kwargs: object):
        yield span

    with (
        patch(
            "soothe.utils.observability.langfuse._evaluate_span.evaluate_langfuse_span",
            side_effect=_fake_span,
        ),
        patch(
            "soothe.sloop.stages.plan.evaluate.node_plan_assess",
            new=AsyncMock(return_value={"assess_route": "continue_generate"}),
        ),
    ):
        out = await node_plan_evaluate(ctx, {})

    assert out.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_gap is gap
    span.update.assert_called_once()
    # Pin restored after evaluate (prior was None).
    assert plan_phase._loop_planner._pinned_trace_id is None
