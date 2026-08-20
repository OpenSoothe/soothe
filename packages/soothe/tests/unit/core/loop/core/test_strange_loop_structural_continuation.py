"""Tests for social-gate structural continuation bypass in StrangeLoop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.strange_loop import StrangeLoop


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


def _social_classifier(
    *,
    chitchat_response: str | None = None,
) -> MagicMock:
    social_gate_result = MagicMock()
    social_gate_result.is_task = False
    social_gate_result.confidence = "high"
    social_gate_result.reasoning = "Social cue."
    social_gate_result.social_response = chitchat_response
    social_gate_result.response_language = None
    intent_classifier = MagicMock()
    intent_classifier.classify_social_gate = AsyncMock(return_value=social_gate_result)
    if chitchat_response is not None:
        social_intent = MagicMock()
        social_intent.chitchat_response = chitchat_response
        intent_classifier.social_to_intent = MagicMock(return_value=social_intent)
    return intent_classifier


async def _drive_social_gate(
    *,
    goal: str,
    checkpoint: MagicMock,
    intent_classifier: MagicMock,
) -> list[tuple[str, object]]:
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

    with (
        patch.object(sl, "_ce", ce_instance),
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.sloop.strange_loop.CheckpointAnchorManager",
        ) as anchor_cls,
        patch(
            "soothe.sloop.orchestrator.runner.invoke_strange_loop_graph",
            new=AsyncMock(),
        ),
        patch(
            "soothe.sloop.strange_loop.LoopRuntimeContext",
        ) as runtime_ctx_cls,
        patch(
            "soothe_nano.workspace.workspace_paths.filesystem_virtual_mode_from_soothe_config",
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

    return events


@pytest.mark.asyncio
async def test_continue_keyword_bypasses_social_gate_fast_path() -> None:
    """Bare continue must resume via checkpoint, not chitchat finalize."""
    events = await _drive_social_gate(
        goal="continue",
        checkpoint=_running_checkpoint(),
        intent_classifier=_social_classifier(),
    )
    assert not any(event_type == "intent_fast_path" for event_type, _ in events)


@pytest.mark.asyncio
async def test_continue_without_intra_loop_checkpoint_keeps_intake_social() -> None:
    """Bare continue with empty this-loop checkpoint must keep intake social."""
    reply = "Sure, I'm ready when you are."
    intent_classifier = _social_classifier(chitchat_response=reply)
    events = await _drive_social_gate(
        goal="continue",
        checkpoint=_empty_checkpoint(),
        intent_classifier=intent_classifier,
    )
    fast = [payload for event_type, payload in events if event_type == "intent_fast_path"]
    assert fast
    assert fast[0]["chitchat_response"] == reply
    intent_classifier.social_to_intent.assert_called_once()


@pytest.mark.asyncio
async def test_embedded_continue_the_loop_bypasses_social_gate_fast_path() -> None:
    """Trailing loop-resume phrase must resume via checkpoint, not chitchat."""
    events = await _drive_social_gate(
        goal="Run the suite again. continue the loop",
        checkpoint=_running_checkpoint(),
        intent_classifier=_social_classifier(),
    )
    assert not any(event_type == "intent_fast_path" for event_type, _ in events)
