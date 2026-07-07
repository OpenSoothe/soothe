"""Pre-graph intake progress events surfaced before graph pump (IG-554)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.engine.strange_loop import StrangeLoop
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)


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


@pytest.mark.asyncio
async def test_run_with_progress_yields_intake_status_and_reasoning_pre_graph() -> None:
    """Pass 2 pre-classification must emit TUI progress before the graph starts."""
    sl = _make_strange_loop()

    pass1_result = MagicMock()
    pass1_result.is_task = True
    pass1_result.confidence = "high"
    pass1_result.reasoning = "Work request detected."

    preclassified = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll read the readme first.",
        goal_description="Summarize readme",
        task_complexity=TaskComplexity.SIMPLE,
    )

    intent_classifier = MagicMock()
    intent_classifier.classify_pass1 = AsyncMock(return_value=pass1_result)
    intent_classifier.classify_scope_intake = AsyncMock(return_value=preclassified)

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

    emitted: list[tuple[str, object]] = []

    async def _capture_emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    with (
        patch.object(sl, "_ce", None),
        patch("soothe.foundation.context.engine.ContextEngine", return_value=ce_instance),
        patch("soothe.foundation.context.persistence.sqlite_backend.SqliteContextPersistence"),
        patch(
            "soothe.foundation.sloop.state.persistence.runtime_paths.resolve_context_engine_db_path",
            return_value="/tmp/soothe-test.db",
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch(
            "soothe.foundation.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe.foundation.workspace.tool_path_resolution.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch("soothe.skills.catalog.parse_slash_skill_user_line", return_value=None),
        patch("soothe.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = _capture_emit
        runtime_ctx_cls.return_value = runtime_ctx
        am_cls.create = AsyncMock(return_value=mock_anchor)

        events: list[tuple[str, object]] = []
        gen = sl.run_with_progress(
            goal="summarize readme",
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
        )
        try:
            async for event in gen:
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass
        finally:
            await gen.aclose()

    assert ("plan_phase_status", {"label": "Interpreting goal"}) in events
    reasoning_events = [
        payload
        for event_type, payload in events
        if event_type == "intent_classified_reasoning" and isinstance(payload, dict)
    ]
    assert len(reasoning_events) == 1
    assert reasoning_events[0]["reasoning"] == "I'll read the readme first."
