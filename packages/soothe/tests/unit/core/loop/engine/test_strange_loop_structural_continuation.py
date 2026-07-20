"""Tests for Pass1 structural continuation bypass in StrangeLoop (IG-558)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.engine.strange_loop import StrangeLoop
from soothe.foundation.sloop.intention.models import IntakeLabel, TaskComplexity
from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry


def _make_strange_loop() -> StrangeLoop:
    config = MagicMock()
    config.agent.loop.working_memory.enabled = False
    config.agent.loop.goal_context = MagicMock()
    config.agent.loop.context_engine = MagicMock()
    config.agent.loop.execute_prompt_ledger = MagicMock()
    config.agent.loop.execute_prompt_ledger.execute_ai_ledger_max_tokens = 0
    config.persistence.default_backend = "sqlite"
    config.persistence.postgres_base_dsn = None
    config.persistence.soothe_postgres_dsn = None
    config.home = "/tmp/soothe-test"
    config.observability.langfuse.enabled = False
    return StrangeLoop(core_agent=MagicMock(), loop_planner=MagicMock(), config=config)


def _running_checkpoint() -> MagicMock:
    now = datetime.now(UTC)
    goal = GoalIndexEntry(
        goal_id="goal-0",
        status="running",
        thread_id="L1",
        started_at=now,
        completed_at=None,
        duration_ms=0,
        tokens_used=0,
    )
    checkpoint = MagicMock()
    checkpoint.status = "running"
    checkpoint.current_goal_index = 0
    checkpoint.goal_history = [goal]
    checkpoint.thread_ids = ["L1"]
    checkpoint.current_thread_id = "L1"
    checkpoint.execution_checkpoint = {"iteration": 1}
    return checkpoint


@pytest.mark.asyncio
async def test_continue_keyword_bypasses_pass1_social_fast_path() -> None:
    """Bare continue must resume via checkpoint, not chitchat finalize."""
    sl = _make_strange_loop()

    pass1_result = MagicMock()
    pass1_result.is_task = False
    pass1_result.confidence = "high"
    pass1_result.reasoning = "Social cue."

    intent_classifier = MagicMock()
    intent_classifier.classify_pass1 = AsyncMock(return_value=pass1_result)
    intent_classifier.classify_scope_intake = AsyncMock(
        return_value=MagicMock(
            intake_label=IntakeLabel.SIMPLE,
            reasoning="Resume loop.",
            task_complexity=TaskComplexity.SIMPLE,
        )
    )

    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=_running_checkpoint())
    mock_sm.save = AsyncMock()
    mock_sm.close = AsyncMock()

    ce_instance = MagicMock()
    ce_instance.load = AsyncMock(return_value=True)
    ce_instance.get_ledger_entries = MagicMock(return_value=[])
    ce_instance.get_all_goals = MagicMock(return_value=[])
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()
    ce_instance._semantic = MagicMock()

    emitted: list[tuple[str, object]] = []

    async def _capture_emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    with (
        patch.object(sl, "_ce", ce_instance),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as anchor_cls,
        patch(
            "soothe.foundation.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.tool_path_resolution.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        anchor_cls.create = AsyncMock(return_value=MagicMock(close=AsyncMock()))
        runtime_ctx = MagicMock()
        runtime_ctx.emit = _capture_emit
        runtime_ctx_cls.return_value = runtime_ctx

        events: list[tuple[str, object]] = []
        gen = sl.run_with_progress(
            goal="continue",
            thread_id="L1",
            workspace=None,
            max_iterations=3,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for event in gen:
                events.append(event)
                if any(event_type == "intent_fast_path" for event_type, _ in events):
                    break
                if len(events) >= 6:
                    break
        except Exception:
            pass
        finally:
            await gen.aclose()

    assert not any(event_type == "intent_fast_path" for event_type, _ in events)
    intent_classifier.classify_scope_intake.assert_awaited()


@pytest.mark.asyncio
async def test_embedded_continue_the_loop_bypasses_pass1_social_fast_path() -> None:
    """Trailing loop-resume phrase must resume via checkpoint, not chitchat."""
    sl = _make_strange_loop()

    pass1_result = MagicMock()
    pass1_result.is_task = False
    pass1_result.confidence = "high"
    pass1_result.reasoning = "Social cue."

    intent_classifier = MagicMock()
    intent_classifier.classify_pass1 = AsyncMock(return_value=pass1_result)
    intent_classifier.classify_scope_intake = AsyncMock(
        return_value=MagicMock(
            intake_label=IntakeLabel.SIMPLE,
            reasoning="Resume loop.",
            task_complexity=TaskComplexity.SIMPLE,
        )
    )

    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=_running_checkpoint())
    mock_sm.save = AsyncMock()
    mock_sm.close = AsyncMock()

    ce_instance = MagicMock()
    ce_instance.load = AsyncMock(return_value=True)
    ce_instance.get_ledger_entries = MagicMock(return_value=[])
    ce_instance.get_all_goals = MagicMock(return_value=[])
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()
    ce_instance._semantic = MagicMock()

    events: list[tuple[str, object]] = []

    with (
        patch.object(sl, "_ce", ce_instance),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as anchor_cls,
        patch(
            "soothe.foundation.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.tool_path_resolution.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        anchor_cls.create = AsyncMock(return_value=MagicMock(close=AsyncMock()))
        runtime_ctx = MagicMock()
        runtime_ctx.emit = AsyncMock()
        runtime_ctx_cls.return_value = runtime_ctx

        gen = sl.run_with_progress(
            goal="Run the suite again. continue the loop",
            thread_id="L1",
            workspace=None,
            max_iterations=3,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for event in gen:
                events.append(event)
                if any(event_type == "intent_fast_path" for event_type, _ in events):
                    break
                if len(events) >= 6:
                    break
        except Exception:
            pass
        finally:
            await gen.aclose()

    assert not any(event_type == "intent_fast_path" for event_type, _ in events)
    intent_classifier.classify_scope_intake.assert_awaited()
