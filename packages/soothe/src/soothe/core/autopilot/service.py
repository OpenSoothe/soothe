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
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

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
    from soothe.core.goal_engine.engine import GoalEngine

logger = logging.getLogger(__name__)


class AutopilotConfig(BaseModel):
    """Autopilot configuration (RFC-222).

    Args:
        enabled: Whether autopilot mode is active.
        max_loops: Maximum concurrent AgentLoop workers.
        loop_idle_timeout: Seconds before releasing idle loop.
        poll_interval: Scheduling loop tick interval.
        dreaming_poll_interval: Reduced polling when in dreaming mode.
        inbox_dir: Path to autopilot inbox directory.
        outbox_dir: Path to autopilot outbox directory.
        webhooks: Webhook URLs for goal events.
    """

    enabled: bool = False
    max_loops: int = 4
    loop_idle_timeout: int = 300  # seconds
    poll_interval: int = 5  # seconds
    dreaming_poll_interval: int = 60  # seconds
    inbox_dir: str = "$SOOTHE_HOME/autopilot/inbox"
    outbox_dir: str = "$SOOTHE_HOME/autopilot/outbox"
    webhooks: dict[str, str | None] = Field(default_factory=dict)


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
        config: Autopilot configuration.
        internal_bus: Internal EventBus for coordination.
    """

    def __init__(
        self,
        goal_engine: GoalEngine,
        config: AutopilotConfig | None = None,
        internal_bus: Any | None = None,
    ) -> None:
        """Initialize AutopilotService.

        Args:
            goal_engine: GoalEngine instance for goal management.
            config: Autopilot configuration (uses defaults if None).
            internal_bus: Internal EventBus (uses singleton if None).
        """
        self._goal_engine = goal_engine
        self._config = config or AutopilotConfig()
        self._internal_bus = internal_bus or get_internal_bus()
        self._loop_pool = LoopPool(max_loops=self._config.max_loops)
        self._running = False
        self._dreaming = False
        self._scheduling_task: asyncio.Task | None = None

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

        Args:
            goal_id: Goal whose locks to release.
        """
        if hasattr(self._goal_engine, "_file_registry"):
            released = self._goal_engine._file_registry.release_all_for_goal(goal_id)
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
            if hasattr(self._goal_engine, "_file_registry"):
                released = self._goal_engine._file_registry.release_all_for_loop(loop_id)
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
        """Schedule all ready goals from GoalEngine."""
        max_par = self._config.max_loops - self._loop_pool.active_count()
        if max_par <= 0:
            return

        ready_goals = await self._goal_engine.ready_goals(limit=max_par)
        for goal in ready_goals:
            await self._schedule_goal(goal.id)

    async def _schedule_goal(self, goal_id: str) -> None:
        """Schedule a single goal to a loop.

        Args:
            goal_id: Goal to schedule.
        """
        goal = self._goal_engine._goals.get(goal_id)
        if not goal:
            logger.warning("Goal %s not found for scheduling", goal_id)
            return

        loop = await self._assign_loop_with_lineage(goal)
        if not loop:
            logger.warning("No loop available for goal %s", goal_id)
            return

        # Update goal with loop assignment
        goal.assigned_loop_id = loop.loop_id

        logger.info("Scheduled goal %s to loop %s", goal_id, loop.loop_id)

    async def _assign_loop_with_lineage(self, goal: Any) -> LoopHandle | None:
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
