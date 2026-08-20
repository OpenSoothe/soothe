"""Pre-graph social-gate progress events surfaced before graph pump."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.engine.strange_loop import StrangeLoop, _task_intent_from_pre_graph_intake
from soothe.sloop.intention.models import (
    IntakeConfidence,
    IntakeLabel,
    IntakeLLMResult,
    IntentClassification,
    ResponseLanguage,
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
    return StrangeLoop(core_agent=MagicMock(), config=config)


@pytest.mark.asyncio
async def test_run_with_progress_yields_intake_status_pre_graph() -> None:
    """The social gate emits a TUI cognition status before the graph runs."""
    sl = _make_strange_loop()

    social_gate_result = MagicMock()
    social_gate_result.is_task = True
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "This is a request to summarize the readme."

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

    emitted: list[tuple[str, object]] = []

    async def _capture_emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

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
                if len(events) >= 4:
                    break
        except Exception:
            pass
        finally:
            await gen.aclose()

    assert ("plan_phase_status", {"label": "Interpreting goal"}) in events


def test_task_intent_from_pre_graph_intake_reuses_llm_result() -> None:
    """A task gate result becomes loop intent without a second model call."""
    result = IntakeLLMResult(
        is_task=True,
        confidence=IntakeConfidence.HIGH,
        social_response=None,
        task_complexity=TaskComplexity.SIMPLE,
        task_short_description="Propose 3 optimizations for Veritas arch",
        response_language=ResponseLanguage.EN,
        reasoning="Now I will propose three optimization points for Veritas arch.",
    )
    intent = _task_intent_from_pre_graph_intake(MagicMock(), result, "review veritas")
    assert intent is not None
    assert intent.intake_label == IntakeLabel.SIMPLE
    assert intent.task_complexity == TaskComplexity.SIMPLE
    assert intent.task_short_description == "Propose 3 optimizations for Veritas arch"


def test_task_intent_from_pre_graph_intake_skips_social() -> None:
    result = IntakeLLMResult(
        is_task=False,
        confidence=IntakeConfidence.HIGH,
        social_response="Hi!",
        response_language=ResponseLanguage.EN,
        reasoning="Greeting.",
    )
    assert _task_intent_from_pre_graph_intake(MagicMock(), result, "hi") is None


@pytest.mark.asyncio
async def test_run_with_progress_reuses_social_gate_task_as_loop_intent() -> None:
    """Graph entry must not classify again when the social gate already returned a task."""
    sl = _make_strange_loop()

    social_gate_result = IntakeLLMResult(
        is_task=True,
        confidence=IntakeConfidence.HIGH,
        social_response=None,
        task_complexity=TaskComplexity.SIMPLE,
        task_short_description="Propose 3 optimizations for Veritas arch",
        response_language=ResponseLanguage.EN,
        reasoning="Now I will propose three optimization points for Veritas arch.",
    )

    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)
    intent_classifier.classify_intake = AsyncMock()

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
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = AsyncMock()
        runtime_ctx_cls.return_value = runtime_ctx
        am_cls.create = AsyncMock(return_value=mock_anchor)

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

    intent_classifier.classify_social_gate.assert_awaited_once()
    intent_classifier.classify_intake.assert_not_called()
    loop_state = runtime_ctx_cls.call_args.kwargs["loop_state"]
    assert isinstance(loop_state.intent, IntentClassification)
    assert loop_state.intent.task_short_description == ("Propose 3 optimizations for Veritas arch")
    assert loop_state.intent.task_complexity == TaskComplexity.SIMPLE
    assert any(
        event_type == "intent_classified_reasoning"
        and isinstance(payload, dict)
        and payload.get("reasoning")
        == "Now I will propose three optimization points for Veritas arch."
        for event_type, payload in events
    )
