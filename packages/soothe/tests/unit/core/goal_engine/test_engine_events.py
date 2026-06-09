"""Tests for GoalEngine ↔ InternalEventBus wiring (RFC-222)."""

from __future__ import annotations

from typing import Any

import pytest

from soothe.foundation.autopilot.engine import GoalEngine
from soothe.foundation.autopilot.engine.models import EvidenceBundle
from soothe.foundation.events.internal_bus import InternalEventBus


def _make_evidence(narrative: str = "x") -> EvidenceBundle:
    return EvidenceBundle(structured={}, narrative=narrative, source="layer2_execute")


class _Recorder:
    """Subscribes to internal events and records them in order."""

    def __init__(self, bus: InternalEventBus) -> None:
        self.events: list[Any] = []
        for event_type in (
            "soothe.internal.goal.state_changed",
            "soothe.internal.goal.ready",
            "soothe.internal.file.released",
        ):
            bus.subscribe(event_type, self._on_event)

    async def _on_event(self, event: Any) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


class TestSoloModeNoEmission:
    """When constructed without a bus, GoalEngine must be silent."""

    @pytest.mark.asyncio
    async def test_create_goal_emits_nothing_in_solo_mode(self) -> None:
        engine = GoalEngine()  # no internal_bus
        # Should not raise / hang even though there are no subscribers anywhere.
        goal = await engine.create_goal("solo")
        assert goal.status == "pending"

    @pytest.mark.asyncio
    async def test_complete_goal_emits_nothing_in_solo_mode(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("solo")
        await engine.complete_goal(goal.id)
        # No exception, no subscribers — verifies the None-bus branch.


class TestStateChangeEvents:
    """Verify InternalGoalStateChangedEvent fires for every transition."""

    @pytest.mark.asyncio
    async def test_create_emits_none_to_pending(self) -> None:
        bus = InternalEventBus()
        recorder = _Recorder(bus)
        engine = GoalEngine(internal_bus=bus)

        await engine.create_goal("first")

        change = next(e for e in recorder.events if e.type == "soothe.internal.goal.state_changed")
        assert change.old_status == "none"
        assert change.new_status == "pending"
        assert change.reason == "created"

    @pytest.mark.asyncio
    async def test_ready_goals_emits_per_goal_change_plus_ready(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)

        await engine.create_goal("a", priority=50)
        await engine.create_goal("b", priority=80)

        # Start recording AFTER creation so we isolate ready_goals output.
        recorder = _Recorder(bus)
        ready = await engine.ready_goals(limit=2)

        assert len(ready) == 2
        state_changes = [
            e for e in recorder.events if e.type == "soothe.internal.goal.state_changed"
        ]
        assert len(state_changes) == 2
        for change in state_changes:
            assert change.old_status == "pending"
            assert change.new_status == "active"
            assert change.reason == "ready_activated"

        ready_events = [e for e in recorder.events if e.type == "soothe.internal.goal.ready"]
        assert len(ready_events) == 1
        assert ready_events[0].count == 2
        assert sorted(ready_events[0].goal_ids) == sorted(g.id for g in ready)

    @pytest.mark.asyncio
    async def test_complete_emits_change_and_releases_locks(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)

        goal = await engine.create_goal("done")
        engine.file_registry.acquire_lock("/x", goal.id, "loop-A", "edit")
        engine.file_registry.acquire_lock("/y", goal.id, "loop-A", "edit")

        recorder = _Recorder(bus)
        await engine.complete_goal(goal.id)

        released = [e for e in recorder.events if e.type == "soothe.internal.file.released"]
        assert sorted(e.file_path for e in released) == ["/x", "/y"]

        change = next(e for e in recorder.events if e.type == "soothe.internal.goal.state_changed")
        assert change.old_status == "pending"
        assert change.new_status == "completed"
        assert change.reason == "completed"
        assert engine.file_registry.lock_count() == 0

    @pytest.mark.asyncio
    async def test_fail_goal_retry_emits_pending_change(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)

        goal = await engine.create_goal("flaky")
        # Activate first so the failure is from "active"
        await engine.ready_goals(limit=1)

        recorder = _Recorder(bus)
        await engine.fail_goal(goal.id, evidence=_make_evidence("boom"))

        change = next(e for e in recorder.events if e.type == "soothe.internal.goal.state_changed")
        assert change.old_status == "active"
        assert change.new_status == "pending"
        assert change.reason == "retry"

    @pytest.mark.asyncio
    async def test_fail_goal_permanent_emits_failed_change(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)

        goal = await engine.create_goal("doomed", max_retries=0)
        await engine.ready_goals(limit=1)

        recorder = _Recorder(bus)
        await engine.fail_goal(goal.id, evidence=_make_evidence("nope"))

        change = next(e for e in recorder.events if e.type == "soothe.internal.goal.state_changed")
        assert change.old_status == "active"
        assert change.new_status == "failed"
        assert change.reason == "failed"

    @pytest.mark.asyncio
    async def test_validate_suspend_block_reactivate_emit(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)

        goal = await engine.create_goal("flow")
        recorder = _Recorder(bus)

        await engine.validate_goal(goal.id)
        await engine.suspend_goal(goal.id, reason="budget")
        await engine.reactivate_goal(goal.id)
        await engine.block_goal(goal.id, reason="external")
        await engine.reactivate_goal(goal.id)

        changes = [e for e in recorder.events if e.type == "soothe.internal.goal.state_changed"]
        assert [(c.old_status, c.new_status) for c in changes] == [
            ("pending", "validated"),
            ("validated", "suspended"),
            ("suspended", "pending"),
            ("pending", "blocked"),
            ("blocked", "pending"),
        ]


class TestPeekReadyGoals:
    """peek_ready_goals must be read-only."""

    @pytest.mark.asyncio
    async def test_peek_does_not_mutate_status(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("untouched")

        result = await engine.peek_ready_goals(limit=5)

        assert len(result) == 1
        assert result[0].id == goal.id
        assert goal.status == "pending"  # still pending

    @pytest.mark.asyncio
    async def test_peek_does_not_emit_events(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)
        await engine.create_goal("p")
        recorder = _Recorder(bus)

        await engine.peek_ready_goals(limit=5)

        assert recorder.events == []

    @pytest.mark.asyncio
    async def test_peek_then_claim_atomic(self) -> None:
        bus = InternalEventBus()
        engine = GoalEngine(internal_bus=bus)
        await engine.create_goal("a", priority=50)
        b = await engine.create_goal("b", priority=90)
        candidates = await engine.peek_ready_goals(limit=2)
        assert {c.id for c in candidates} == {b.id, candidates[1].id}
        # Statuses still pending
        assert all(c.status == "pending" for c in candidates)

        recorder = _Recorder(bus)
        # Claim by ID — should transition only that goal.
        claimed = await engine.claim_goal(b.id, loop_id="loop-A")
        assert claimed is not None
        assert claimed.status == "active"
        assert claimed.assigned_loop_id == "loop-A"

        changes = [e for e in recorder.events if e.type == "soothe.internal.goal.state_changed"]
        assert len(changes) == 1
        assert changes[0].goal_id == b.id
        assert changes[0].old_status == "pending"
        assert changes[0].new_status == "active"
        assert changes[0].reason == "claimed"

    @pytest.mark.asyncio
    async def test_claim_returns_none_for_missing_goal(self) -> None:
        engine = GoalEngine()
        result = await engine.claim_goal("does-not-exist", loop_id="loop-A")
        assert result is None

    @pytest.mark.asyncio
    async def test_claim_returns_none_for_terminal_goal(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("done")
        await engine.complete_goal(goal.id)
        result = await engine.claim_goal(goal.id, loop_id="loop-A")
        assert result is None
