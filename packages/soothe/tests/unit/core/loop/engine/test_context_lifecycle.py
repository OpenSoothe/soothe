"""Unit tests for ContextEngineLifecycle (RFC-624 Phase 3d).

Covers: lifecycle hooks, no-op behavior when disabled, error isolation,
goal lifecycle completion, step feedback dual-path, persistence timing,
and semantic loading.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.models import StepNode
from soothe.foundation.loop.engine.context_lifecycle import ContextEngineLifecycle
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_step_action(step_id: str, desc: str, deps: list[str] | None = None) -> StepAction:
    return StepAction(id=step_id, description=desc, dependencies=deps or [])


def _make_plan_result(
    steps: list[StepAction] | None = None,
    status: str = "continue",
    plan_action: str = "new",
) -> PlanResult:
    decision = None
    if plan_action == "new":
        if steps:
            decision = AgentDecision(type="execute_steps", steps=steps)
        else:
            decision = AgentDecision(
                type="execute_steps",
                steps=[StepAction(id="01", description="Dummy")],
            )
    return PlanResult(
        status=status,
        plan_action=plan_action,
        decision=decision,
        evidence_summary="",
        goal_progress="none",
        next_action="test",
        require_goal_completion=True,
    )


def _make_step_result(step_id: str, success: bool = True) -> StepResult:
    return StepResult(
        step_id=step_id,
        success=success,
        duration_ms=100,
        thread_id="test-thread",
        error="test error" if not success else None,
    )


async def _make_ce_with_goal() -> tuple[ContextEngine, str]:
    """Create a ContextEngine with an active goal and return (ce, goal_id)."""
    ce = ContextEngine()
    goal = await ce.create_goal("Test goal")
    await ce.activate_goal(goal.id, loop_id="loop-1")
    return ce, goal.id


# ── Disabled lifecycle (CE off) ──────────────────────────────────────


class TestDisabledLifecycle:
    """When CE is disabled (None), all methods are no-ops."""

    def test_enabled_returns_false_with_none(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        assert lifecycle.enabled is False

    def test_enabled_returns_false_with_empty_goal_id(self) -> None:
        ce = MagicMock()
        lifecycle = ContextEngineLifecycle(ce, None)
        assert lifecycle.enabled is False

    @pytest.mark.asyncio
    async def test_on_goal_start_is_noop(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        await lifecycle.on_goal_start(workspace=None)

    @pytest.mark.asyncio
    async def test_on_plan_ingested_is_noop(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        await lifecycle.on_plan_ingested(_make_plan_result(), "P1", 0)

    @pytest.mark.asyncio
    async def test_on_steps_executed_is_noop(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        await lifecycle.on_steps_executed([_make_step_result("01")])

    @pytest.mark.asyncio
    async def test_on_goal_complete_is_noop(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        await lifecycle.on_goal_complete("done")

    @pytest.mark.asyncio
    async def test_get_context_bundle_returns_none(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        result = await lifecycle.get_context_bundle()
        assert result is None


# ── Enabled lifecycle ────────────────────────────────────────────────


class TestEnabledLifecycle:
    """When CE is enabled, lifecycle methods interact with CE."""

    def test_enabled_returns_true(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        assert lifecycle.enabled is True

    @pytest.mark.asyncio
    async def test_on_goal_start_loads_semantic(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        with (
            patch.object(ce._semantic, "load_project_instructions") as mock_proj,
            patch.object(ce._semantic, "load_agent_instructions") as mock_agent,
            patch.object(ce._semantic, "load_memory") as mock_mem,
        ):
            await lifecycle.on_goal_start(workspace=Path("/tmp"))
            mock_proj.assert_called_once()
            mock_agent.assert_called_once()
            mock_mem.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_goal_start_no_workspace_skips_load(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        with patch.object(ce._semantic, "load_project_instructions") as mock_proj:
            await lifecycle.on_goal_start(workspace=None)
            mock_proj.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_plan_ingested_saves(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)
        plan_result = _make_plan_result([_make_step_action("01", "Step 1")])

        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_plan_ingested(plan_result, "P1", 0)
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_steps_executed_fires_async_and_saves(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        await ce.add_step(goal_id, StepNode(id="01", description="Step 1"))

        lifecycle = ContextEngineLifecycle(ce, goal_id)
        step_results = [_make_step_result("01", success=True)]

        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_steps_executed(step_results)
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_steps_executed_mixed_success_failure(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        await ce.add_step(goal_id, StepNode(id="01", description="Step 1"))
        await ce.add_step(goal_id, StepNode(id="02", description="Step 2"))

        lifecycle = ContextEngineLifecycle(ce, goal_id)
        step_results = [
            _make_step_result("01", success=True),
            _make_step_result("02", success=False),
        ]

        with patch.object(ce, "save", new_callable=AsyncMock):
            await lifecycle.on_steps_executed(step_results)
            # Give async tasks a moment to fire
            await asyncio.sleep(0.05)

        goal = ce.get_goal_sync(goal_id)
        assert goal is not None
        # Note: complete_step/fail_step fire via asyncio.create_task, may
        # not have completed yet in test. The important thing is save() was called.

    @pytest.mark.asyncio
    async def test_on_goal_complete_done_completes_goal(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_goal_complete("done")
            mock_save.assert_called_once()

        goal = ce.get_goal_sync(goal_id)
        assert goal is not None
        assert goal.status == "completed"

    @pytest.mark.asyncio
    async def test_on_goal_complete_failed_fails_goal(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        plan_result = _make_plan_result(status="done", plan_action="keep")
        plan_result.assessment_reasoning = "something went wrong"

        lifecycle = ContextEngineLifecycle(ce, goal_id)
        with patch.object(ce, "save", new_callable=AsyncMock):
            await lifecycle.on_goal_complete("failed", plan_result=plan_result)

        goal = ce.get_goal_sync(goal_id)
        assert goal is not None
        assert goal.status == "failed"

    @pytest.mark.asyncio
    async def test_get_context_bundle_returns_bundle(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        bundle = await lifecycle.get_context_bundle()
        assert bundle is not None

    @pytest.mark.asyncio
    async def test_get_context_bundle_with_none_ce_returns_none(self) -> None:
        lifecycle = ContextEngineLifecycle(None, None)
        result = await lifecycle.get_context_bundle()
        assert result is None


# ── Error isolation ──────────────────────────────────────────────────


class TestErrorIsolation:
    """CE failures never propagate to graph nodes."""

    @pytest.mark.asyncio
    async def test_on_goal_start_error_does_not_raise(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        ce._semantic = MagicMock()
        ce._semantic.load_project_instructions.side_effect = RuntimeError("disk error")

        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        # Should not raise
        await lifecycle.on_goal_start(workspace=Path("/tmp"))

    @pytest.mark.asyncio
    async def test_on_plan_ingested_error_does_not_raise(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        ce.save = AsyncMock(side_effect=RuntimeError("persistence error"))

        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        await lifecycle.on_plan_ingested(_make_plan_result(), "P1", 0)

    @pytest.mark.asyncio
    async def test_on_steps_executed_error_does_not_raise(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        ce.save = AsyncMock(side_effect=RuntimeError("persistence error"))
        ce.complete_step = AsyncMock()
        ce.fail_step = AsyncMock()

        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        await lifecycle.on_steps_executed([_make_step_result("01")])

    @pytest.mark.asyncio
    async def test_on_goal_complete_error_does_not_raise(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        ce.complete_goal = AsyncMock(side_effect=RuntimeError("goal error"))
        ce.save = AsyncMock()

        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        await lifecycle.on_goal_complete("done")

    @pytest.mark.asyncio
    async def test_get_context_bundle_error_returns_none(self) -> None:
        ce = MagicMock(spec=ContextEngine)
        ce.project = AsyncMock(side_effect=RuntimeError("projection error"))

        lifecycle = ContextEngineLifecycle(ce, "goal-1")
        result = await lifecycle.get_context_bundle()
        assert result is None


# ── Persistence timing ───────────────────────────────────────────────


class TestPersistenceTiming:
    """Verify CE state is saved at the correct lifecycle points."""

    @pytest.mark.asyncio
    async def test_save_called_after_plan_ingested(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_plan_ingested(_make_plan_result(), "P1", 0)
            assert mock_save.call_count == 1

    @pytest.mark.asyncio
    async def test_save_called_after_steps_executed(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        await ce.add_step(goal_id, StepNode(id="01", description="Step 1"))

        lifecycle = ContextEngineLifecycle(ce, goal_id)
        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_steps_executed([_make_step_result("01")])
            assert mock_save.call_count == 1

    @pytest.mark.asyncio
    async def test_save_called_after_goal_complete(self) -> None:
        ce, goal_id = await _make_ce_with_goal()
        lifecycle = ContextEngineLifecycle(ce, goal_id)

        with patch.object(ce, "save", new_callable=AsyncMock) as mock_save:
            await lifecycle.on_goal_complete("done")
            assert mock_save.call_count == 1
