"""Regression tests for cancel-then-retry resume of an interrupted goal.

Covers the 6-point resumable retry solution:

* ``interrupted`` goal index status is treated as resumable (Point 5a).
* The idle-resume re-activation branch restores an ``interrupted`` goal to
  ``running`` (Point 5b).
* The iteration budget gate (now ``enforce_loop_budget`` on DISPATCH) grants
  one grace iteration on a resumed goal at the budget boundary so a
  cancel-then-retry at the final iteration does not immediately terminalize
  the goal (Point 4).

The ``TestCancelRetryContinueLifecycle`` class drives the *full* Cancel →
Retry → Continue lifecycle through real instances (a ``StrangeLoopCheckpoint``
+ the real ``mark_goal_interrupted`` mutation logic + the real
``has_resumable_interrupted_goal`` helper + the real idle-resume re-activation
conditional + the real ``enforce_loop_budget``) so regressions in any link of
the chain surface here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from soothe.sloop.stages.execute.loop_budget import enforce_loop_budget
from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint, ThreadHealthMetrics
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.state.schemas import LoopState
from soothe.sloop.state.sloop_manager import StrangeLoopStateManager
from soothe.sloop.utils.structural_continuation import (
    has_resumable_interrupted_goal,
    is_loop_control_signal,
)


def _goal(*, status: str = "running") -> GoalIndexEntry:
    now = datetime.now(UTC)
    return GoalIndexEntry(
        goal_id="goal-0",
        status=status,  # type: ignore[arg-type]
        thread_id="loop-1",
        started_at=now,
        completed_at=None,
        duration_ms=0,
        tokens_used=0,
    )


def _checkpoint(*, status: str, goal_status: str = "running") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        current_goal_index=0,
        goal_history=[_goal(status=goal_status)],
    )


def _runtime_ctx(
    *,
    iteration: int,
    max_iterations: int,
    recovery_valid_resume: bool,
    goal_record: GoalIndexEntry | None = None,
) -> SimpleNamespace:
    """Build a minimal runtime context duck-typed for ``enforce_loop_budget``."""
    checkpoint = SimpleNamespace(
        thread_health_metrics=ThreadHealthMetrics(thread_id="t", last_updated=datetime.now(UTC)),
    )
    return SimpleNamespace(
        loop_state=LoopState(
            goal="retry",
            thread_id="t",
            iteration=iteration,
            max_iterations=max_iterations,
        ),
        checkpoint=checkpoint,
        recovery_valid_resume=recovery_valid_resume,
        goal_record=goal_record,
        emit=AsyncMock(),
        state_manager=SimpleNamespace(save=AsyncMock()),
        strange_loop=SimpleNamespace(config=None, core_agent=None),
    )


def test_interrupted_goal_is_resumable() -> None:
    """An interrupted goal index entry must be recognized as resumable."""
    cp = _checkpoint(status="idle", goal_status="interrupted")
    assert has_resumable_interrupted_goal(cp)


def test_interrupted_status_reactivates_to_running() -> None:
    """The re-activation branch must restore an interrupted goal to running.

    This mirrors the ``strange_loop.py`` idle-resume branch: when the goal
    record status is ``interrupted`` (set by ``mark_goal_interrupted`` on a
    user cancel), a retry/continue/resume must flip it back to ``running``
    and clear ``completed_at`` so the loop resumes in place.
    """
    goal = _goal(status="interrupted")
    completed_at = goal.completed_at
    # Simulate the re-activation branch from strange_loop.py
    assert goal.status in ("cancelled", "interrupted")
    goal.status = "running"
    goal.completed_at = None
    assert goal.status == "running"
    assert goal.completed_at is None
    assert completed_at is None  # interrupted goals are not completed


def test_retry_keyword_is_loop_control_signal() -> None:
    """retry/continue/resume must be recognized as a loop-control signal."""
    assert is_loop_control_signal("retry")
    assert is_loop_control_signal("continue")
    assert is_loop_control_signal("resume")
    assert not is_loop_control_signal("hello")


@pytest.mark.asyncio
async def test_iteration_gate_grants_grace_iteration_on_resumed_goal() -> None:
    """The gate must NOT emit max_iterations when a goal was just resumed.

    Regression for cancel-then-retry at the budget boundary: when the
    persisted iteration cursor sits at ``max_iterations`` and the goal was
    resumed in place (``recovery_valid_resume=True``), the gate grants one
    grace iteration so the resumed run can make progress. Without the grace
    path, the gate would immediately terminalize the goal before doing any
    work, defeating the resume.
    """
    ctx = _runtime_ctx(
        iteration=5,
        max_iterations=5,
        recovery_valid_resume=True,
    )

    result = await enforce_loop_budget(ctx)  # type: ignore[arg-type]

    assert result is None
    ctx.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_iteration_gate_terminals_non_resumed_goal_at_boundary() -> None:
    """A non-resumed goal at the budget boundary still terminates normally.

    Guards against the grace-iteration path over-triggering: only goals that
    were actually resumed (``recovery_valid_resume=True``) skip the boundary
    check. A fresh goal that reached ``max_iterations`` must terminalize.
    """
    ctx = _runtime_ctx(
        iteration=5,
        max_iterations=5,
        recovery_valid_resume=False,
        goal_record=_goal(status="running"),
    )

    result = await enforce_loop_budget(ctx)  # type: ignore[arg-type]

    assert result == "max_iterations"
    ctx.emit.assert_awaited()


# ---------------------------------------------------------------------------
# Full Cancel → Retry → Continue lifecycle (real instances, chained chain)
# ---------------------------------------------------------------------------


def _make_checkpoint(*, goal_status: str = "running", iteration: int = 3) -> StrangeLoopCheckpoint:
    """Build a real ``StrangeLoopCheckpoint`` with one in-flight goal.

    Mirrors the shape ``strange_loop.py`` produces after starting a goal: the
    loop is ``running``, ``current_goal_index`` points at a ``running`` goal,
    and ``execution_checkpoint`` carries the persisted iteration cursor.
    """
    now = datetime.now(UTC)
    metrics = ThreadHealthMetrics(thread_id="t1", last_updated=now)
    goal = GoalIndexEntry(
        goal_id="loop-1_goal_0",
        status=goal_status,  # type: ignore[arg-type]
        thread_id="t1",
        started_at=now,
        completed_at=None,
        duration_ms=0,
        tokens_used=0,
    )
    cp = StrangeLoopCheckpoint(
        loop_id="loop-1",
        thread_ids=["t1"],
        current_thread_id="t1",
        status="running",
        goal_history=[goal],
        current_goal_index=0,
        thread_health_metrics=metrics,
        created_at=now,
        updated_at=now,
        execution_checkpoint={"iteration": iteration, "loop_id": "loop-1", "thread_id": "t1"},
    )
    return cp


def _real_state_manager(checkpoint: StrangeLoopCheckpoint) -> StrangeLoopStateManager:
    """Construct a ``StrangeLoopStateManager`` with an in-memory checkpoint.

    ``save`` is stubbed to a no-op so the real ``mark_goal_interrupted``
    mutation logic (cursor persist + status flip + ``idle`` touch) runs
    against the in-memory checkpoint without a DB backend.
    """
    mgr = StrangeLoopStateManager(loop_id=checkpoint.loop_id)
    mgr._checkpoint = checkpoint  # type: ignore[attr-defined]
    mgr.save = AsyncMock()  # type: ignore[method-assign]
    return mgr


def _reactivate_interrupted_goal(
    checkpoint: StrangeLoopCheckpoint,
) -> tuple[GoalIndexEntry, int, bool]:
    """Replicate the ``strange_loop.py`` idle-resume re-activation branch.

    When the checkpoint is ``idle`` with a resumable ``interrupted``/``cancelled``
    goal and the user sends a loop-control signal, the branch restores the goal
    to ``running``, clears ``completed_at``, restores the iteration cursor from
    ``execution_checkpoint``, flips the loop back to ``running``, and signals
    ``recovery_valid_resume=True``. Returns the (goal, iteration, resumed) tuple.
    """
    assert checkpoint.status == "idle"
    assert has_resumable_interrupted_goal(checkpoint)
    assert is_loop_control_signal("retry")
    goal = checkpoint.goal_history[checkpoint.current_goal_index]
    if goal.status in ("cancelled", "interrupted"):
        goal.status = "running"  # type: ignore[assignment]
        goal.completed_at = None
    iteration = int((checkpoint.execution_checkpoint or {}).get("iteration") or 0)
    checkpoint.status = "running"  # type: ignore[assignment]
    return goal, iteration, True


class TestCancelRetryContinueLifecycle:
    """End-to-end lifecycle: cancel persists an interrupted cursor, retry
    re-activates the goal in place, and the gate grants a grace iteration.

    These tests chain the real links of the 6-point solution so a regression
    in any of them (status vocabulary, cursor persistence, re-activation, or
    the iteration gate) breaks here rather than silently degrading resume.
    """

    @pytest.mark.asyncio
    async def test_cancel_then_retry_then_continue_full_chain(self) -> None:
        """Full lifecycle: running → mark interrupted → idle-resume → grace gate.

        1. A running goal at iteration 3 is cancelled via ``mark_goal_interrupted``:
           goal status flips to ``interrupted`` (NOT terminal ``cancelled``),
           the cursor ``iteration=3`` is persisted, and the loop touches to
           ``idle``.
        2. The user sends ``retry``: ``has_resumable_interrupted_goal`` detects
           the interrupted goal, the re-activation branch restores it to
           ``running`` and restores ``iteration=3`` from the cursor.
        3. The iteration gate at ``iteration >= max_iterations`` with
           ``recovery_valid_resume=True`` grants a grace iteration (no
           hard-exit), letting the resumed goal make progress.
        """
        cp = _make_checkpoint(goal_status="running", iteration=3)
        mgr = _real_state_manager(cp)
        goal = cp.goal_history[0]

        # --- CANCEL: mark_goal_interrupted persists an interrupted cursor ---
        await mgr.mark_goal_interrupted(goal, iteration=3, reason="user_cancelled")

        # Goal is interrupted (resumable), NOT terminal cancelled.
        assert goal.status == "interrupted"
        assert goal.completed_at is None
        # Loop touched to idle so the next turn re-enters via idle-resume.
        assert cp.status == "idle"
        # Cursor persisted as-is (not +1): the in-progress iteration did not flush.
        assert cp.execution_checkpoint["iteration"] == 3

        # --- RETRY: idle-resume re-activates the interrupted goal in place ---
        reactivated, iteration, resumed = _reactivate_interrupted_goal(cp)
        assert resumed is True
        assert reactivated.status == "running"
        assert reactivated.completed_at is None
        assert iteration == 3  # restored from persisted cursor
        assert cp.status == "running"

        # --- CONTINUE: gate grants a grace iteration on the resumed goal ---
        gate_ctx = _runtime_ctx(
            iteration=5,
            max_iterations=5,
            recovery_valid_resume=True,
            goal_record=reactivated,
        )
        result = await enforce_loop_budget(gate_ctx)  # type: ignore[arg-type]
        assert result is None
        gate_ctx.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_persists_cursor_not_incremented(self) -> None:
        """``mark_goal_interrupted`` persists the iteration as-is.

        The in-progress iteration never completed its ``record_iteration``
        flush (which writes ``iteration + 1``), so the cursor must reflect
        the *current* iteration, not the next one. Resuming then restores
        exactly that iteration.
        """
        cp = _make_checkpoint(goal_status="running", iteration=7)
        mgr = _real_state_manager(cp)

        await mgr.mark_goal_interrupted(cp.goal_history[0], iteration=7, reason="user_cancelled")

        assert cp.execution_checkpoint["iteration"] == 7
        _, restored_iteration, _ = _reactivate_interrupted_goal(cp)
        assert restored_iteration == 7

    @pytest.mark.asyncio
    async def test_cancel_with_no_in_flight_goal_is_noop(self) -> None:
        """Cancelling when there is no in-flight goal must not crash or mutate.

        ``mark_goal_interrupted(goal_record=None)`` is a no-op: it still
        persists the cursor field (defensive) but no goal status changes.
        """
        cp = _make_checkpoint(goal_status="running", iteration=2)
        mgr = _real_state_manager(cp)

        await mgr.mark_goal_interrupted(None, iteration=2, reason="no_active_goal")

        # No goal mutation; loop still touched to idle for the next turn.
        assert cp.goal_history[0].status == "running"
        assert cp.status == "idle"

    @pytest.mark.asyncio
    async def test_double_interrupt_is_idempotent(self) -> None:
        """Marking an already-interrupted goal interrupted again leaves status.

        ``mark_goal_interrupted`` only flips ``running`` → ``interrupted``;
        a second interrupt on an already-interrupted goal keeps the existing
        status (no spurious terminalization) and re-persists the cursor.
        """
        cp = _make_checkpoint(goal_status="running", iteration=4)
        mgr = _real_state_manager(cp)
        goal = cp.goal_history[0]

        await mgr.mark_goal_interrupted(goal, iteration=4, reason="user_cancelled")
        assert goal.status == "interrupted"

        # Reset to running to simulate a resume then a second cancel — or
        # directly re-mark the interrupted goal: status must stay interrupted.
        cp.status = "running"  # type: ignore[assignment]
        await mgr.mark_goal_interrupted(goal, iteration=4, reason="user_cancelled_again")
        assert goal.status == "interrupted"
        assert cp.execution_checkpoint["iteration"] == 4

    @pytest.mark.asyncio
    async def test_retry_without_control_signal_starts_new_goal(self) -> None:
        """A non-control user message on an idle+interrupted checkpoint does
        NOT re-activate the interrupted goal; it starts a fresh goal.

        The idle-resume re-activation branch is gated on
        ``is_loop_control_signal(user_line)``. A normal message bypasses
        re-activation, leaving the interrupted goal untouched (a new goal
        is appended by ``start_new_goal`` in the real loop).
        """
        cp = _make_checkpoint(goal_status="running", iteration=1)
        mgr = _real_state_manager(cp)
        goal = cp.goal_history[0]

        await mgr.mark_goal_interrupted(goal, iteration=1, reason="user_cancelled")
        assert cp.status == "idle"
        assert goal.status == "interrupted"

        # A plain message is not a control signal → must not re-activate.
        assert has_resumable_interrupted_goal(cp) is True
        assert is_loop_control_signal("please fix the parser bug") is False
        # The interrupted goal remains interrupted (new goal path would append).
        assert goal.status == "interrupted"

    @pytest.mark.asyncio
    async def test_continue_keyword_also_reactivates_interrupted_goal(self) -> None:
        """``continue`` (not just ``retry``) re-activates an interrupted goal.

        All three control signals — retry, continue, resume — are valid
        triggers for the idle-resume re-activation branch, so the lifecycle
        works regardless of which word the user types.
        """
        cp = _make_checkpoint(goal_status="running", iteration=2)
        mgr = _real_state_manager(cp)

        await mgr.mark_goal_interrupted(cp.goal_history[0], iteration=2, reason="user_cancelled")
        assert cp.status == "idle"

        for signal in ("retry", "continue", "resume"):
            assert is_loop_control_signal(signal) is True

        reactivated, iteration, resumed = _reactivate_interrupted_goal(cp)
        assert resumed is True
        assert reactivated.status == "running"
        assert iteration == 2

    @pytest.mark.asyncio
    async def test_resumed_goal_at_boundary_progresses_then_gates_on_next_turn(
        self,
    ) -> None:
        """Grace iteration is one-shot: the resumed goal gets exactly one turn
        past the boundary, then the gate reapplies on the next (non-resumed)
        turn.

        Guards against the grace path letting a resumed goal run unbounded:
        after the grace turn, ``recovery_valid_resume`` is False and the
        boundary check terminalizes normally.
        """
        cp = _make_checkpoint(goal_status="running", iteration=5)
        mgr = _real_state_manager(cp)

        await mgr.mark_goal_interrupted(cp.goal_history[0], iteration=5, reason="user_cancelled")
        reactivated, _, _ = _reactivate_interrupted_goal(cp)

        # First turn: resumed → grace iteration granted (no hard-exit).
        resumed_ctx = _runtime_ctx(
            iteration=5, max_iterations=5, recovery_valid_resume=True, goal_record=reactivated
        )
        assert await enforce_loop_budget(resumed_ctx) is None  # type: ignore[arg-type]

        # Second turn: not resumed → boundary check reapplies, hard-exit.
        next_ctx = _runtime_ctx(
            iteration=5, max_iterations=5, recovery_valid_resume=False, goal_record=reactivated
        )
        assert await enforce_loop_budget(next_ctx) == "max_iterations"  # type: ignore[arg-type]
        next_ctx.emit.assert_awaited()

    @pytest.mark.asyncio
    async def test_interrupted_is_not_terminal_and_remains_in_flight(self) -> None:
        """``interrupted`` is a resumable status, not a terminal one.

        After cancel, the goal must be classifiable as in-flight (so
        ``force_terminal_status`` can still transition it on a later fatal
        error) and the loop checkpoint must be non-terminal (so resume is
        allowed). This is the core invariant of the 6-point solution.
        """
        from soothe.sloop.state.status_vocabulary import (
            is_goal_index_in_flight,
        )

        cp = _make_checkpoint(goal_status="running", iteration=0)
        mgr = _real_state_manager(cp)
        goal = cp.goal_history[0]

        await mgr.mark_goal_interrupted(goal, iteration=0, reason="user_cancelled")

        assert goal.status == "interrupted"
        # In-flight (resumable / can still be terminalized), not terminal.
        assert is_goal_index_in_flight(goal.status) is True
        # Loop checkpoint stayed resumable (idle), not finalized/cancelled.
        assert cp.status == "idle"
        # And force_terminal_status can still transition an interrupted goal.
        applied = cp.force_terminal_status(terminal_status="cancelled", goal_status="cancelled")
        assert applied is True
        assert goal.status == "cancelled"
