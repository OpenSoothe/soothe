"""Tests for GoalEngine async backoff scheduling (RFC-222 Q6)."""

from __future__ import annotations

import asyncio

import pytest

from soothe.foundation.autopilot.engine import GoalEngine
from soothe.foundation.autopilot.engine.models import BackoffDecision, EvidenceBundle


class _FakeReasoner:
    """Stand-in for GoalBackoffReasoner."""

    def __init__(self, *, target: str, raise_exc: bool = False, delay: float = 0.0) -> None:
        self.target = target
        self.raise_exc = raise_exc
        self.delay = delay
        self.calls = 0
        self.called_event = asyncio.Event()

    async def reason_backoff(self, goal_id, goals, failed_evidence):  # noqa: ANN001
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        self.called_event.set()
        if self.raise_exc:
            raise RuntimeError("reasoner blew up")
        return BackoffDecision(
            backoff_to_goal_id=self.target,
            reason="test backoff",
            new_directives=[],
            evidence_summary="condensed",
        )


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        structured={"x": 1},
        narrative="something failed",
        source="layer2_execute",
    )


class TestAsyncBackoffScheduling:
    @pytest.mark.asyncio
    async def test_fail_goal_returns_immediately_with_async_reasoner(self) -> None:
        """fail_goal must not block on the LLM call."""
        engine = GoalEngine(max_retries=0)
        parent = await engine.create_goal("parent", priority=80)
        child = await engine.create_goal("child", parent_id=parent.id)

        # Inject a slow reasoner — fail_goal should still return promptly.
        engine._backoff_reasoner = _FakeReasoner(target=parent.id, delay=0.5)

        result = await asyncio.wait_for(
            engine.fail_goal(child.id, evidence=_evidence(), allow_retry=False),
            timeout=0.2,
        )
        # fail_goal returns None when reasoner is scheduled async.
        assert result is None

        # Drain pending tasks so we don't leak.
        await asyncio.gather(*list(engine._backoff_tasks), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_immediate_transition_applied_before_reasoner_completes(self) -> None:
        engine = GoalEngine(max_retries=0)
        parent = await engine.create_goal("parent", priority=80)
        child = await engine.create_goal("child", parent_id=parent.id)
        engine._backoff_reasoner = _FakeReasoner(target=parent.id, delay=0.2)

        await engine.fail_goal(child.id, evidence=_evidence(), allow_retry=False)
        # Immediate state: child failed (no retries left).
        failed = await engine.get_goal(child.id)
        assert failed is not None
        assert failed.status == "failed"

        await asyncio.gather(*list(engine._backoff_tasks), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_async_decision_resets_target_to_pending(self) -> None:
        engine = GoalEngine(max_retries=0)
        parent = await engine.create_goal("parent", priority=80)
        child = await engine.create_goal("child", parent_id=parent.id)

        # First mark parent failed so backoff can revive it.
        parent.status = "failed"

        reasoner = _FakeReasoner(target=parent.id)
        engine._backoff_reasoner = reasoner

        await engine.fail_goal(child.id, evidence=_evidence(), allow_retry=False)

        # Wait for the in-flight backoff task to complete.
        await asyncio.gather(*list(engine._backoff_tasks), return_exceptions=True)

        revived = await engine.get_goal(parent.id)
        assert revived is not None
        assert revived.status == "pending"
        assert reasoner.calls == 1

    @pytest.mark.asyncio
    async def test_reasoner_exception_does_not_break_engine(self) -> None:
        engine = GoalEngine(max_retries=0)
        goal = await engine.create_goal("g")
        engine._backoff_reasoner = _FakeReasoner(target=goal.id, raise_exc=True)

        # Should not raise.
        await engine.fail_goal(goal.id, evidence=_evidence(), allow_retry=False)
        await asyncio.gather(*list(engine._backoff_tasks), return_exceptions=True)

        # Immediate transition stands.
        finished = await engine.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "failed"

    @pytest.mark.asyncio
    async def test_task_set_drained_after_completion(self) -> None:
        engine = GoalEngine(max_retries=0)
        goal = await engine.create_goal("g")
        engine._backoff_reasoner = _FakeReasoner(target=goal.id)

        await engine.fail_goal(goal.id, evidence=_evidence(), allow_retry=False)
        # At least one task scheduled.
        assert len(engine._backoff_tasks) >= 1

        await asyncio.gather(*list(engine._backoff_tasks), return_exceptions=True)
        # done callback removes them.
        await asyncio.sleep(0)
        assert len(engine._backoff_tasks) == 0
