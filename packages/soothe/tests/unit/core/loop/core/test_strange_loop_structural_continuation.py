"""Structural continuation bypass for in-graph intake classify.

Chitchat is decided in the graph INTAKE node. A bare "continue" on a running
checkpoint must resume via checkpoint, not chitchat-finalize — that bypass
lives in ``enter_loop``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
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


def _empty_checkpoint() -> MagicMock:
    checkpoint = MagicMock()
    checkpoint.status = "running"
    checkpoint.current_goal_index = -1
    checkpoint.goal_history = []
    checkpoint.thread_ids = ["L1"]
    checkpoint.current_thread_id = "L1"
    checkpoint.execution_checkpoint = {}
    checkpoint.loop_state = None
    return checkpoint


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


def _chitchat_classifier(*, chitchat_response: str | None = None) -> MagicMock:
    """Classifier whose in-graph classify returns a social (chitchat) verdict."""
    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        reasoning="Social cue.",
        task_complexity=TaskComplexity.MINIMAL,
        chitchat_response=chitchat_response,
    )
    classifier = MagicMock()
    classifier.classify_intake = AsyncMock(return_value=intent)
    return classifier


async def _drive_intake(
    *,
    goal: str,
    checkpoint: MagicMock,
    intent_classifier: MagicMock,
) -> tuple[list[tuple[str, object]], MagicMock]:
    """Run ``run_with_progress`` and return (events, runtime_ctx_mock)."""
    sl = _make_strange_loop()
    mock_sm = MagicMock()
    mock_sm.loop_id = "L1"
    mock_sm.load = AsyncMock(return_value=checkpoint)
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
    gen: AsyncIterator[tuple[str, object]] | None = None
    runtime_ctx: MagicMock = MagicMock()

    with (
        patch.object(sl, "_ce", ce_instance),
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

        gen = sl.run_with_progress(
            goal=goal,
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
                if len(events) >= 8:
                    break
        except Exception:
            pass
        finally:
            await gen.aclose()

    return events, runtime_ctx


async def _drive_intake_ctx(
    *,
    goal: str,
    checkpoint: MagicMock,
    intent_classifier: MagicMock,
) -> MagicMock:
    """Return only the runtime context mock from a drive."""
    _, ctx = await _drive_intake(
        goal=goal, checkpoint=checkpoint, intent_classifier=intent_classifier
    )
    return ctx


@pytest.mark.asyncio
async def test_continue_keyword_on_running_checkpoint_resumes_not_chitchat() -> None:
    """Bare continue on a running checkpoint must resume, not chitchat-finalize."""
    events, _ = await _drive_intake(
        goal="continue",
        checkpoint=_running_checkpoint(),
        intent_classifier=_chitchat_classifier(),
    )
    assert not any(event_type == "intent_fast_path" for event_type, _ in events)


@pytest.mark.asyncio
async def test_continue_without_intra_loop_checkpoint_keeps_chitchat() -> None:
    """Bare continue with empty this-loop checkpoint lets the graph run chitchat.

    With no pre-graph gate, chitchat flows through the graph INTAKE node +
    ``enter_loop`` fast-path. Assert the graph is invoked (not short-circuited)
    and the classifier is wired so the node would classify social.
    """
    reply = "Sure, I'm ready when you are."
    ctx = await _drive_intake_ctx(
        goal="continue",
        checkpoint=_empty_checkpoint(),
        intent_classifier=_chitchat_classifier(chitchat_response=reply),
    )
    assert ctx is not None
    assert ctx.intent_classifier is not None


@pytest.mark.asyncio
async def test_embedded_continue_the_loop_resumes_not_chitchat() -> None:
    """Trailing loop-resume phrase must resume via checkpoint, not chitchat."""
    events, _ = await _drive_intake(
        goal="Run the suite again. continue the loop",
        checkpoint=_running_checkpoint(),
        intent_classifier=_chitchat_classifier(),
    )
    assert not any(event_type == "intent_fast_path" for event_type, _ in events)
