"""In-graph intake classify progress events.

The graph INTAKE node is the sole classify call site. It projects the full CE
ledger (prior-goal completion + preamble).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    ResponseLanguage,
)
from soothe.sloop.strange_loop import StrangeLoop


def _make_strange_loop() -> StrangeLoop:
    config = MagicMock()
    config.agent.loop.working_memory.enabled = False
    config.agent.loop.context_engine = MagicMock()
    config.agent.loop.execute_prompt_ledger = MagicMock()
    config.agent.loop.execute_prompt_ledger.execute_ai_ledger_max_tokens = 0
    config.persistence.default_backend = "sqlite"
    config.persistence.postgres_base_dsn = None
    config.persistence.soothe_postgres_dsn = None
    config.home = "/tmp/soothe-test"
    config.observability.langfuse.enabled = False
    return StrangeLoop(core_agent=MagicMock(), config=config)


@pytest.mark.asyncio
async def test_run_with_progress_uses_in_graph_classify() -> None:
    """The graph INTAKE node is the sole classify call; no pre-graph gate."""
    sl = _make_strange_loop()

    intent_classifier = MagicMock()
    intent_classifier.classify_intake = AsyncMock(
        return_value=IntentClassification(
            intake_label=IntakeLabel.SIMPLE,
            task_complexity=TaskComplexity.SIMPLE,
            task_short_description="Propose 3 optimizations for Veritas arch",
            reasoning="Now I will propose three optimization points for Veritas arch.",
            response_language=ResponseLanguage.EN,
        )
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
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = AsyncMock()
        runtime_ctx_cls.return_value = runtime_ctx

        events: list[tuple[str, object]] = []
        gen = sl.run_with_progress(
            goal="review veritas arch and propose three optimize points. DO NOT impl",
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for event in gen:
                events.append(event)
        except Exception:
            pass
        finally:
            await gen.aclose()

    # state.intent starts None; the graph INTAKE node classifies. The
    # intent_classifier is wired to the runtime context so the (mocked-out)
    # graph node would call classify_intake with full ledger.
    loop_state = runtime_ctx_cls.call_args.kwargs["loop_state"]
    assert loop_state.intent is None
    ctx_kwargs = runtime_ctx_cls.call_args.kwargs
    assert ctx_kwargs["intent_classifier"] is intent_classifier
