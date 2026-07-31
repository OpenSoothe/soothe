"""A ``/skill:`` submission owns execution and suppresses specialist routing (IG-669)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.engine.strange_loop import StrangeLoop
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
    build_loop_routing_classification,
)
from soothe.sloop.orchestrator.routing import route_by_intent
from soothe.sloop.stages.preprocess.enter_loop import node_init_or_resume


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    return None


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


async def _drive_intake(
    *,
    goal: str,
    preferred_subagent: str | None,
    parsed_skill: object | None,
) -> MagicMock:
    """Run ``run_with_progress`` through intake and return the ``LoopRuntimeContext`` mock."""
    sl = _make_strange_loop()

    pass1_result = MagicMock()
    pass1_result.is_task = True
    pass1_result.confidence = "high"
    pass1_result.reasoning = "Work request detected."

    intent_classifier = MagicMock()
    intent_classifier.classify_pass1 = AsyncMock(return_value=pass1_result)
    intent_classifier.classify_scope_intake = AsyncMock(
        return_value=IntentClassification(
            intake_label=IntakeLabel.SIMPLE,
            reasoning="I'll start the research.",
            task_complexity=TaskComplexity.SIMPLE,
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
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch("soothe.sloop.engine.strange_loop.LoopRuntimeContext") as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
            return_value=False,
        ),
        patch(
            "soothe_nano.skills.catalog.parse_slash_skill_user_line",
            return_value=parsed_skill,
        ),
        patch("soothe_nano.skills.catalog.try_expand_slash_skill_user_line", return_value=None),
    ):
        runtime_ctx = MagicMock()
        runtime_ctx.emit = _noop_emit
        runtime_ctx_cls.return_value = runtime_ctx
        am_cls.create = AsyncMock(return_value=mock_anchor)

        gen = sl.run_with_progress(
            goal=goal,
            thread_id="t1",
            workspace=None,
            max_iterations=1,
            loop_id="L1",
            intent_classifier=intent_classifier,
            preferred_subagent=preferred_subagent,
            routing_classification=build_loop_routing_classification(None, preferred_subagent),
        )
        async for _event in gen:
            pass

    return runtime_ctx_cls


@pytest.mark.asyncio
async def test_slash_skill_clears_specialist_routing_hint() -> None:
    """Regression: ``/skill:`` plus an inferred specialist must not take the wired route."""
    runtime_ctx_cls = await _drive_intake(
        goal="Begin research on the seed paper",
        preferred_subagent="academic_research",
        parsed_skill=("omr-bootstrap", "Begin research on the seed paper"),
    )

    kwargs = runtime_ctx_cls.call_args.kwargs
    assert kwargs["preferred_subagent"] is None
    routing = kwargs["loop_state"].routing_classification
    assert routing is None or routing.preferred_subagent is None


@pytest.mark.asyncio
async def test_slash_specialist_without_skill_keeps_routing_hint() -> None:
    """A bare ``/academic_research`` submission still reaches the wired specialist."""
    runtime_ctx_cls = await _drive_intake(
        goal="Begin research on the seed paper",
        preferred_subagent="academic_research",
        parsed_skill=None,
    )

    kwargs = runtime_ctx_cls.call_args.kwargs
    assert kwargs["preferred_subagent"] == "academic_research"
    routing = kwargs["loop_state"].routing_classification
    assert routing is not None
    assert routing.preferred_subagent == "academic_research"


@pytest.mark.asyncio
async def test_enter_loop_skips_wired_branch_without_slash_hint() -> None:
    """With no explicit hint, intake routes to the normal plan/execute path."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    ctx = SimpleNamespace(
        loop_state=SimpleNamespace(
            intent=intent,
            routing_classification=build_loop_routing_classification(intent, None),
            goal="research the seed paper",
            goal_user_submission="research the seed paper",
        ),
        preferred_subagent=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        checkpoint=None,
        ce=None,
        ce_goal_id=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_noop_emit,
    )
    result = await node_init_or_resume(ctx, {})  # type: ignore[arg-type]
    assert result["intent_route"] != "wired_subagent"
    assert route_by_intent(result) != "delegate"


@pytest.mark.asyncio
async def test_stray_pass2_wire_subagent_field_is_ignored() -> None:
    """A model that still emits ``wire_subagent`` cannot influence routing."""
    intent = IntentClassification.model_validate(
        {
            "intake_label": IntakeLabel.SIMPLE,
            "requires_tool_use": True,
            "task_complexity": TaskComplexity.SIMPLE,
            "wire_subagent": "academic_research",
        }
    )
    assert not hasattr(intent, "wire_subagent")

    routing = build_loop_routing_classification(intent, preferred_subagent=None)
    assert routing is not None
    assert routing.preferred_subagent is None
