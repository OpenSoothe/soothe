"""AutopilotService for Layer 3 orchestration (RFC-222, RFC-625).

This module provides the AutopilotService class that manages:
- Loop pool (StrangeLoop worker creation, assignment, release)
- Scheduling loop (goal → loop assignment with lineage reuse)
- Internal EventBus integration (AL ↔ CE ↔ AP coordination)
- Dreaming mode transitions

Architecture Position: Layer 3 orchestrator using ContextEngine.
- AutopilotService: Loop management, scheduling, webhooks
- ContextEngine: Goal lifecycle, DAG (sole source of truth per RFC-625)
- AutopilotMonitor: DAG verification, dreaming coordination

Key Principle: Solo mode preserved - AutopilotService only active
when autopilot.enabled is true.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES, GoalNode, StepExecution, StepNode
from soothe.events.internal_bus import InternalEventBus
from soothe.events.internal_events import (
    INTERNAL_GOAL_STATE_CHANGED,
    INTERNAL_GOAL_UNBLOCKED,
    INTERNAL_GOALS_READY,
    InternalAutopilotAwakeEvent,
    InternalAutopilotDreamingEvent,
    InternalAutopilotStartedEvent,
    InternalAutopilotStoppedEvent,
    InternalGoalCompletedEvent,
    InternalGoalFailedEvent,
    InternalGoalsReadyEvent,
    InternalGoalStateChangedEvent,
    InternalGoalUnblockedEvent,
    InternalLoopAssignedEvent,
    InternalLoopIdleEvent,
    InternalLoopPoolChangedEvent,
    InternalLoopReleasedEvent,
)

if TYPE_CHECKING:
    from soothe.autopilot import AutopilotMonitor
    from soothe.config.models import AutopilotConfig

logger = logging.getLogger(__name__)


class AutopilotService:
    """Layer 3 Autopilot orchestration service (RFC-222, RFC-625).

    Manages StrangeLoop worker pool and goal scheduling with
    lineage-aware loop reuse. Uses ContextEngine as the sole
    source of truth for goal/step state.

    Responsibilities:
    - Spawn and manage StrangeLoop workers (loop pool)
    - Schedule ready goals to available loops
    - Lineage-aware loop assignment (reuse parent's loop)
    - Send webhook notifications
    - Enter dreaming mode when no goals active

    NOT responsible for:
    - Single-goal execution logic (StrangeLoop owns this)
    - Goal DAG management (ContextEngine owns this per RFC-625)
    - Tool/subagent execution (CoreAgent owns this)

    Args:
        ce: ContextEngine instance for goal management (RFC-625).
        config: AutopilotConfig (RFC-222 fields live in this unified config).
        internal_bus: Internal EventBus for coordination.
        monitor: Optional AutopilotMonitor for proactive DAG monitoring.
    """

    def __init__(
        self,
        ce: ContextEngine,
        config: AutopilotConfig,
        internal_bus: Any | None = None,
        *,
        monitor: AutopilotMonitor | None = None,
        subscribe_to_bus: bool = True,
        runner_factory: Any,
        workspace_reservation: Any | None = None,
        consensus_model: Any | None = None,
        goal_persist_store: Any | None = None,
    ) -> None:
        """Initialize AutopilotService.

        Args:
            ce: ContextEngine instance for goal management (RFC-625).
            config: Project-level AutopilotConfig carrying RFC-222 loop pool
                fields (``max_loops``, ``loop_idle_timeout``, ``poll_interval``,
                ``dreaming_poll_interval``).
            internal_bus: Internal EventBus (uses singleton if None).
            monitor: Optional AutopilotMonitor for proactive DAG monitoring.
                When provided (daemon mode), handles goal intake, verification,
                and dreaming coordination.
            subscribe_to_bus: When True (default), subscribe handlers to the
                bus immediately. RFC-222 (revised): the daemon constructs a
                daemon-owned ``AutopilotService`` alongside the per-runner
                one — they share the singleton bus, so the daemon instance
                must pass ``subscribe_to_bus=False`` to avoid
                double-handling every event.
            runner_factory: ``LoopRunnerFactory``-shaped object exposing
                ``create_runner(loop_id) -> LoopRunnerProtocol``. Required for
                worker-pool dispatch (RFC-222 Phase C+).
            workspace_reservation: Optional ``WorkspaceReservation`` gate.
                When provided, the scheduling loop refuses to dispatch a
                goal whose workspace overlaps an active reservation. When
                ``None``, no workspace gating is applied.
            consensus_model: Optional LLM for RFC-204 consensus validation.
                When ``None``, completed goals suspend until a model is configured.
            goal_persist_store: Optional ``AsyncPersistStore`` for persisting
                the ContextEngine DAG snapshot across daemon restarts.
                Also backs the job↔loop membership index (IG-677).
        """
        if runner_factory is None:
            msg = "runner_factory is required"
            raise ValueError(msg)
        self._ce = ce
        self._monitor = monitor
        self._config = config
        self._internal_bus = internal_bus if internal_bus is not None else InternalEventBus()
        self._running = False
        self._dreaming = False
        self._scheduling_task: asyncio.Task | None = None
        self._subscribed = False
        # IG-680: health removals cascade through service cancel when monitor is wired.
        if self._monitor is not None:
            self._monitor.bind_service_cancel(self.cancel_goal)

        # RFC-222 revised (Phase C): WorkerPool-driven dispatch.
        # Capacity: ``max_loops`` (pool size) and ``max_parallel_goals``
        # (schedule cap in ``_schedule_via_worker_pool``). Assignment locking
        # lives on ``WorkerPool``.
        self._runner_factory = runner_factory
        from soothe.autopilot.job_loop_index import JobLoopIndex
        from soothe.autopilot.worker_pool import WorkerPool

        self._worker_pool = WorkerPool(factory=runner_factory, max_loops=self._config.max_loops)
        self._workspace_reservation = workspace_reservation
        self._consensus_model = consensus_model
        self._goal_persist_store = goal_persist_store
        self._job_loop_index = JobLoopIndex(store=goal_persist_store)
        self._context_store: Any = None
        self._context_projector: Any = None
        self._dispatch_tasks: dict[str, asyncio.Task] = {}  # goal_id → consumer task
        self._persist_fail_count = 0
        self._rail_interpreter: Any = None
        self._init_rail_interpreter()

        if subscribe_to_bus:
            self._setup_subscriptions()
            self._subscribed = True

    def _init_rail_interpreter(self) -> None:
        """Construct LoopRail interpreter with job-scoped JSONL traces (IG-RQJ-02)."""
        try:
            from pathlib import Path

            from soothe_sdk.paths import SOOTHE_DATA_DIR

            from soothe.autopilot.rail.guards import LLMGuardEvaluator
            from soothe.autopilot.rail.interpreter import LoopRailInterpreter
            from soothe.autopilot.rail.trace_store import JsonlRailTraceStore

            guards = None
            if self._consensus_model is not None:
                guards = LLMGuardEvaluator(model=self._consensus_model)
            data_dir = Path(SOOTHE_DATA_DIR)
            trace_root = data_dir / "jobs"
            legacy_root = data_dir / "loops"
            trace_root.mkdir(parents=True, exist_ok=True)
            self._rail_interpreter = LoopRailInterpreter(
                self._ce,
                guards=guards,
                trace=JsonlRailTraceStore(root=trace_root, legacy_root=legacy_root),
                jobs_root=trace_root,
            )
        except Exception:
            logger.warning("LoopRail interpreter unavailable", exc_info=True)
            self._rail_interpreter = None

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
        self._internal_bus.subscribe(
            INTERNAL_GOAL_UNBLOCKED,
            self._handle_goal_unblocked,
        )

    async def _handle_goal_state_changed(self, event: InternalGoalStateChangedEvent) -> None:
        """Handle goal state change from ContextEngine.

        Triggers scheduling re-evaluation and loop cleanup.

        Args:
            event: Goal state change event.
        """
        logger.debug(
            "Goal %s state changed: %s → %s",
            event.goal_id,
            event.old_status,
            event.new_status,
        )

        # Release loop if goal completed
        if event.new_status == "completed" and event.loop_id:
            await self._mark_loop_idle(event.loop_id, event.goal_id)

        # Trigger scheduling if new active goal
        if event.new_status == "active" and self._running and not self._dreaming:
            await self._schedule_ready_goals()

    async def _handle_goals_ready(self, event: InternalGoalsReadyEvent) -> None:
        """Handle goals ready for scheduling.

        Args:
            event: Goals ready event.
        """
        logger.info("Goals ready for scheduling: %d", event.count)

        if self._running and not self._dreaming:
            for goal_id in event.goal_ids:
                await self._schedule_goal(goal_id)

    async def _handle_goal_unblocked(self, event: InternalGoalUnblockedEvent) -> None:
        """Handle goal unblocked event (e.g., clarification resolved).

        Immediately triggers scheduling for the unblocked goal to avoid
        waiting for the next poll cycle. This ensures responsive autopilot
        when clarification questions are answered by the user.

        Args:
            event: Goal unblocked event with goal_id and optional loop_id.
        """
        logger.info(
            "Goal %s unblocked (%s → %s), triggering scheduling",
            event.goal_id,
            event.old_status,
            event.new_status,
        )

        if self._running and not self._dreaming:
            await self._schedule_goal(event.goal_id)

    async def _mark_loop_idle(self, loop_id: str, goal_id: str) -> None:
        """Mark worker idle after goal completion (idempotent with stream consumer).

        Args:
            loop_id: Worker loop id.
            goal_id: Completed goal.
        """
        worker = self._worker_pool.get_worker(loop_id)
        if worker is not None and worker.current_goal_id == goal_id:
            await self._worker_pool.mark_idle(loop_id, success=True)

        await self._internal_bus.emit(
            InternalLoopIdleEvent(
                loop_id=loop_id,
                last_goal_id=goal_id,
                goal_history_count=len(worker.last_goal_ids) if worker else 0,
            )
        )

        await self._internal_bus.emit(
            InternalLoopPoolChangedEvent(
                active_count=self._worker_pool.active_count(),
                idle_count=self._worker_pool.idle_count(),
                total_count=self._worker_pool.total_count(),
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

        await self._restore_persisted_goals()
        interrupted = await self._job_loop_index.interrupt_active_loops()
        if interrupted:
            logger.warning(
                "[Autopilot] crash recovery: interrupted %d active loop assignment(s)",
                len(interrupted),
            )

        if self._monitor is not None:
            await self._monitor.start()

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

        if self._monitor is not None:
            await self._monitor.stop()

        await self._persist_goals()

        # Cancel any in-flight dispatch consumer tasks (RFC-222 Phase C).
        for goal_id, task in list(self._dispatch_tasks.items()):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._dispatch_tasks.pop(goal_id, None)

        # Release all workers
        for worker in list(self._worker_pool.workers()):
            await self._release_worker(worker.loop_id, reason="shutdown")

        await self._internal_bus.emit(
            InternalAutopilotStoppedEvent(
                reason=reason,
                active_loops=self._worker_pool.active_count(),
                goals_completed=sum(1 for g in self._ce.get_all_goals() if g.status == "completed"),
            )
        )

        logger.info("AutopilotService stopped: %s", reason)

    # ---- Public submission API (RFC-222 revised, Phase C) -------------

    async def submit_task(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
        max_send_backs: int | None = None,
        depends_on: list[str] | None = None,
        informs: list[str] | None = None,
        source_file: str | None = None,
        workspace: str | None = None,
        cron_job_id: str | None = None,  # RFC-229: Cron job tracking for recurring rescheduling
        rail_id: str | None = None,
        verification_rules: str | None = None,
    ) -> GoalNode:
        """Create a goal in this service's ContextEngine (RFC-222 revised, RFC-625).

        Public entry point for callers (HTTP ``/autopilot/submit`` and other
        programmatic clients) to add a
        new goal to the DAG. The scheduling loop will pick it up on its
        next tick when ``self._running`` is True.

        Args:
            description: Goal description text.
            priority: 0-100, higher schedules earlier.
            parent_id: Optional parent goal id for hierarchical decomposition.
            max_retries: Override default max retries.
            max_send_backs: Override default max consensus send-backs.
            depends_on: Hard dependencies — goal won't run until these complete.
            informs: Soft dependencies — context flows from these but the
                child can still run if they haven't completed yet.
            source_file: Optional file path for goal-file-discovery use cases
                (RFC-204).
            workspace: Optional client workspace path. When set, workers execute
                in this directory and scheduling-time reservation uses it.
            cron_job_id: Optional cron job ID for tracking recurring job goals (RFC-229).
            rail_id: Optional LoopRail id (IG-678). Resolved via selector when None.
            verification_rules: Optional operator criteria (RFC-228; stored on goal).

        Returns:
            The newly-created ``GoalNode``. Callers can read ``.id`` to track it.

        Raises:
            ValueError: If goal depth limit would be exceeded or workspace invalid.
        """
        resolved_workspace: str | None = None
        if workspace is not None and str(workspace).strip():
            from soothe.workspace import validate_client_workspace

            resolved_workspace = str(validate_client_workspace(workspace))

        from soothe.rails.selector import resolve_rail_id

        resolved_rail = resolve_rail_id(
            rail_id,
            workspace=resolved_workspace,
            default_rail=getattr(self._config, "default_rail", None),
        )

        if self._monitor is not None:
            intake = await self._monitor.intake_goal(
                description,
                priority=priority,
                workspace=resolved_workspace,
                depends_on=depends_on,
                source="user",
                parent_id=parent_id,
                max_retries=max_retries,
                max_send_backs=max_send_backs,
                informs=informs,
                source_file=source_file,
            )
            if intake.status != "accepted" or not intake.goal_id:
                msg = intake.reason or f"Goal intake {intake.status}"
                raise ValueError(msg)
            goal = await self._ce.get_goal(intake.goal_id)
            if goal is None:
                msg = f"Intake accepted but goal {intake.goal_id} missing from ContextEngine"
                raise RuntimeError(msg)
        else:
            goal = await self._ce.create_goal(
                description,
                priority=priority,
                parent_id=parent_id,
                max_retries=max_retries,
                max_send_backs=max_send_backs,
                depends_on=depends_on,
                informs=informs,
                source_file=source_file,
                workspace=resolved_workspace,
            )
        # RFC-229: Set cron_job_id on goal for recurring job rescheduling
        if cron_job_id is not None:
            goal.cron_job_id = cron_job_id
            logger.debug("Goal %s linked to cron job %s", goal.id, cron_job_id)
        if verification_rules and verification_rules.strip():
            goal.verification_rules = verification_rules.strip()
        if resolved_rail and goal.parent_id is None:
            goal.rail_id = resolved_rail
            goal.role = goal.role or "root"
        # IG-677: root goals are jobs — ensure membership record exists.
        if goal.parent_id is None:
            await self._job_loop_index.ensure_job(goal.id)
            await self._bind_rail_for_job(goal)
        if self._dreaming:
            await self.wake_from_dreaming(trigger="new_task")
        await self._persist_goals()
        return goal

    async def _bind_rail_for_job(self, goal: GoalNode) -> None:
        """Bind LoopRail interpreter for a root job and fire ``job_start``."""
        if self._rail_interpreter is None or not goal.rail_id:
            return
        try:
            from soothe.autopilot.rail.interpreter import RailEvent

            await self._rail_interpreter.bind_job(
                goal.id,
                rail_id=goal.rail_id,
                workspace=goal.workspace,
            )
            await self._rail_interpreter.handle(
                RailEvent(name="job_start", job_id=goal.id, goal_id=goal.id)
            )
        except Exception:
            logger.warning(
                "Failed to bind/start rail %s for job %s",
                goal.rail_id,
                goal.id,
                exc_info=True,
            )

    def _job_id_for_goal(self, goal_id: str) -> str | None:
        """Walk parents to the root job id."""
        goal = self._ce._dag.get_goal(goal_id)
        if goal is None:
            return None
        seen: set[str] = set()
        while goal is not None and goal.parent_id and goal.parent_id not in seen:
            seen.add(goal.id)
            parent = self._ce._dag.get_goal(goal.parent_id)
            if parent is None:
                break
            goal = parent
        return goal.id if goal is not None else None

    async def _notify_rail(self, event_name: str, goal_id: str, **payload: Any) -> None:
        if self._rail_interpreter is None:
            return
        job_id = self._job_id_for_goal(goal_id)
        if job_id is None:
            return
        root = self._ce._dag.get_goal(job_id)
        if root is None or not root.rail_id:
            return
        # Rebind after restore if needed
        if job_id not in getattr(self._rail_interpreter, "_rails", {}):
            try:
                await self._rail_interpreter.bind_job(
                    job_id,
                    rail_id=root.rail_id,
                    workspace=root.workspace,
                )
            except Exception:
                logger.debug("Rail rebind failed for %s", job_id, exc_info=True)
                return
        try:
            from soothe.autopilot.rail.interpreter import RailEvent

            await self._rail_interpreter.handle(
                RailEvent(
                    name=event_name,
                    job_id=job_id,
                    goal_id=goal_id,
                    payload=dict(payload),
                )
            )
        except Exception:
            logger.warning("Rail handle %s failed for goal %s", event_name, goal_id, exc_info=True)

    async def list_goals(self, *, status: str | None = None) -> list[GoalNode]:
        """Read-through to ContextEngine for HTTP/CLI surfaces."""
        return await self._ce.list_goals(status=status)

    async def get_goal(self, goal_id: str) -> GoalNode | None:
        """Read-through to ContextEngine for HTTP/CLI surfaces."""
        return await self._ce.get_goal(goal_id)

    async def _cancel_goal_worker(self, goal: GoalNode) -> None:
        """Stop the worker for an active goal if one is assigned (RFC-222 H8)."""
        if self._worker_pool is None or not goal.assigned_loop_id:
            return
        worker = self._worker_pool.get_worker(goal.assigned_loop_id)
        if worker is None or worker.current_goal_id != goal.id:
            return
        try:
            await worker.runner.cancel()
            logger.info(
                "[Autopilot] cancel_goal: requested cancel of worker %s for goal %s",
                worker.loop_id,
                goal.id,
            )
        except Exception:
            logger.warning(
                "worker.runner.cancel() raised during cancel_goal(%s)",
                goal.id,
                exc_info=True,
            )

    async def _release_worker_after_cancel(self, goal_id: str, loop_id: str | None) -> None:
        """Release the worker slot and dispatch task after goal cancellation.

        The stream consumer (``_consume_worker_stream``) normally calls
        ``mark_idle`` when the runner stream terminates.  But when a goal is
        cancelled externally (WebSocket/CLI), the consumer task may still be
        blocked on the stream — leaving the worker slot in ``active`` status
        indefinitely (a dead worker).  This method proactively returns the
        slot to idle and cancels the consumer task so no dead workers remain.
        """
        if loop_id and self._worker_pool is not None:
            await self._worker_pool.mark_idle(loop_id, success=False)
            logger.info(
                "[Autopilot] cancel_goal: returned worker %s to idle after cancelling goal %s",
                loop_id,
                goal_id,
            )
        task = self._dispatch_tasks.pop(goal_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _cancel_open_goal_node(self, goal: GoalNode, *, reason: str) -> None:
        """Cancel one non-terminal goal: stop worker, CE transition, release workspace.

        Ensures the worker slot is returned to idle and the dispatch consumer
        task is cancelled so no dead workers remain after ``cancel_goal``.
        """
        loop_id = goal.assigned_loop_id
        await self._cancel_goal_worker(goal)
        await self._ce.cancel_goal(goal.id, reason=reason)
        if loop_id:
            try:
                await self._job_loop_index.record_end(loop_id, status="cancelled")
            except Exception:
                logger.warning(
                    "Failed to record cancelled loop %s for goal %s",
                    loop_id,
                    goal.id,
                    exc_info=True,
                )
        if self._workspace_reservation is not None:
            self._workspace_reservation.release(goal.id)
        if goal.parent_id is None:
            try:
                await self._job_loop_index.mark_job_status(goal.id, "cancelled")
            except Exception:
                logger.debug("Failed to mark job %s cancelled", goal.id, exc_info=True)

        # Return worker slot to idle pool and cancel the dispatch consumer task
        # so no dead workers are left behind after cancel_goal invocation.
        await self._release_worker_after_cancel(goal.id, loop_id)

    async def cancel_goal(self, goal_id: str, *, reason: str = "user_cancelled") -> GoalNode | None:
        """Cancel a goal and all non-terminal descendants.

        RFC-222 H8: when a goal is currently dispatched, resolve the assigned
        worker via ``WorkerPool`` and call ``worker.runner.cancel()`` to abort
        the subprocess via RFC-221's cooperative cancellation.

        RFC-626 / RFC-228: job cancel is root-goal cancel with descendant
        cascade. Already-terminal goals in the subtree are skipped so canceling
        a cancelled root still cleans pending children.

        Args:
            goal_id: Goal (or job root) to cancel.
            reason: Logged with the cancellation for audit.

        Returns:
            The GoalNode if it existed, else None.
        """
        goal = await self._ce.get_goal(goal_id)
        if goal is None:
            return None

        for gid in self._ce.collect_subtree_ids(goal_id):
            node = await self._ce.get_goal(gid)
            if node is None or node.status in TERMINAL_STATES:
                continue
            await self._cancel_open_goal_node(node, reason=reason)

        await self._persist_goals()
        return await self._ce.get_goal(goal_id)

    async def cancel_all_open_goals(self, *, reason: str = "user_cancelled") -> dict[str, Any]:
        """Cancel every non-terminal goal with a single persist.

        Args:
            reason: Logged with each cancellation for audit.

        Returns:
            Dict with ``cancelled_count`` and ``goal_ids``.
        """
        cancelled_ids: list[str] = []
        for goal in await self.list_goals():
            if goal.status in TERMINAL_STATES:
                continue
            await self._cancel_open_goal_node(goal, reason=reason)
            cancelled_ids.append(goal.id)

        await self._persist_goals()
        return {"cancelled_count": len(cancelled_ids), "goal_ids": cancelled_ids}

    async def pause_job(self, job_id: str, *, reason: str = "user_pause") -> GoalNode | None:
        """Suspend a job root and all non-terminal descendants; stop workers.

        IG-678 P1-1: unlike a bare ``CE.suspend_goal`` on the root, this
        cancels in-flight child workers so pause actually stops work.

        Args:
            job_id: Root goal id (job).
            reason: Audit reason stored on suspended goals.

        Returns:
            Updated root GoalNode, or None if missing.
        """
        root = await self._ce.get_goal(job_id)
        if root is None:
            return None

        for gid in self._ce.collect_subtree_ids(job_id):
            node = await self._ce.get_goal(gid)
            if node is None or node.status in TERMINAL_STATES:
                continue
            if node.status == "suspended":
                continue
            await self._pause_open_goal_node(node, reason=reason)

        if root.parent_id is None:
            try:
                await self._job_loop_index.mark_job_status(job_id, "paused")
            except Exception:
                logger.debug("Failed to mark job %s paused", job_id, exc_info=True)

        await self._persist_goals()
        return await self._ce.get_goal(job_id)

    async def resume_job(self, job_id: str) -> GoalNode | None:
        """Reactivate a paused job and fire rail ``user_intervention`` (IG-678 P2).

        Reactivates the root and any suspended descendants paused with it.
        """
        root = await self._ce.get_goal(job_id)
        if root is None:
            return None
        if root.status not in ("suspended", "blocked"):
            msg = f"Job {job_id} is not paused (status: {root.status})"
            raise ValueError(msg)

        for gid in self._ce.collect_subtree_ids(job_id):
            node = await self._ce.get_goal(gid)
            if node is None or node.status not in ("suspended", "blocked"):
                continue
            await self._ce.reactivate_goal(gid)

        if root.parent_id is None:
            try:
                await self._job_loop_index.mark_job_status(job_id, "running")
            except Exception:
                logger.debug("Failed to mark job %s running", job_id, exc_info=True)

        await self._notify_rail("user_intervention", job_id)
        await self._persist_goals()
        return await self._ce.get_goal(job_id)

    async def _pause_open_goal_node(self, goal: GoalNode, *, reason: str) -> None:
        """Suspend one non-terminal goal and stop its worker if assigned."""
        loop_id = goal.assigned_loop_id
        await self._cancel_goal_worker(goal)
        await self._ce.suspend_goal(goal.id, reason=reason)
        if loop_id:
            try:
                await self._job_loop_index.record_end(loop_id, status="cancelled")
            except Exception:
                logger.warning(
                    "Failed to record paused loop %s for goal %s",
                    loop_id,
                    goal.id,
                    exc_info=True,
                )
        if self._workspace_reservation is not None:
            self._workspace_reservation.release(goal.id)
        await self._release_worker_after_cancel(goal.id, loop_id)

    # ---- Internals ----------------------------------------------------

    async def _release_worker(self, loop_id: str, reason: str = "idle_timeout") -> None:
        """Release a worker from the pool.

        Args:
            loop_id: Worker to release.
            reason: Why the worker is released.
        """
        worker = await self._worker_pool.release_worker(loop_id)
        if worker is not None:
            await self._internal_bus.emit(
                InternalLoopReleasedEvent(
                    loop_id=loop_id,
                    reason=reason if reason in ("idle_timeout", "shutdown", "error") else "error",
                    goals_processed=len(worker.last_goal_ids),
                )
            )

            logger.info(
                "Released worker %s: %s (processed %d goals)",
                loop_id,
                reason,
                len(worker.last_goal_ids),
            )

    async def _run_scheduling_loop(self) -> None:
        """Main scheduling loop coroutine.

        Polls ContextEngine for ready goals, assigns loops,
        monitors loop health, releases idle loops.
        """
        poll_interval = self._config.poll_interval

        while self._running:
            try:
                # 1. Schedule ready goals
                await self._schedule_ready_goals()

                # 2. Monitor active loops
                await self._monitor_loop_health()

                # 3. Release idle loops past timeout
                await self._release_idle_loops()

                # 4. Check for dreaming transition
                if self._ce.is_dag_complete():
                    await self._enter_dreaming_mode()

                # 5. Sleep for next tick
                await asyncio.sleep(
                    self._config.dreaming_poll_interval if self._dreaming else poll_interval
                )

            except asyncio.CancelledError:
                logger.debug("Scheduling loop cancelled")
                break
            except Exception:
                logger.exception("Scheduling loop error")
                await asyncio.sleep(poll_interval)

    async def _schedule_ready_goals(self) -> None:
        """Schedule all ready goals via WorkerPool dispatch (RFC-222 Phase C+)."""
        await self._schedule_via_worker_pool()

    async def _schedule_via_worker_pool(self) -> None:
        """RFC-222 Phase C: schedule via WorkerPool + real subprocess dispatch.

        For each ready goal under capacity, optionally check workspace
        reservation, claim the goal, and spawn a stream-consuming task
        that drives ``worker.runner.run(LoopRunRequest)`` and reacts to
        the worker's terminal ``GoalCompletionChunk``.
        """
        if self._worker_pool is None:
            return

        # Bound by WorkerPool capacity and max_parallel_goals.
        pool_slots = max(0, self._config.max_loops - self._worker_pool.active_count())
        goal_slots = max(0, self._config.max_parallel_goals - self._worker_pool.active_count())
        cap_remaining = min(pool_slots, goal_slots)
        if cap_remaining <= 0:
            return

        candidates = self._ce.peek_ready_goals(limit=cap_remaining)
        for candidate in candidates:
            # Rail-bound job roots are coordinators only — skip without
            # aborting the schedule round (False would break the loop).
            if candidate.parent_id is None and candidate.rail_id:
                logger.debug(
                    "Skipping schedule for rail job root %s (rail_id=%s)",
                    candidate.id,
                    candidate.rail_id,
                )
                continue
            if not await self._try_dispatch_goal(candidate):
                break

    async def _try_dispatch_goal(self, goal: GoalNode) -> bool:
        """Attempt WorkerPool dispatch for one ready goal."""
        # Rail-bound job roots are coordinators only — children execute work.
        if goal.parent_id is None and goal.rail_id:
            logger.debug(
                "Skipping dispatch for rail job root %s (rail_id=%s)",
                goal.id,
                goal.rail_id,
            )
            return True
        if self._workspace_reservation is not None:
            ws = self._infer_workspace(goal)
            conflict = self._workspace_reservation.conflicts_with_active(
                ws, exclude_goal_id=goal.id
            )
            if conflict:
                logger.debug(
                    "Goal %s deferred: workspace %s conflicts with active goal %s",
                    goal.id,
                    ws,
                    conflict,
                )
                return False
            if not self._workspace_reservation.acquire(goal.id, ws):
                return False

        job_id = self._resolve_job_id(goal)
        worker = await self._worker_pool.pick_worker(goal, job_id=job_id)
        if worker is None:
            if self._workspace_reservation is not None:
                self._workspace_reservation.release(goal.id)
            logger.debug("No worker capacity for goal %s; deferring", goal.id)
            return False

        claimed = self._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        if claimed is None:
            logger.debug("Goal %s vanished before claim; releasing worker", goal.id)
            await self._worker_pool.mark_idle(worker.loop_id, success=True)
            if self._workspace_reservation is not None:
                self._workspace_reservation.release(goal.id)
            return False

        try:
            await self._job_loop_index.record_start(
                job_id,
                loop_id=worker.loop_id,
                goal_id=goal.id,
                attempt=goal.retry_count + 1,
            )
        except Exception:
            logger.warning(
                "Failed to record job loop start for goal %s",
                goal.id,
                exc_info=True,
            )

        await self._internal_bus.emit(
            InternalLoopAssignedEvent(
                loop_id=worker.loop_id,
                goal_id=goal.id,
                parent_goal_id=goal.parent_id,
                reused=False,
            )
        )
        await self._dispatch_to_worker(claimed, worker)
        return True

    def _resolve_job_id(self, goal: GoalNode) -> str:
        """Walk parent_id chain to the root goal (job_id)."""
        current = goal
        seen: set[str] = {goal.id}
        while current.parent_id:
            parent = self._ce.get_goal_sync(current.parent_id)
            if parent is None or parent.id in seen:
                break
            seen.add(parent.id)
            current = parent
        return current.id

    async def _dispatch_to_worker(self, goal: GoalNode, worker: Any) -> None:
        """Build the LoopRunRequest and spawn a stream-consuming task."""
        from soothe.protocols.runner import GoalDispatchEnvelope, LoopRunRequest

        bundle = await self._build_merged_context(goal)

        # RFC-222 H5: compute wall-clock deadline from config. The worker logs
        # this value; the daemon-side monitor (``_monitor_loop_health``) is
        # the authoritative enforcer — it cancels the worker on overrun.
        deadline_seconds = getattr(self._config, "goal_deadline_seconds", None)

        request = LoopRunRequest(
            loop_id=worker.loop_id,
            thread_id=f"autopilot__goal_{goal.id}__attempt_{goal.retry_count + 1}",
            user_input="",
            client_workspace=goal.workspace,
            autopilot_job=GoalDispatchEnvelope(
                goal_id=goal.id,
                goal_description=goal.description,
                merged_context=bundle,
                deadline_seconds=deadline_seconds,
                attempt=goal.retry_count + 1,
            ),
            autonomous=True,
            max_iterations=self._config.max_iterations,
        )

        task = asyncio.create_task(self._consume_worker_stream(goal.id, worker, request))
        worker.active_task = task
        self._dispatch_tasks[goal.id] = task
        logger.info(
            "[Autopilot] dispatched goal %s to worker %s (attempt %d)",
            goal.id,
            worker.loop_id,
            request.autopilot_job.attempt,
        )

    async def _build_merged_context(self, goal: GoalNode) -> Any:
        """Build the GoalDispatchContextBundle for ``goal``.

        Hooks the ``ContextProjector`` if one was wired, then attaches
        operator guidance accumulated on the goal (and job-scoped root).
        """
        from soothe.autopilot.engine_models import GoalDispatchContextBundle

        projector = getattr(self, "_context_projector", None)
        if projector is None:
            bundle = GoalDispatchContextBundle()
        else:
            try:
                bundle = await projector.project(goal, self._ce._dag.goals)
            except Exception:
                logger.warning(
                    "ContextProjector failed for goal %s; falling back to empty bundle",
                    goal.id,
                    exc_info=True,
                )
                bundle = GoalDispatchContextBundle()

        guidance = _collect_operator_guidance(goal, self._ce._dag.goals)
        if guidance:
            return bundle.model_copy(update={"operator_guidance": guidance})
        return bundle

    async def _emit_goal_completed(self, goal_id: str, *, loop_id: str | None = None) -> None:
        """Notify monitor subscribers that a goal completed."""
        lid = loop_id or ""
        if not lid:
            goal = await self._ce.get_goal(goal_id)
            lid = (goal.assigned_loop_id if goal else None) or ""
        await self._internal_bus.emit(
            InternalGoalCompletedEvent(goal_id=goal_id, loop_id=lid, plan_result={})
        )
        await self._notify_rail("goal_completed", goal_id)

    async def _emit_goal_failed(
        self,
        goal_id: str,
        *,
        evidence: dict[str, Any] | None = None,
        error_message: str | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Notify monitor subscribers that a goal failed."""
        lid = loop_id or ""
        if not lid:
            goal = await self._ce.get_goal(goal_id)
            lid = (goal.assigned_loop_id if goal else None) or ""
        await self._internal_bus.emit(
            InternalGoalFailedEvent(
                goal_id=goal_id,
                loop_id=lid,
                evidence=evidence or {},
                error_message=error_message,
            )
        )
        await self._notify_rail("goal_failed", goal_id, error=error_message)

    async def _mirror_plan_decision(self, goal_id: str, payload: dict[str, Any]) -> None:
        """Apply worker ``plan_decision`` steps onto the Autopilot CE goal (IG-689).

        Worker StrangeLoop CEs are loop-scoped; ``autopilot top`` reads the daemon
        Autopilot CE. Mirror planned StepDAG nodes so the live forest can list STEPs.
        """
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            return
        iteration = int(payload.get("iteration") or 0)
        added = 0
        for raw in steps:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("id") or "").strip()
            if not sid:
                continue
            deps = [str(d) for d in (raw.get("dependencies") or []) if d]
            desc = str(raw.get("description") or "").strip()
            if sid in goal.steps.nodes:
                existing = goal.steps.nodes[sid]
                if existing.status == "pending" and deps:
                    existing.dependencies = deps
                if desc and not existing.description:
                    existing.description = desc
                continue
            goal.steps.add_step(
                StepNode(
                    id=sid,
                    description=desc,
                    dependencies=deps,
                    plan_iteration=iteration,
                )
            )
            added += 1
        if added or steps:
            goal.touch()
            await self._persist_goals()

    async def _mirror_step_started(self, goal_id: str, payload: dict[str, Any]) -> None:
        """Mark a step ``active`` on the Autopilot CE goal when execution begins."""
        sid = str(payload.get("step_id") or "").strip()
        if not sid:
            return
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return
        if sid not in goal.steps.nodes:
            desc = str(payload.get("description") or sid).strip() or sid
            goal.steps.add_step(StepNode(id=sid, description=desc))
        await self._ce.activate_step(goal_id, sid)

    async def _mirror_step_completed(self, goal_id: str, payload: dict[str, Any]) -> None:
        """Apply worker ``step_completed`` onto the Autopilot CE goal (IG-689)."""
        sid = str(payload.get("step_id") or "").strip()
        if not sid:
            return
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return
        if sid not in goal.steps.nodes:
            desc = str(payload.get("description") or sid).strip() or sid
            goal.steps.add_step(StepNode(id=sid, description=desc))
        execution = StepExecution(
            duration_ms=int(payload.get("duration_ms") or 0),
            tool_call_count=int(payload.get("tool_call_count") or 0),
            error=str(payload["error"]) if payload.get("error") else None,
        )
        if payload.get("success", True):
            await self._ce.complete_step(goal_id, sid, execution)
        else:
            await self._ce.fail_step(goal_id, sid, execution)

    async def _mirror_contribution_steps(self, goal_id: str, contribution: Any) -> None:
        """Backfill StepDAG from completion contribution when progress was missed."""
        plan_steps = getattr(contribution, "plan_steps_executed", None) or []
        if not plan_steps:
            return
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return
        for step in plan_steps:
            sid = str(getattr(step, "id", "") or "").strip()
            if not sid:
                continue
            action = str(getattr(step, "action", "") or "").strip()
            outcome = str(getattr(step, "outcome", "") or "completed").lower()
            if sid not in goal.steps.nodes:
                goal.steps.add_step(StepNode(id=sid, description=action or sid))
            if goal.steps.nodes[sid].status in ("completed", "failed", "skipped"):
                continue
            execution = StepExecution()
            if outcome in {"failed", "failure", "error"}:
                await self._ce.fail_step(goal_id, sid, execution)
            elif outcome in {"skipped", "skip"}:
                await self._ce.skip_step(goal_id, sid)
            else:
                await self._ce.complete_step(goal_id, sid, execution)

    async def _apply_worker_progress_event(self, goal_id: str, data: dict[str, Any]) -> None:
        """Route autopilot progress custom chunks onto Autopilot CE StepDAG."""
        ctype = str(data.get("type") or "")
        prefix = "soothe.internal.autopilot.progress."
        if not ctype.startswith(prefix):
            return
        event = ctype[len(prefix) :]
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {k: v for k, v in data.items() if k not in {"type", "goal_id", "payload"}}
        try:
            if event == "plan_decision":
                await self._mirror_plan_decision(goal_id, payload)
            elif event == "step_started":
                await self._mirror_step_started(goal_id, payload)
            elif event == "step_completed":
                await self._mirror_step_completed(goal_id, payload)
        except Exception:
            logger.warning(
                "Failed to mirror worker progress %s onto goal %s",
                event,
                goal_id,
                exc_info=True,
            )

    async def _consume_worker_stream(self, goal_id: str, worker: Any, request: Any) -> None:
        """Drain a worker's stream and react to ``GoalCompletionChunk``.

        Progress events (``plan_decision``, ``step_started``, ``step_completed``)
        are mirrored onto the Autopilot CE StepDAG so ``autopilot top`` can list
        STEPs with live status (IG-689).

        On a successful completion: mark goal completed in ContextEngine,
        store the contribution if a context store is wired, return the
        worker to the idle queue, release any workspace reservation.

        On exception or non-completion termination: mark goal failed.
        """
        from soothe.autopilot.engine_models import (
            EvidenceBundle,
            GoalDispatchContextContribution,
        )

        completion_seen = False
        try:
            async for chunk in worker.runner.run(request):
                # chunk = (namespace, mode, data) per StreamChunk shape.
                _, mode, data = chunk
                if mode != "custom" or not isinstance(data, dict):
                    continue
                ctype = data.get("type", "")
                if isinstance(ctype, str) and ctype.startswith(
                    "soothe.internal.autopilot.progress."
                ):
                    await self._apply_worker_progress_event(goal_id, data)
                    continue
                if ctype != "soothe.internal.autopilot.goal_completion":
                    continue

                completion_seen = True
                outcome = data.get("outcome", "failed")
                contribution_dict = data.get("context_contribution") or {}
                try:
                    contribution = GoalDispatchContextContribution.model_validate(contribution_dict)
                except Exception:
                    logger.warning(
                        "Invalid GoalDispatchContextContribution for goal %s; using empty",
                        goal_id,
                        exc_info=True,
                    )
                    contribution = GoalDispatchContextContribution()

                try:
                    await self._mirror_contribution_steps(goal_id, contribution)
                except Exception:
                    logger.warning(
                        "Failed to backfill steps from contribution for goal %s",
                        goal_id,
                        exc_info=True,
                    )

                # RFC-204 Group C: Apply directives BEFORE outcome handling.
                # This creates subgoals that inherit from the active goal.
                directives_data = data.get("goal_directives", [])
                if directives_data:
                    try:
                        from soothe_sdk.protocols.planner import GoalDirective

                        directives = [GoalDirective(**d) for d in directives_data]
                        created_ids = await self._ce.apply_directives(
                            directives,
                            source_goal_id=goal_id,
                        )
                        logger.info(
                            "Applied %d directives from goal %s, created goals: %s",
                            len(directives),
                            goal_id,
                            created_ids,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to apply directives for goal %s",
                            goal_id,
                            exc_info=True,
                        )

                # Persist the contribution if a store is wired.
                store = getattr(self, "_context_store", None)
                if store is not None:
                    try:
                        await store.put(goal_id, contribution)
                    except Exception:
                        logger.warning(
                            "Failed to persist contribution for goal %s",
                            goal_id,
                            exc_info=True,
                        )

                # React to outcome by transitioning the goal.
                if outcome == "completed":
                    await self._apply_consensus_and_finalize(
                        goal_id,
                        evidence_summary=str(data.get("evidence_summary", "")),
                        loop_id=worker.loop_id,
                        contribution=contribution,
                    )
                elif outcome == "needs_replan":
                    # IG-680: clarification / empty PlanResult → suspend, not fail.
                    narrative = (
                        str(data.get("evidence_summary", "")).strip()
                        or str(data.get("error_text", "")).strip()
                        or "Worker needs replan (insufficient terminal evidence)"
                    )
                    try:
                        await self._ce.suspend_goal(goal_id, reason=narrative)
                    except Exception:
                        logger.exception("suspend_goal raised for needs_replan %s", goal_id)
                else:  # failed
                    evidence = EvidenceBundle(
                        structured={
                            "outcome": outcome,
                            "plan_result_status": data.get("plan_result_status"),
                        },
                        narrative=str(data.get("evidence_summary", "")).strip()
                        or str(data.get("error_text", "")).strip()
                        or "Worker reported failure without evidence summary",
                        source="layer2_execute",
                    )
                    try:
                        await self._ce.fail_goal(goal_id, evidence=evidence)
                        await self._emit_goal_failed(
                            goal_id,
                            evidence=evidence.model_dump(mode="json"),
                            error_message=evidence.narrative,
                            loop_id=worker.loop_id,
                        )
                    except Exception:
                        logger.exception("fail_goal raised for goal %s", goal_id)

                break  # one completion chunk per dispatch is the contract
        except Exception:
            logger.exception(
                "Worker stream raised for goal %s on worker %s",
                goal_id,
                worker.loop_id,
            )

        if not completion_seen:
            # Worker stream ended without a completion chunk — treat as failed.
            from soothe.autopilot.engine_models import EvidenceBundle as _EvBundle

            try:
                await self._ce.fail_goal(
                    goal_id,
                    evidence=_EvBundle(
                        structured={"outcome": "no_completion_chunk"},
                        narrative="Worker exited without emitting GoalCompletionChunk",
                        source="layer2_execute",
                    ),
                )
                await self._emit_goal_failed(
                    goal_id,
                    evidence={"outcome": "no_completion_chunk"},
                    error_message="Worker exited without emitting GoalCompletionChunk",
                    loop_id=worker.loop_id,
                )
            except Exception:
                logger.debug("fail_goal raised on missing completion", exc_info=True)

        # Always release worker + reservation, even on errors.
        end_status = "completed" if completion_seen else "failed"
        # Prefer outcome from CE if available.
        finished = await self._ce.get_goal(goal_id)
        if finished is not None:
            if finished.status == "completed":
                end_status = "completed"
            elif finished.status in ("cancelled", "failed", "suspended"):
                end_status = "failed" if finished.status != "cancelled" else "cancelled"
        try:
            await self._job_loop_index.record_end(
                worker.loop_id,
                status=end_status,  # type: ignore[arg-type]
            )
        except Exception:
            logger.warning(
                "Failed to record job loop end for goal %s loop %s",
                goal_id,
                worker.loop_id,
                exc_info=True,
            )
        if self._worker_pool is not None:
            await self._worker_pool.mark_idle(worker.loop_id, success=completion_seen)
        if self._workspace_reservation is not None:
            self._workspace_reservation.release(goal_id)

        self._dispatch_tasks.pop(goal_id, None)
        await self._persist_goals()

    async def _apply_consensus_and_finalize(
        self,
        goal_id: str,
        *,
        evidence_summary: str,
        loop_id: str | None = None,
        contribution: Any | None = None,
    ) -> None:
        """RFC-204 / IG-680: validate worker completion before accepting the goal.

        Never falls back to ``goal.description`` as the agent response when
        evidence is empty — that path caused false send_backs in eval.
        """
        from soothe.autopilot.consensus import evaluate_goal_completion
        from soothe.autopilot.evidence_grounding import (
            enrich_workspace_evidence,
            format_contribution_evidence,
        )

        goal = await self._ce.get_goal(goal_id)
        if goal is None:
            return

        files = getattr(contribution, "files_touched", None) if contribution else None
        findings = getattr(contribution, "findings", None) if contribution else None
        plan_steps = getattr(contribution, "plan_steps_executed", None) if contribution else None
        tool_stats = getattr(contribution, "tool_call_stats", None) if contribution else None
        grounded = format_contribution_evidence(
            evidence_summary=evidence_summary,
            files_touched=files,
            findings=findings,
            plan_steps=plan_steps,
            tool_call_stats=tool_stats,
        )
        # Always attach structural workspace evidence when present — a thin
        # evidence_summary alone previously skipped the probe and caused
        # false send_backs despite on-disk deliverables.
        probe = enrich_workspace_evidence(goal.workspace)
        if probe:
            grounded = f"{grounded}\n{probe}".strip() if grounded else probe
        if not grounded:
            reason = "insufficient evidence for consensus (empty summary and workspace probe)"
            logger.warning("Consensus suspend for %s: %s", goal_id, reason)
            try:
                await self._ce.suspend_goal(goal_id, reason=reason)
            except Exception:
                logger.exception(
                    "suspend_goal raised after empty consensus evidence for %s", goal_id
                )
            return

        # Persist findings onto the goal for post-completion context (IG-680 P1-7).
        if findings:
            try:
                for finding in findings[:20]:
                    summary = getattr(finding, "summary", None) or str(finding)
                    if summary and summary not in goal.findings:
                        goal.findings.append(str(summary)[:500])
            except Exception:
                logger.debug("Failed to attach findings to goal %s", goal_id, exc_info=True)

        response_text = grounded
        try:
            decision, reasoning = await evaluate_goal_completion(
                goal.description,
                response_text,
                grounded,
                model=self._consensus_model,
            )
        except Exception:
            logger.exception("Consensus evaluation failed for goal %s", goal_id)
            decision, reasoning = "suspend", "Consensus evaluation failed"

        # Structural override: markers + pytest PASS beat LLM send_back/suspend
        # that ignore the probe (eval false-negative pattern).
        if decision != "accept" and "pytest -q: PASS" in probe:
            prior = decision
            logger.info(
                "Consensus override accept for %s: workspace pytest PASS (llm decision was %s)",
                goal_id,
                prior,
            )
            decision = "accept"
            reasoning = (
                "Accepted via workspace verification (pytest PASS + deliverable "
                f"markers). Prior LLM decision was {prior}: {reasoning}"
            )

        try:
            if decision == "accept":
                await self._ce.complete_goal(goal_id)
                await self._emit_goal_completed(goal_id, loop_id=loop_id)
            elif decision == "send_back":
                await self._ce.send_back_goal(goal_id, reason=reasoning)
                await self._notify_rail("goal_send_back", goal_id, reason=reasoning)
            else:
                await self._ce.suspend_goal(goal_id, reason=reasoning)
        except Exception:
            logger.exception("Goal transition failed after consensus for %s", goal_id)

    @staticmethod
    def _infer_workspace(goal: GoalNode) -> str:
        """Workspace path for scheduling-time reservation (RFC-222).

        Uses the goal's client workspace when set; otherwise a per-goal sentinel
        so goals without an explicit workspace still get distinct reservation slots.
        """
        if goal.workspace:
            return goal.workspace
        return f"$autopilot/goal/{goal.id}"

    async def _schedule_goal(self, goal_id: str) -> None:
        """Schedule a single ready goal to a worker."""
        goal = await self._ce.get_goal(goal_id)
        if not goal:
            logger.warning("Goal %s not found for scheduling", goal_id)
            return

        ready = self._ce.peek_ready_goals(limit=self._config.max_loops)
        if not any(g.id == goal_id for g in ready):
            return

        candidate = next(g for g in ready if g.id == goal_id)
        if not await self._try_dispatch_goal(candidate):
            logger.warning("No worker capacity for goal %s", goal_id)

    async def _monitor_loop_health(self) -> None:
        """Monitor active workers — enforce wall-clock deadlines (RFC-222 H5).

        For each active worker, if ``goal_deadline_seconds`` is configured and
        the worker has been busy longer than that, request cooperative
        cancellation via ``worker.runner.cancel()`` and fail the goal with a
        deadline_exceeded evidence bundle. The stream consumer task will see
        the cancel and unwind cleanly (releasing reservation + worker).
        """
        if self._worker_pool is None:
            return

        deadline = getattr(self._config, "goal_deadline_seconds", None)
        if not deadline or deadline <= 0:
            return

        from soothe.autopilot.engine_models import EvidenceBundle

        now = datetime.now(UTC)
        for worker in self._worker_pool.active_workers():
            started = getattr(worker, "dispatch_started_at", None)
            goal_id = worker.current_goal_id
            if started is None or goal_id is None:
                continue
            elapsed = (now - started).total_seconds()
            if elapsed < deadline:
                continue

            logger.warning(
                "[Autopilot] H5: goal %s on %s exceeded deadline (%.1fs > %.1fs); cancelling",
                goal_id,
                worker.loop_id,
                elapsed,
                deadline,
            )
            # Request cooperative cancel of the worker first; the stream
            # consumer task will then see termination and clean up.
            try:
                await worker.runner.cancel()
            except Exception:
                logger.debug("worker.runner.cancel() raised for %s", worker.loop_id, exc_info=True)

            # Transition the goal to failed so backoff/retry logic can react.
            try:
                await self._ce.fail_goal(
                    goal_id,
                    evidence=EvidenceBundle(
                        structured={
                            "reason": "deadline_exceeded",
                            "elapsed_seconds": round(elapsed, 2),
                            "deadline_seconds": float(deadline),
                            "loop_id": worker.loop_id,
                        },
                        narrative=(
                            "Goal exceeded deadline_seconds budget; "
                            "worker cancelled by autopilot monitor."
                        ),
                        source="layer3_reflect",
                    ),
                )
            except Exception:
                logger.debug(
                    "fail_goal raised after deadline cancel for %s", goal_id, exc_info=True
                )

    async def _release_idle_loops(self) -> None:
        """Release idle workers past timeout."""
        timeout = self._config.loop_idle_timeout
        now = datetime.now(UTC)

        for worker in self._worker_pool.idle_workers():
            if worker.idle_since:
                elapsed = (now - worker.idle_since).total_seconds()
                if elapsed > timeout:
                    await self._release_worker(worker.loop_id, reason="idle_timeout")

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

    async def force_dream(self) -> None:
        """Force-enter dreaming mode (WS ``autopilot_dream`` / programmatic).

        Prefer ``agent.autopilot.dreaming_enabled`` and automatic DAG-complete
        entry over manual force; this remains for wire/protocol callers.
        """
        if not self._config.dreaming_enabled:
            logger.info("Dreaming disabled in config; ignoring force_dream")
            return
        await self._enter_dreaming_mode()

    _GOALS_SNAPSHOT_KEY = "autopilot:goals:snapshot"

    async def _persist_goals(self) -> None:
        """Persist ContextEngine DAG snapshot when a store is wired."""
        if self._goal_persist_store is None:
            return
        try:
            await self._goal_persist_store.save(
                self._GOALS_SNAPSHOT_KEY,
                self._ce.get_dag_snapshot().model_dump(mode="json"),
            )
            self._persist_fail_count = 0
        except Exception:
            self._persist_fail_count += 1
            log = logger.error if self._persist_fail_count >= 3 else logger.warning
            log(
                "Failed to persist autopilot goals snapshot (consecutive=%d)",
                self._persist_fail_count,
                exc_info=True,
            )

    async def _restore_persisted_goals(self) -> None:
        """Restore ContextEngine DAG from persistence and recover stranded actives."""
        if self._goal_persist_store is None:
            return
        try:
            data = await self._goal_persist_store.load(self._GOALS_SNAPSHOT_KEY)
            if isinstance(data, dict) and "goals" in data:
                from soothe.context.models import GoalStepDAGSnapshot

                snapshot = GoalStepDAGSnapshot.model_validate(data)
                self._ce._dag.restore_from_snapshot(snapshot)
        except Exception:
            logger.warning("Failed to restore autopilot goals snapshot", exc_info=True)
        recovered = await self._ce.recover()
        if recovered:
            logger.warning(
                "[Autopilot] crash recovery: reset %d active goal(s) → pending: %s",
                len(recovered),
                ", ".join(recovered),
            )

    def status(self) -> dict[str, Any]:
        """Get AutopilotService status.

        Returns:
            Status dict with running, dreaming, loop pool stats.
        """
        return {
            "running": self._running,
            "dreaming": self._dreaming,
            "loop_pool": {
                "active": self._worker_pool.active_count(),
                "idle": self._worker_pool.idle_count(),
                "total": self._worker_pool.total_count(),
                "max": self._worker_pool.max_loops,
            },
            "goals": {
                "completed": sum(1 for g in self._ce.get_all_goals() if g.status == "completed"),
            },
            "config": {
                "max_loops": self._config.max_loops,
                "loop_idle_timeout": self._config.loop_idle_timeout,
                "poll_interval": self._config.poll_interval,
            },
        }

    async def list_job_loops(self, job_id: str) -> list[dict[str, Any]]:
        """Return durable loop membership history for a job (IG-677)."""
        entries = await self._job_loop_index.list_loops(job_id)
        return [e.model_dump(mode="json") for e in entries]

    async def top_snapshot(self, *, include_terminal: bool = False) -> dict[str, Any]:
        """Build jobs → goals → loops snapshot for CLI top (IG-679 / IG-688).

        Filters use CE ``TERMINAL_STATES`` for goals (unless
        ``include_terminal``) and ``status == "active"`` for JobLoopIndex
        entries. StepDAG under kept goals is preserved for ``steps=on``.
        See RFC-228 §autopilot_top.

        Args:
            include_terminal: When ``True``, keep completed/failed/cancelled
                goals and fully terminal jobs (CLI ``a`` / ``--all``).

        Returns:
            Dict with ``running``, ``dreaming``, ``loop_pool``, ``generated_at``,
            and ``jobs`` (each with filtered ``dag`` and active ``loops``).
        """
        from soothe.autopilot.top_snapshot import build_top_job_entry, sort_top_jobs

        status = self.status()
        goals = await self.list_goals()
        roots = [g for g in goals if g.parent_id is None]
        jobs: list[dict[str, Any]] = []
        for root in roots:
            dag = await self.dag_snapshot(root.id)
            loops = await self.list_job_loops(root.id)
            created = root.created_at
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)
            entry = build_top_job_entry(
                job_id=root.id,
                status=str(root.status),
                priority=int(root.priority),
                description=root.description,
                workspace=root.workspace,
                dag=dag,
                loops=loops,
                created_at=created_at,
                include_terminal=include_terminal,
            )
            if entry is not None:
                jobs.append(entry)
        return {
            "running": status.get("running", False),
            "dreaming": status.get("dreaming", False),
            "loop_pool": status.get("loop_pool", {}),
            "generated_at": datetime.now(UTC).isoformat(),
            "jobs": sort_top_jobs(jobs),
        }

    async def dag_snapshot(self, root_goal_id: str) -> dict[str, Any]:
        """Export job subtree for visualization (RFC-228 / CLI top).

        Membership is the ``parent_id`` subtree (same as cancel / rail
        descendants). Tree ``edges`` are parent → child so CLI ``job`` /
        ``top`` can nest internal goals. Per-node ``depends_on`` remains
        scheduling metadata (do not invert it into tree edges — rail often
        makes the root depend on a child planner).

        Args:
            root_goal_id: Root goal ID (job_id) to traverse from.

        Returns:
            Dict with ``nodes``, ``edges``, and ``root_id``.
            Nodes contain: id, description, status, priority, depends_on,
            parent_id, assigned_loop_id, steps_completed, steps_total,
            tool_calls, optional ``steps`` StepDAG, summary/findings when
            completed.
            Edges contain: source=parent_id, target=child id.
        """
        goals = await self._ce.list_goals()
        goal_by_id: dict[str, GoalNode] = {g.id: g for g in goals}

        # parent_id hierarchy (job membership) — not depends_on inversion
        children_map: dict[str, list[str]] = {}
        for g in goals:
            if g.parent_id:
                children_map.setdefault(g.parent_id, []).append(g.id)

        descendants: list[GoalNode] = []
        visited: set[str] = set()
        queue = [root_goal_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            goal = goal_by_id.get(current_id)
            if goal is not None:
                descendants.append(goal)

            for child_id in children_map.get(current_id, []):
                if child_id not in visited:
                    queue.append(child_id)

        # Build nodes for React Flow / CLI top (include planned StepDAG)
        nodes: list[dict[str, Any]] = []
        for g in descendants:
            step_payload = _serialize_goal_steps(g)
            node: dict[str, Any] = {
                "id": g.id,
                "description": (g.description[:100] if len(g.description) > 100 else g.description),
                "status": g.status,
                "priority": g.priority,
                "depends_on": list(g.depends_on or []),
                "parent_id": g.parent_id,
                "assigned_loop_id": g.assigned_loop_id,
                "steps_completed": step_payload["steps_completed"],
                "steps_total": step_payload["steps_total"],
                "tool_calls": 0,
                "created_at": (
                    g.created_at.isoformat()
                    if hasattr(g.created_at, "isoformat")
                    else str(g.created_at)
                ),
            }
            if step_payload["steps"] is not None:
                node["steps"] = step_payload["steps"]
            # Report fields fill counts only when StepDAG is empty
            if g.report is not None:
                report = g.report if isinstance(g.report, dict) else {}
                if step_payload["steps_total"] == 0:
                    node["steps_completed"] = report.get("steps_completed", 0) or 0
                    node["steps_total"] = report.get("steps_total", 0) or 0
                node["tool_calls"] = report.get("tool_calls", 0) or 0
                if g.status == "completed":
                    node["summary"] = report.get("summary")
                    node["findings"] = report.get("findings") or []
            nodes.append(node)

        # Hierarchy edges for ASCII / React tree (parent → child)
        edges: list[dict[str, str]] = []
        for g in descendants:
            if g.parent_id and g.parent_id in visited:
                edges.append({"source": g.parent_id, "target": g.id})

        return {
            "nodes": nodes,
            "edges": edges,
            "root_id": root_goal_id,
        }


def _serialize_goal_steps(goal: GoalNode) -> dict[str, Any]:
    """Build planned StepDAG payload and live counts for dag/top snapshots.

    Returns:
        Dict with ``steps_completed``, ``steps_total``, and optional ``steps``
        (``nodes`` + ``edges``) when the goal has planned steps.
    """
    step_dag = getattr(goal, "steps", None)
    nodes_map = getattr(step_dag, "nodes", None) if step_dag is not None else None
    if not nodes_map:
        return {"steps_completed": 0, "steps_total": 0, "steps": None}

    step_nodes: list[dict[str, Any]] = []
    step_edges: list[dict[str, str]] = []
    completed = 0
    for sn in nodes_map.values():
        desc = sn.description or ""
        if len(desc) > 80:
            desc = desc[:80]
        status = str(sn.status)
        if status == "completed":
            completed += 1
        step_nodes.append(
            {
                "id": sn.id,
                "description": desc,
                "status": status,
                "dependencies": list(sn.dependencies or []),
            }
        )
        for dep in sn.dependencies or []:
            step_edges.append({"source": str(dep), "target": str(sn.id)})
    return {
        "steps_completed": completed,
        "steps_total": len(step_nodes),
        "steps": {"nodes": step_nodes, "edges": step_edges},
    }


def _collect_operator_guidance(
    goal: GoalNode,
    all_goals: dict[str, GoalNode],
) -> list[str]:
    """Collect RFC-228 guidance texts for a goal about to be dispatched.

    Includes guidance on the goal itself plus job-scoped entries on the root.
    """
    texts: list[str] = []
    seen: set[str] = set()

    def _append(entries: list[dict[str, Any]] | None) -> None:
        for entry in entries or []:
            text = str(entry.get("text") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            texts.append(text)

    _append(goal.guidance_accumulated)

    root: GoalNode | None = goal
    visited: set[str] = set()
    while root is not None and root.parent_id and root.parent_id not in visited:
        visited.add(root.id)
        parent = all_goals.get(root.parent_id)
        if parent is None:
            break
        root = parent
    if root is not None and root.id != goal.id:
        job_scoped = [
            e for e in (root.guidance_accumulated or []) if str(e.get("scope") or "") == "job"
        ]
        _append(job_scoped)

    return texts
