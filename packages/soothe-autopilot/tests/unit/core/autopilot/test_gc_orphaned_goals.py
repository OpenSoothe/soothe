"""Tests for the autopilot goal-GC scan and stale-reservation reconciliation.

Covers two leak-prevention mechanisms added to close the "ghost-active
worker + stale WorkspaceReservation" failure and the "orphaned children
under a terminal job root" failure:

- ``AutopilotService.gc_orphaned_goals`` — cancels non-terminal goals
  whose job root is already terminal.
- ``AutopilotService.reconcile_stale_reservations`` — releases
  WorkspaceReservation entries and ghost-active WorkerPool slots when a
  goal's completion chunk never reached ``_consume_worker_stream``.
- ``AutopilotService.reconcile_stale_worker`` — the daemon-side stale-loop
  reconciler hook that frees a worker slot + reservation for a demoted
  loop and re-queues/cancels the stranded goal.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from soothe_autopilot import AutopilotService
from soothe_autopilot.workers.workspace_reservation import WorkspaceReservation

from .fakes import IdleFakeFactory


def _service(*, gc_enabled: bool = True) -> AutopilotService:
    return AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2, gc_enabled=gc_enabled),
        internal_bus=InternalEventBus(),
        monitor=None,
        runner_factory=IdleFakeFactory(),
        workspace_reservation=WorkspaceReservation(enabled=True, strict_overlap=True),
    )


class TestGCOrphanedGoals:
    @pytest.mark.asyncio
    async def test_no_goals_returns_zero(self) -> None:
        svc = _service()
        assert await svc.gc_orphaned_goals() == 0

    @pytest.mark.asyncio
    async def test_pending_goal_under_completed_root_is_cancelled(self) -> None:
        """A pending child whose job root is completed is an orphan → cancelled."""
        svc = _service()
        root = await svc._ce.create_goal("root job", source="user")
        child = await svc._ce.create_goal("orphan child", parent_id=root.id, source="user")
        # Mark the root completed — child is now an orphan.
        await svc._ce.complete_goal(root.id)
        assert child.status == "pending"

        cancelled = await svc.gc_orphaned_goals()

        assert cancelled == 1
        child_after = await svc._ce.get_goal(child.id)
        assert child_after.status == "cancelled"

    @pytest.mark.asyncio
    async def test_pending_goal_under_active_root_is_kept(self) -> None:
        """A pending child whose root is still active must NOT be cancelled."""
        svc = _service()
        root = await svc._ce.create_goal("root job", source="user")
        child = await svc._ce.create_goal("active child", parent_id=root.id, source="user")
        svc._ce.claim_goal(root.id, loop_id="loop-1")
        assert root.status == "active"

        cancelled = await svc.gc_orphaned_goals()

        assert cancelled == 0
        assert (await svc._ce.get_goal(child.id)).status == "pending"

    @pytest.mark.asyncio
    async def test_gc_skips_already_terminal_children(self) -> None:
        svc = _service()
        root = await svc._ce.create_goal("root job", source="user")
        await svc._ce.create_goal("done child", parent_id=root.id, source="user")
        await svc._ce.complete_goal(root.id)
        # All children terminal already.
        for goal in await svc._ce.list_goals():
            if goal.parent_id == root.id and goal.status != "completed":
                await svc._ce.complete_goal(goal.id)

        assert await svc.gc_orphaned_goals() == 0

    @pytest.mark.asyncio
    async def test_gc_disabled_returns_zero(self) -> None:
        svc = _service(gc_enabled=False)
        root = await svc._ce.create_goal("root job", source="user")
        await svc._ce.create_goal("orphan child", parent_id=root.id, source="user")
        await svc._ce.complete_goal(root.id)

        assert await svc.gc_orphaned_goals() == 0
        # Child is still pending (GC disabled).
        for goal in await svc._ce.list_goals():
            if goal.parent_id == root.id:
                assert goal.status == "pending"

    @pytest.mark.asyncio
    async def test_gc_cancels_active_goal_under_terminal_root(self) -> None:
        """An active child whose root just went terminal is also an orphan."""
        svc = _service()
        root = await svc._ce.create_goal("root job", source="user")
        child = await svc._ce.create_goal("active child", parent_id=root.id, source="user")
        svc._ce.claim_goal(child.id, loop_id="loop-1")
        await svc._ce.complete_goal(root.id)

        cancelled = await svc.gc_orphaned_goals()

        assert cancelled == 1
        assert (await svc._ce.get_goal(child.id)).status == "cancelled"


class TestReconcileStaleReservations:
    @pytest.mark.asyncio
    async def test_releases_reservation_for_terminal_goal(self) -> None:
        """A terminal goal that still holds a reservation gets released."""
        svc = _service()
        root = await svc._ce.create_goal("g", source="user", workspace="/ws/a")
        # Simulate the leak: goal is completed but reservation still held.
        await svc._ce.complete_goal(root.id)
        assert svc._workspace_reservation.acquire(root.id, "/ws/a")

        released = await svc.reconcile_stale_reservations()

        assert released >= 1
        assert svc._workspace_reservation.reservation_count() == 0

    @pytest.mark.asyncio
    async def test_releases_ghost_active_worker_slot(self) -> None:
        """A worker slot stuck active with no current goal gets mark_idle'd."""
        svc = _service()
        goal = await svc._ce.create_goal("g", source="user")
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        # Simulate the ghost: mark slot active with no current goal.
        worker.status = "active"
        worker.current_goal_id = None

        released = await svc.reconcile_stale_reservations()

        assert released >= 1
        assert svc._worker_pool.active_count() == 0

    @pytest.mark.asyncio
    async def test_releases_worker_for_terminal_goal(self) -> None:
        """A worker still active whose goal is terminal gets released."""
        svc = _service()
        goal = await svc._ce.create_goal("g", source="user")
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        # Goal completes but worker slot never mark_idle'd (lost chunk).
        await svc._ce.complete_goal(goal.id)
        assert worker.status == "active"  # ghost-active

        released = await svc.reconcile_stale_reservations()

        assert released >= 1
        assert worker.status == "idle"

    @pytest.mark.asyncio
    async def test_keeps_reservation_for_active_goal(self) -> None:
        svc = _service()
        goal = await svc._ce.create_goal("g", source="user", workspace="/ws/a")
        svc._ce.claim_goal(goal.id, loop_id="loop-1")
        assert svc._workspace_reservation.acquire(goal.id, "/ws/a")

        released = await svc.reconcile_stale_reservations()

        assert released == 0
        assert svc._workspace_reservation.reservation_count() == 1


