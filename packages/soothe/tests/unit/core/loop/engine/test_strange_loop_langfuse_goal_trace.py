"""Pre-graph intake shares GoalLoopTrace with strange-loop-graph."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.engine.strange_loop import StrangeLoop
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.utils.observability.langfuse import GoalLoopTrace


def _make_strange_loop(*, langfuse_enabled: bool = True) -> StrangeLoop:
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
    config.observability.langfuse.enabled = langfuse_enabled
    config.observability.langfuse.trace_name = "soothe-dev"
    return StrangeLoop(core_agent=MagicMock(), config=config)


async def _drive_run_with_progress(
    sl: StrangeLoop,
    *,
    intent_classifier: Any,
    goal_trace: GoalLoopTrace,
    intake_span: Any,
    goal: str = "summarize readme",
) -> AsyncIterator[tuple[str, Any]]:
    """Run one turn with pre-graph IO stubbed, yielding the progress events."""
    ce_instance = MagicMock()
    ce_instance.load = AsyncMock(return_value=False)
    ce_instance.get_ledger_entries = MagicMock(return_value=[])
    ce_instance.get_all_goals = MagicMock(return_value=[])
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()
    ce_instance._semantic = MagicMock()

    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(
        return_value=MagicMock(status="idle", goal_history=[], thread_ids=[])
    )
    mock_sm.start_new_goal = MagicMock(return_value=MagicMock(goal_id="g1", iteration=0))
    mock_sm.save = AsyncMock()
    mock_sm.close = AsyncMock()

    mock_anchor = MagicMock()
    mock_anchor.close = AsyncMock()

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.context.store_sqlite.SqliteContextPersistence"),
        patch(
            "soothe.sloop.checkpoints.runtime_paths.resolve_context_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch("soothe.sloop.engine.strange_loop.CheckpointAnchorManager") as am_cls,
        patch(
            "soothe.sloop.engine.strange_loop.open_intake_langfuse_span",
            return_value=intake_span,
        ),
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch("soothe.sloop.engine.strange_loop.LoopRuntimeContext"),
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
        patch(
            "soothe.utils.observability.langfuse.SootheLangfuse.begin_goal_loop",
            return_value=goal_trace,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor)

        gen = sl.run_with_progress(
            goal=goal,
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for event in gen:
                yield event
        except Exception:
            pass
        finally:
            await gen.aclose()


@pytest.mark.asyncio
async def test_run_with_progress_pins_goal_trace_before_intake() -> None:
    """Social gate and graph ctx must share one GoalLoopTrace when Langfuse is enabled."""
    sl = _make_strange_loop()

    social_gate_result = MagicMock()
    social_gate_result.is_task = True
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "Work request."

    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)

    goal_trace = GoalLoopTrace(
        soothe_config=sl.config,
        trace_id="trace-goal-1",
        session_id="L1",
        loop_id="L1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    ce_instance = MagicMock()
    ce_instance.load = AsyncMock(return_value=False)
    ce_instance.get_ledger_entries = MagicMock(return_value=[])
    ce_instance.get_all_goals = MagicMock(return_value=[])
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()
    ce_instance._semantic = MagicMock()

    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(
        return_value=MagicMock(status="idle", goal_history=[], thread_ids=[])
    )
    mock_sm.start_new_goal = MagicMock(return_value=MagicMock(goal_id="g1", iteration=0))
    mock_sm.save = AsyncMock()
    mock_sm.close = AsyncMock()

    mock_anchor = MagicMock()
    mock_anchor.close = AsyncMock()

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.context.store_sqlite.SqliteContextPersistence"),
        patch(
            "soothe.sloop.checkpoints.runtime_paths.resolve_context_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.sloop.engine.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
        patch(
            "soothe.utils.observability.langfuse.SootheLangfuse.begin_goal_loop",
            return_value=goal_trace,
        ) as begin_goal_loop,
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = AsyncMock()
        runtime_ctx_cls.return_value = runtime_ctx
        am_cls.create = AsyncMock(return_value=mock_anchor)

        gen = sl.run_with_progress(
            goal="summarize readme",
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for _event in gen:
                pass
        except Exception:
            pass
        finally:
            await gen.aclose()

    begin_goal_loop.assert_called_once_with(session_id="L1", loop_id="L1")

    social_gate_kwargs = intent_classifier.classify_social_gate.await_args.kwargs
    assert social_gate_kwargs["goal_trace"] is goal_trace

    ctx_kwargs = runtime_ctx_cls.call_args.kwargs
    assert ctx_kwargs["goal_trace"] is goal_trace


@pytest.mark.asyncio
async def test_pre_graph_passes_nest_under_intake_span() -> None:
    """The social gate receives the span-scoped trace; the span closes when the task is confirmed."""
    sl = _make_strange_loop()

    social_gate_result = MagicMock()
    social_gate_result.is_task = True
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "Work request."
    social_gate_result.response_language = None

    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)

    goal_trace = GoalLoopTrace(
        soothe_config=sl.config,
        trace_id="trace-goal-1",
        session_id="L1",
        loop_id="L1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    intake_span = MagicMock()
    intake_span.parent_span_id = "span-intake-1"

    async for _ in _drive_run_with_progress(
        sl,
        intent_classifier=intent_classifier,
        goal_trace=goal_trace,
        intake_span=intake_span,
    ):
        pass

    for call in (intent_classifier.classify_social_gate,):
        assert call.await_args.kwargs["goal_trace"].intake_parent_span_id == "span-intake-1"
    intake_span.end.assert_any_call(output="task")


@pytest.mark.asyncio
async def test_social_fast_path_closes_intake_span_and_flushes() -> None:
    """No graph runs on a social turn, so intake must close and export itself."""
    sl = _make_strange_loop()

    social_gate_result = MagicMock()
    social_gate_result.is_task = False
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "Greeting."
    social_gate_result.response_language = None

    social_intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        reasoning="Greeting.",
        task_complexity=TaskComplexity.SIMPLE,
        chitchat_response="Doing well!",
    )

    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)
    intent_classifier.social_to_intent = MagicMock(return_value=social_intent)

    goal_trace = GoalLoopTrace(
        soothe_config=sl.config,
        trace_id="trace-goal-1",
        session_id="L1",
        loop_id="L1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    intake_span = MagicMock()
    intake_span.parent_span_id = "span-intake-1"

    with patch(
        "soothe.utils.observability.langfuse.SootheLangfuse.flush",
    ) as flush:
        events = [
            event
            async for event in _drive_run_with_progress(
                sl,
                intent_classifier=intent_classifier,
                goal_trace=goal_trace,
                intake_span=intake_span,
                goal="how are u",
            )
        ]

    assert any(event_type == "intent_fast_path" for event_type, _ in events)
    intake_span.end.assert_any_call(output="Doing well!")
    flush.assert_called_once()


@pytest.mark.asyncio
async def test_run_with_progress_skips_begin_goal_loop_when_langfuse_disabled() -> None:
    sl = _make_strange_loop(langfuse_enabled=False)

    social_gate_result = MagicMock()
    social_gate_result.is_task = True
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "Work request."

    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)

    ce_instance = MagicMock()
    ce_instance.load = AsyncMock(return_value=False)
    ce_instance.get_ledger_entries = MagicMock(return_value=[])
    ce_instance.get_all_goals = MagicMock(return_value=[])
    ce_instance.create_goal = AsyncMock(return_value=MagicMock(id="g1"))
    ce_instance.activate_goal = AsyncMock()
    ce_instance._semantic = MagicMock()

    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(
        return_value=MagicMock(status="idle", goal_history=[], thread_ids=[])
    )
    mock_sm.start_new_goal = MagicMock(return_value=MagicMock(goal_id="g1", iteration=0))
    mock_sm.save = AsyncMock()
    mock_sm.close = AsyncMock()

    mock_anchor = MagicMock()
    mock_anchor.close = AsyncMock()

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.context.store_sqlite.SqliteContextPersistence"),
        patch(
            "soothe.sloop.checkpoints.runtime_paths.resolve_context_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.sloop.engine.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe_nano.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
        patch(
            "soothe.utils.observability.langfuse.SootheLangfuse.begin_goal_loop",
        ) as begin_goal_loop,
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = AsyncMock()
        runtime_ctx_cls.return_value = runtime_ctx
        am_cls.create = AsyncMock(return_value=mock_anchor)

        gen = sl.run_with_progress(
            goal="summarize readme",
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for _event in gen:
                pass
        except Exception:
            pass
        finally:
            await gen.aclose()

    begin_goal_loop.assert_not_called()
    assert intent_classifier.classify_social_gate.await_args.kwargs["goal_trace"] is None
    assert runtime_ctx_cls.call_args.kwargs["goal_trace"] is None
