"""Goal-loop trace pinning for in-graph intake classify.

The pre-graph social gate is gone; intake classification runs in the graph
INTAKE node. The goal trace is pinned before the graph runs so the classify
LLM and ``strange-loop-graph`` share one trace.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.strange_loop import StrangeLoop
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


def _make_classifier(*, is_task: bool = True) -> MagicMock:
    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT if not is_task else IntakeLabel.SIMPLE,
        reasoning="Work request." if is_task else "Greeting.",
        task_complexity=TaskComplexity.SIMPLE,
        chitchat_response="Doing well!" if not is_task else None,
    )
    classifier = MagicMock()
    classifier.classify_intake = AsyncMock(return_value=intent)
    return classifier


def _common_patches(sl: StrangeLoop):
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

    return ce_instance, mock_sm, mock_anchor


@pytest.mark.asyncio
async def test_run_with_progress_pins_goal_trace_before_graph() -> None:
    """Graph ctx receives the pinned GoalLoopTrace when Langfuse is enabled."""
    sl = _make_strange_loop()

    intent_classifier = _make_classifier(is_task=True)
    goal_trace = GoalLoopTrace(
        soothe_config=sl.config,
        trace_id="trace-goal-1",
        session_id="L1",
        loop_id="L1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    ce_instance, mock_sm, mock_anchor = _common_patches(sl)

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.context.store_sqlite.SqliteContextPersistence"),
        patch(
            "soothe.sloop.checkpoints.runtime_paths.resolve_context_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch("soothe.sloop.strange_loop.CheckpointAnchorManager") as am_cls,
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch("soothe.sloop.strange_loop.LoopRuntimeContext") as runtime_ctx_cls,
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
    ctx_kwargs = runtime_ctx_cls.call_args.kwargs
    assert ctx_kwargs["goal_trace"] is goal_trace


@pytest.mark.asyncio
async def test_run_with_progress_skips_begin_goal_loop_when_langfuse_disabled() -> None:
    sl = _make_strange_loop(langfuse_enabled=False)

    intent_classifier = _make_classifier(is_task=True)
    ce_instance, mock_sm, mock_anchor = _common_patches(sl)

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.context.store_sqlite.SqliteContextPersistence"),
        patch(
            "soothe.sloop.checkpoints.runtime_paths.resolve_context_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch("soothe.sloop.strange_loop.CheckpointAnchorManager") as am_cls,
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch("soothe.sloop.strange_loop.LoopRuntimeContext") as runtime_ctx_cls,
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
    assert runtime_ctx_cls.call_args.kwargs["goal_trace"] is None