class TestReconcileStaleWorker:
    @pytest.mark.asyncio
    async def test_requeues_stranded_active_goal_when_job_open(self) -> None:
        """A stale loop with an active goal under an open job → goal re-queued."""
        svc = _service()
        root = await svc._ce.create_goal("root", source="user")
        child = await svc._ce.create_goal("child", parent_id=root.id, source="user")
        worker = await svc._worker_pool.pick_worker(child, job_id=root.id)
        svc._ce.claim_goal(child.id, loop_id=worker.loop_id)
        # Root still pending (open job).
        assert (await svc._ce.get_goal(child.id)).status == "active"

        released = await svc.reconcile_stale_worker(worker.loop_id)

        assert released >= 1
        child_after = await svc._ce.get_goal(child.id)
        assert child_after.status == "pending"
        assert child_after.assigned_loop_id is None
        assert worker.status == "idle"

    @pytest.mark.asyncio
    async def test_cancels_stranded_goal_when_job_terminal(self) -> None:
        """A stale loop with an active goal under a terminal job → cancelled."""
        svc = _service()
        root = await svc._ce.create_goal("root", source="user")
        child = await svc._ce.create_goal("child", parent_id=root.id, source="user")
        worker = await svc._worker_pool.pick_worker(child, job_id=root.id)
        svc._ce.claim_goal(child.id, loop_id=worker.loop_id)
        await svc._ce.complete_goal(root.id)

        released = await svc.reconcile_stale_worker(worker.loop_id)

        assert released >= 1
        assert (await svc._ce.get_goal(child.id)).status == "cancelled"
        assert worker.status == "idle"

    @pytest.mark.asyncio
    async def test_noop_for_unknown_loop(self) -> None:
        svc = _service()
        assert await svc.reconcile_stale_worker("no-such-loop") == 0


class TestReconcileGoalResourcesIntegration:
    @pytest.mark.asyncio
    async def test_reconcile_releases_leaked_runtime_for_terminal_goal(self, tmp_path) -> None:
        """The watchdog releases slots + reservations for terminal goals."""
        svc = _service()
        workspace = str(tmp_path / "ws")
        goal = await svc._ce.create_goal("g", source="user", workspace=workspace)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        # Goal completes but completion chunk lost → worker stuck active.
        await svc._ce.complete_goal(goal.id)
        assert worker.status == "active"

        # Avoid the real shell_drain path touching the filesystem.
        with patch(
            "soothe.runner.shell_drain.drain_goal_runtime",
            return_value=0,
        ):
            count = await svc.reconcile_goal_resources()

        assert count >= 1
        assert worker.status == "idle"
        assert svc._workspace_reservation.reservation_count() == 0
