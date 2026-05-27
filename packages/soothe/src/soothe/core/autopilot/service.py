"""AutopilotService for Layer 3 orchestration (RFC-222).

This module provides the AutopilotService class that manages:
- Loop pool (AgentLoop worker creation, assignment, release)
- Scheduling loop (goal → loop assignment with lineage reuse)
- Internal EventBus integration (AL ↔ GE ↔ AP coordination)
- Dreaming mode transitions

Architecture Position: Layer 3 peer with GoalEngine.
- AutopilotService: Loop management, scheduling, webhooks
- GoalEngine: Goal lifecycle, DAG, file locks

Key Principle: Solo mode preserved - AutopilotService only active
when autopilot.enabled is true.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.core.autopilot.loop_pool import LoopHandle, LoopPool
from soothe.core.events.internal_bus import get_internal_bus
from soothe.core.events.internal_events import (
    INTERNAL_GOAL_STATE_CHANGED,
    INTERNAL_GOALS_READY,
    InternalAutopilotAwakeEvent,
    InternalAutopilotDreamingEvent,
    InternalAutopilotStartedEvent,
    InternalAutopilotStoppedEvent,
    InternalFileReleasedEvent,
    InternalGoalsReadyEvent,
    InternalGoalStateChangedEvent,
    InternalLoopAssignedEvent,
    InternalLoopIdleEvent,
    InternalLoopPoolChangedEvent,
    InternalLoopReleasedEvent,
    InternalLoopSpawnedEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Callable

    from soothe.config.models import AutonomousConfig
    from soothe.core.goal_engine.engine import GoalEngine
    from soothe.core.goal_engine.models import Goal

logger = logging.getLogger(__name__)


# RFC-222: ContextVar carrying the active (loop_id, goal_id) for the current
# AsyncIO task. Middleware (FileLockMiddleware, observability hooks) reads this
# to attribute lock ownership and lineage without needing the values threaded
# through every call site. Set by AutopilotService.execute_goal; None in solo
# mode (zero overhead — readers see None and short-circuit).
_active_loop_context: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "soothe_autopilot_active_loop", default=None
)


def get_active_loop_context() -> tuple[str, str] | None:
    """Return the (loop_id, goal_id) active in the current task, if any.

    Used by middleware components that need to attribute work to a specific
    AutopilotService loop assignment without taking loop_id/goal_id as
    constructor arguments.
    """
    return _active_loop_context.get()


class AutopilotService:
    """Layer 3 Autopilot orchestration service.

    Manages AgentLoop worker pool and goal scheduling with
    lineage-aware loop reuse. Subscribes to GoalEngine events
    for reactive scheduling.

    Responsibilities:
    - Spawn and manage AgentLoop workers (loop pool)
    - Schedule ready goals to available loops
    - Lineage-aware loop assignment (reuse parent's loop)
    - Process ChannelInbox messages
    - Send webhook notifications
    - Enter dreaming mode when no goals active

    NOT responsible for:
    - Single-goal execution logic (AgentLoop owns this)
    - Goal DAG management (GoalEngine owns this)
    - Tool/subagent execution (CoreAgent owns this)

    Args:
        goal_engine: GoalEngine instance for goal management.
        config: AutonomousConfig (RFC-222 fields live in this unified config).
        internal_bus: Internal EventBus for coordination.
    """

    def __init__(
        self,
        goal_engine: GoalEngine,
        config: AutonomousConfig,
        internal_bus: Any | None = None,
    ) -> None:
        """Initialize AutopilotService.

        Args:
            goal_engine: GoalEngine instance for goal management.
            config: Project-level AutonomousConfig carrying RFC-222 loop pool
                fields (``max_loops``, ``loop_idle_timeout``, ``poll_interval``,
                ``dreaming_poll_interval``).
            internal_bus: Internal EventBus (uses singleton if None).
        """
        self._goal_engine = goal_engine
        self._config = config
        self._internal_bus = internal_bus or get_internal_bus()
        self._loop_pool = LoopPool(max_loops=self._config.max_loops)
        self._running = False
        self._dreaming = False
        self._scheduling_task: asyncio.Task | None = None

        # RFC-222: parallel-execution concurrency control.
        # `_assignment_lock` makes loop assignment atomic so two concurrent
        # execute_goal calls can't reach into _assign_loop_with_lineage at
        # the same time and double-claim a loop slot.
        # `_execution_semaphore` caps the number of in-flight execute_goal
        # runs at `max_parallel_goals` (independent of `max_loops`, which
        # caps worker capacity — loops can be reused for lineage).
        self._assignment_lock = asyncio.Lock()
        self._execution_semaphore = asyncio.Semaphore(self._config.max_parallel_goals)

        # Subscribe to GoalEngine events
        self._setup_subscriptions()

    def _setup_subscriptions(self) -> None:
        """Subscribe to InternalEventBus events."""
        self._internal_bus.subscribe(
            INTERNAL_GOAL_STATE_CHANGED,
            self._handle_goal_state_changed,
        )
        self._internal_bus.subscribe(
            INTERNAL_GOALS_READY,
            self._handle_goals_ready,
        )

    async def _handle_goal_state_changed(self, event: InternalGoalStateChangedEvent) -> None:
        """Handle goal state change from GoalEngine.

        Triggers scheduling re-evaluation and webhook notifications.

        Args:
            event: Goal state change event.
        """
        logger.debug(
            "Goal %s state changed: %s → %s",
            event.goal_id,
            event.old_status,
            event.new_status,
        )

        # Release file locks if goal completed or failed
        if event.new_status in ("completed", "failed"):
            await self._release_goal_locks(event.goal_id)

        # Release loop if goal completed
        if event.new_status == "completed" and event.loop_id:
            await self._mark_loop_idle(event.loop_id, event.goal_id)

        # Trigger scheduling if new active goal
        if event.new_status == "active" and self._running and not self._dreaming:
            await self._schedule_next_goal()

    async def _handle_goals_ready(self, event: InternalGoalsReadyEvent) -> None:
        """Handle goals ready for scheduling.

        Args:
            event: Goals ready event from GoalEngine.
        """
        logger.info("Goals ready for scheduling: %d", event.count)

        if self._running and not self._dreaming:
            for goal_id in event.goal_ids:
                await self._schedule_goal(goal_id)

    async def _release_goal_locks(self, goal_id: str) -> None:
        """Release file locks for completed/failed goal.

        GoalEngine's ``complete_goal``/``fail_goal`` already release locks and
        emit ``InternalFileReleasedEvent``. This is a defensive sweep for cases
        where a state change reaches the bus via another path (e.g. external
        callers that flip status directly). Safe to call multiple times.

        Args:
            goal_id: Goal whose locks to release.
        """
        released = self._goal_engine.file_registry.release_all_for_goal(goal_id)
        for path in released:
            await self._internal_bus.emit(
                InternalFileReleasedEvent(goal_id=goal_id, file_path=path)
            )
            logger.debug("Released file lock: %s for goal %s", path, goal_id)

    async def _mark_loop_idle(self, loop_id: str, goal_id: str) -> None:
        """Mark loop as idle after goal completion.

        Args:
            loop_id: Loop to mark idle.
            goal_id: Completed goal.
        """
        loop = self._loop_pool.loops.get(loop_id)
        if loop:
            loop.mark_idle()
            self._loop_pool.idle_loops.append(loop_id)
            self._loop_pool.goal_to_loop[goal_id] = loop_id

            await self._internal_bus.emit(
                InternalLoopIdleEvent(
                    loop_id=loop_id,
                    last_goal_id=goal_id,
                    goal_history_count=loop.get_history_count(),
                )
            )

            await self._internal_bus.emit(
                InternalLoopPoolChangedEvent(
                    active_count=self._loop_pool.active_count(),
                    idle_count=self._loop_pool.idle_count(),
                    total_count=self._loop_pool.total_count(),
                    change_type="idle",
                    loop_id=loop_id,
                )
            )

    async def start(self) -> None:
        """Start AutopilotService.

        Initializes loop pool, starts scheduling loop,
        emits started event.
        """
        if self._running:
            logger.warning("AutopilotService already running")
            return

        self._running = True
        self._dreaming = False

        await self._internal_bus.emit(
            InternalAutopilotStartedEvent(max_loops=self._config.max_loops)
        )

        await self._internal_bus.emit(
            InternalLoopPoolChangedEvent(
                active_count=0,
                idle_count=0,
                total_count=0,
                change_type="spawn",
            )
        )

        # Start scheduling loop
        self._scheduling_task = asyncio.create_task(self._run_scheduling_loop())

        logger.info("AutopilotService started with max_loops=%d", self._config.max_loops)

    async def stop(self, reason: str = "user_request") -> None:
        """Stop AutopilotService.

        Releases all loops, stops scheduling, emits stopped event.

        Args:
            reason: Why the service stopped.
        """
        if not self._running:
            return

        self._running = False
        self._dreaming = False

        # Cancel scheduling task
        if self._scheduling_task:
            self._scheduling_task.cancel()
            try:
                await self._scheduling_task
            except asyncio.CancelledError:
                pass
            self._scheduling_task = None

        # Release all loops
        for loop_id in list(self._loop_pool.loops.keys()):
            await self._release_loop(loop_id, reason="shutdown")

        await self._internal_bus.emit(
            InternalAutopilotStoppedEvent(
                reason=reason,
                active_loops=self._loop_pool.active_count(),
                goals_completed=len(self._loop_pool.goal_to_loop),
            )
        )

        logger.info("AutopilotService stopped: %s", reason)

    async def _release_loop(self, loop_id: str, reason: str = "idle_timeout") -> LoopHandle | None:
        """Release a loop from the pool.

        Args:
            loop_id: Loop to release.
            reason: Why the loop is released.

        Returns:
            Released LoopHandle if found.
        """
        loop = self._loop_pool.remove_loop(loop_id)
        if loop:
            # Release any file locks held by this loop
            released = self._goal_engine.file_registry.release_all_for_loop(loop_id)
            for path in released:
                await self._internal_bus.emit(
                    InternalFileReleasedEvent(
                        goal_id=loop.current_goal_id or "",
                        file_path=path,
                        loop_id=loop_id,
                    )
                )

            await self._internal_bus.emit(
                InternalLoopReleasedEvent(
                    loop_id=loop_id,
                    reason=reason if reason in ("idle_timeout", "shutdown", "error") else "error",
                    goals_processed=loop.get_history_count(),
                )
            )

            logger.info(
                "Released loop %s: %s (processed %d goals)",
                loop_id,
                reason,
                loop.get_history_count(),
            )

        return loop

    async def execute_goal(
        self,
        goal_id: str,
        executor: Callable[[Goal, LoopHandle], AsyncIterator[Any]],
    ) -> AsyncGenerator[Any, None]:
        """Execute a goal end-to-end with loop assignment + claim + cleanup.

        Wraps an injected ``executor`` (typically the runner's
        ``_execute_autonomous_goal``) with:
        - lineage-aware loop assignment from the pool
        - atomic ``claim_goal`` so the goal flips to ``active`` and the
          assigned loop_id is stamped on it
        - ``_active_loop_context`` ContextVar set for the duration of the
          run so middleware can attribute file locks correctly
        - loop release/idle bookkeeping on completion or failure

        The executor itself is responsible for actually driving AgentLoop,
        emitting domain events, calling ``complete_goal``/``fail_goal``,
        and yielding stream chunks back to the caller.

        Args:
            goal_id: Goal to execute.
            executor: Callable that takes (Goal, LoopHandle) and returns
                an async iterator of stream chunks. Invoked once after
                the goal is claimed and the loop is assigned.

        Yields:
            Whatever the executor yields. If the goal can't be claimed
            (vanished or raced), yields nothing and returns silently.
        """
        # Resolve goal first so we can do lineage assignment with the parent_id
        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            logger.warning("execute_goal: goal %s not found", goal_id)
            return

        # Bound concurrent goal execution via the configured cap so callers
        # that fan out via asyncio.gather can't exceed max_parallel_goals.
        # The semaphore is acquired BEFORE loop assignment so we don't burn
        # a loop slot while waiting for execution capacity.
        async with self._execution_semaphore:
            # Lineage + idle + spawn checks must be atomic w.r.t. other
            # parallel execute_goal calls. Without this lock, two coroutines
            # could both read "parent loop is reusable" and stomp each other.
            async with self._assignment_lock:
                loop = await self._assign_loop_with_lineage(goal)
            if not loop:
                logger.warning("execute_goal: no loop capacity for goal %s", goal_id)
                return

            claimed = await self._goal_engine.claim_goal(goal_id, loop_id=loop.loop_id)
            if not claimed:
                logger.warning(
                    "execute_goal: goal %s no longer claimable; releasing loop %s",
                    goal_id,
                    loop.loop_id,
                )
                # Return the loop to the idle queue so it can serve another goal.
                async with self._assignment_lock:
                    self._loop_pool.idle_loops.append(loop.loop_id)
                    loop.current_goal_id = None
                    loop.mark_idle()
                return

            # Set ContextVar so downstream middleware/observers can read loop+goal.
            token = _active_loop_context.set((loop.loop_id, goal_id))
            succeeded = False
            try:
                async for chunk in executor(claimed, loop):
                    yield chunk
                succeeded = True
            finally:
                _active_loop_context.reset(token)
                await self._finalize_loop_for_goal(loop, goal_id, success=succeeded)

    async def _finalize_loop_for_goal(
        self,
        loop: LoopHandle,
        goal_id: str,
        *,
        success: bool,
    ) -> None:
        """Move a loop from active → idle (or error) after a goal run."""
        if success:
            # The executor is expected to call complete_goal/fail_goal on
            # GoalEngine, which already releases file locks via
            # _release_locks_and_emit. Here we only update pool bookkeeping.
            self._loop_pool.record_goal_completion(goal_id, loop.loop_id)
            await self._internal_bus.emit(
                InternalLoopIdleEvent(
                    loop_id=loop.loop_id,
                    last_goal_id=goal_id,
                    goal_history_count=loop.get_history_count(),
                )
            )
            await self._internal_bus.emit(
                InternalLoopPoolChangedEvent(
                    active_count=self._loop_pool.active_count(),
                    idle_count=self._loop_pool.idle_count(),
                    total_count=self._loop_pool.total_count(),
                    change_type="idle",
                    loop_id=loop.loop_id,
                )
            )
        else:
            # Executor raised — mark loop as errored and release it so a
            # fresh one will be spawned next time. Locks held by the
            # erroring loop are released defensively here even though
            # GoalEngine.fail_goal also does it on the goal_id side.
            self._loop_pool.record_goal_failure(goal_id, loop.loop_id)
            await self._release_loop(loop.loop_id, reason="error")

    async def _run_scheduling_loop(self) -> None:
        """Main scheduling loop coroutine.

        Polls GoalEngine for ready goals, assigns loops,
        monitors loop health, releases idle loops.
        """
        poll_interval = self._config.poll_interval

        while self._running:
            try:
                # 1. Process channel inbox (if configured)
                await self._process_inbox()

                # 2. Check scheduled tasks (if enabled)
                await self._check_scheduled_tasks()

                # 3. Schedule ready goals
                await self._schedule_ready_goals()

                # 4. Monitor active loops
                await self._monitor_loop_health()

                # 5. Release idle loops past timeout
                await self._release_idle_loops()

                # 6. Check for dreaming transition
                if self._goal_engine.is_complete():
                    await self._enter_dreaming_mode()

                # 7. Sleep for next tick
                await asyncio.sleep(
                    self._config.dreaming_poll_interval if self._dreaming else poll_interval
                )

            except asyncio.CancelledError:
                logger.debug("Scheduling loop cancelled")
                break
            except Exception:
                logger.exception("Scheduling loop error")
                await asyncio.sleep(poll_interval)

    async def _process_inbox(self) -> None:
        """Process channel inbox for new tasks.

        Reads pending messages and creates goals via GoalEngine.
        """
        # TODO: Implement inbox processing when channel protocol is ready
        pass

    async def _check_scheduled_tasks(self) -> None:
        """Check scheduled tasks and create goals for due tasks."""
        # TODO: Implement scheduled task check when scheduler is integrated
        pass

    async def _schedule_ready_goals(self) -> None:
        """Schedule all ready goals from GoalEngine.

        Uses ``peek_ready_goals`` for capacity planning (no side effects),
        then activates each goal only after a loop is successfully
        assigned. This avoids prematurely flipping goals to ``active``
        when there isn't enough loop capacity.
        """
        max_par = self._config.max_loops - self._loop_pool.active_count()
        if max_par <= 0:
            return

        candidates = await self._goal_engine.peek_ready_goals(limit=max_par)
        for candidate in candidates:
            loop = await self._assign_loop_with_lineage(candidate)
            if not loop:
                # Pool filled mid-iteration; remaining candidates wait.
                logger.warning("No loop capacity for goal %s; deferring", candidate.id)
                break
            await self._activate_and_record(candidate.id, loop)

    async def _schedule_goal(self, goal_id: str) -> None:
        """Schedule a single goal to a loop.

        Used by reactive paths (e.g. ``_handle_goals_ready``) where the
        scheduler already knows which goal to act on.

        Args:
            goal_id: Goal to schedule.
        """
        goal = await self._goal_engine.get_goal(goal_id)
        if not goal:
            logger.warning("Goal %s not found for scheduling", goal_id)
            return

        loop = await self._assign_loop_with_lineage(goal)
        if not loop:
            logger.warning("No loop available for goal %s", goal_id)
            return

        await self._activate_and_record(goal_id, loop)

    async def _activate_and_record(self, goal_id: str, loop: LoopHandle) -> None:
        """Atomically claim the goal and stamp the assigned loop_id.

        Args:
            goal_id: Goal to activate.
            loop: Assigned LoopHandle.
        """
        claimed = await self._goal_engine.claim_goal(goal_id, loop_id=loop.loop_id)
        if not claimed:
            logger.warning("Goal %s no longer claimable; releasing loop %s", goal_id, loop.loop_id)
            # Loop was already moved out of idle by assignment; put it back.
            self._loop_pool.idle_loops.append(loop.loop_id)
            loop.current_goal_id = None
            loop.mark_idle()
            return
        logger.info("Scheduled goal %s to loop %s", goal_id, loop.loop_id)

    async def _assign_loop_with_lineage(self, goal: Goal) -> LoopHandle | None:
        """Assign loop with lineage-aware reuse.

        Prefers parent's loop for context preservation.

        Args:
            goal: Goal to assign loop for.

        Returns:
            LoopHandle if assigned, None if no capacity.
        """
        # 1. Check lineage affinity
        if goal.parent_id:
            parent_loop_id = self._loop_pool.goal_to_loop.get(goal.parent_id)
            if parent_loop_id:
                parent_loop = self._loop_pool.loops.get(parent_loop_id)
                if parent_loop and parent_loop.can_reuse_for_child(goal.parent_id):
                    # REUSE: preserves working_memory
                    self._loop_pool.assign_loop_to_goal(parent_loop, goal.id)

                    await self._internal_bus.emit(
                        InternalLoopAssignedEvent(
                            loop_id=parent_loop.loop_id,
                            goal_id=goal.id,
                            parent_goal_id=goal.parent_id,
                            reused=True,
                        )
                    )

                    logger.info(
                        "Reused loop %s for child goal %s (parent: %s)",
                        parent_loop.loop_id,
                        goal.id,
                        goal.parent_id,
                    )
                    return parent_loop

        # 2. Check idle loops
        idle_loop = self._loop_pool.pop_idle_loop()
        if idle_loop:
            self._loop_pool.assign_loop_to_goal(idle_loop, goal.id)

            await self._internal_bus.emit(
                InternalLoopAssignedEvent(
                    loop_id=idle_loop.loop_id,
                    goal_id=goal.id,
                    reused=False,
                )
            )

            logger.info("Assigned idle loop %s to goal %s", idle_loop.loop_id, goal.id)
            return idle_loop

        # 3. Spawn new loop
        if self._loop_pool.can_spawn():
            new_loop = await self._spawn_loop()
            self._loop_pool.assign_loop_to_goal(new_loop, goal.id)

            await self._internal_bus.emit(
                InternalLoopAssignedEvent(
                    loop_id=new_loop.loop_id,
                    goal_id=goal.id,
                    reused=False,
                )
            )

            logger.info("Spawned new loop %s for goal %s", new_loop.loop_id, goal.id)
            return new_loop

        # 4. No capacity
        logger.warning("No loop capacity for goal %s", goal.id)
        return None

    async def _spawn_loop(self) -> LoopHandle:
        """Spawn a new AgentLoop worker.

        Returns:
            New LoopHandle.
        """
        loop = LoopHandle(status="idle")
        self._loop_pool.add_loop(loop)

        await self._internal_bus.emit(InternalLoopSpawnedEvent(loop_id=loop.loop_id))

        await self._internal_bus.emit(
            InternalLoopPoolChangedEvent(
                active_count=self._loop_pool.active_count(),
                idle_count=self._loop_pool.idle_count(),
                total_count=self._loop_pool.total_count(),
                change_type="spawn",
                loop_id=loop.loop_id,
            )
        )

        logger.debug("Spawned loop %s", loop.loop_id)
        return loop

    async def _schedule_next_goal(self) -> None:
        """Schedule next ready goal (single goal trigger)."""
        await self._schedule_ready_goals()

    async def _monitor_loop_health(self) -> None:
        """Monitor active loop health.

        Checks for stalled or errored loops.
        """
        # TODO: Implement health monitoring (timeout checks, heartbeat)
        pass

    async def _release_idle_loops(self) -> None:
        """Release idle loops past timeout."""
        timeout = self._config.loop_idle_timeout
        now = datetime.now(UTC)

        for loop_id in list(self._loop_pool.idle_loops):
            loop = self._loop_pool.loops.get(loop_id)
            if loop and loop.idle_since:
                elapsed = (now - loop.idle_since).total_seconds()
                if elapsed > timeout:
                    await self._release_loop(loop_id, reason="idle_timeout")

    async def _enter_dreaming_mode(self) -> None:
        """Enter dreaming mode when no goals active."""
        if self._dreaming:
            return

        self._dreaming = True

        await self._internal_bus.emit(InternalAutopilotDreamingEvent(trigger="all_goals_complete"))

        logger.info(
            "Entered dreaming mode - polling reduced to %ds", self._config.dreaming_poll_interval
        )

    async def wake_from_dreaming(self, trigger: str = "wake_signal") -> None:
        """Wake from dreaming mode.

        Args:
            trigger: What caused the wake (wake_signal, new_task, scheduled_task).
        """
        if not self._dreaming:
            return

        self._dreaming = False

        await self._internal_bus.emit(
            InternalAutopilotAwakeEvent(
                trigger=trigger
                if trigger in ("new_task", "wake_signal", "scheduled_task")
                else "wake_signal"
            )
        )

        logger.info("Woke from dreaming mode - trigger: %s", trigger)

    def status(self) -> dict[str, Any]:
        """Get AutopilotService status.

        Returns:
            Status dict with running, dreaming, loop pool stats.
        """
        return {
            "running": self._running,
            "dreaming": self._dreaming,
            "loop_pool": {
                "active": self._loop_pool.active_count(),
                "idle": self._loop_pool.idle_count(),
                "total": self._loop_pool.total_count(),
                "max": self._loop_pool.max_loops,
            },
            "goals": {
                "completed": len(self._loop_pool.goal_to_loop),
            },
            "config": {
                "max_loops": self._config.max_loops,
                "loop_idle_timeout": self._config.loop_idle_timeout,
                "poll_interval": self._config.poll_interval,
            },
        }
