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

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.events.internal_bus import InternalEventBus
from soothe.foundation.events.internal_events import (
    INTERNAL_GOAL_STATE_CHANGED,
    INTERNAL_GOAL_UNBLOCKED,
    INTERNAL_GOALS_READY,
    InternalAutopilotAwakeEvent,
    InternalAutopilotDreamingEvent,
    InternalAutopilotStartedEvent,
    InternalAutopilotStoppedEvent,
    InternalGoalsReadyEvent,
    InternalGoalStateChangedEvent,
    InternalGoalUnblockedEvent,
    InternalLoopAssignedEvent,
    InternalLoopIdleEvent,
    InternalLoopPoolChangedEvent,
    InternalLoopReleasedEvent,
)

if TYPE_CHECKING:
    from soothe.config.models import AutonomousConfig
    from soothe.foundation.autopilot.monitor.monitor import AutopilotMonitor

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
        config: AutonomousConfig (RFC-222 fields live in this unified config).
        internal_bus: Internal EventBus for coordination.
        monitor: Optional AutopilotMonitor for proactive DAG monitoring.
    """

    def __init__(
        self,
        ce: ContextEngine,
        config: AutonomousConfig,
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
            config: Project-level AutonomousConfig carrying RFC-222 loop pool
                fields (``max_loops``, ``loop_idle_timeout``, ``poll_interval``,
                ``dreaming_poll_interval``).
            internal_bus: Internal EventBus (uses singleton if None).
            monitor: Optional AutopilotMonitor for proactive DAG monitoring.
                When provided (daemon mode), handles goal intake, verification,
                and dreaming coordination.
            subscribe_to_bus: When True (default), subscribe handlers to the
                bus immediately. RFC-222 (revised, Phase B): the daemon
                constructs a daemon-owned ``AutopilotService`` alongside the
                per-runner one — they share the singleton bus, so the daemon
                instance must pass ``subscribe_to_bus=False`` to avoid
                double-handling every event. Phase D will retire the
                per-runner instance and the daemon's will start subscribing.
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

        # RFC-222: parallel-execution concurrency control.
        # `_assignment_lock` makes loop assignment atomic so two concurrent
        # execute_goal calls can't reach into _assign_loop_with_lineage at
        # the same time and double-claim a loop slot.
        # `_execution_semaphore` caps the number of in-flight execute_goal
        # runs at `max_parallel_goals` (independent of `max_loops`, which
        # caps worker capacity — loops can be reused for lineage).
        self._assignment_lock = asyncio.Lock()
        self._execution_semaphore = asyncio.Semaphore(self._config.max_parallel_goals)

        # RFC-222 revised (Phase C): WorkerPool-driven dispatch.
        self._runner_factory = runner_factory
        from soothe.foundation.autopilot.service.worker_pool import WorkerPool

        self._worker_pool = WorkerPool(factory=runner_factory, max_loops=self._config.max_loops)
        self._workspace_reservation = workspace_reservation
        self._consensus_model = consensus_model
        self._goal_persist_store = goal_persist_store
        self._scheduler: Any = None  # SchedulerService | None
        self._context_store: Any = None
        self._context_projector: Any = None
        self._dispatch_tasks: dict[str, asyncio.Task] = {}  # goal_id → consumer task

        if subscribe_to_bus:
            self._setup_subscriptions()
            self._subscribed = True

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
            await self._schedule_next_goal()

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

        Returns:
            The newly-created ``GoalNode``. Callers can read ``.id`` to track it.

        Raises:
            ValueError: If goal depth limit would be exceeded or workspace invalid.
        """
        resolved_workspace: str | None = None
        if workspace is not None and str(workspace).strip():
            from soothe.foundation.workspace import validate_client_workspace

            resolved_workspace = str(validate_client_workspace(workspace))

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
        if self._dreaming:
            await self.wake_from_dreaming(trigger="new_task")
        await self._persist_goals()
        return goal

    async def list_goals(self, *, status: str | None = None) -> list[GoalNode]:
        """Read-through to ContextEngine for HTTP/CLI surfaces."""
        return await self._ce.list_goals(status=status)

    async def get_goal(self, goal_id: str) -> GoalNode | None:
        """Read-through to ContextEngine for HTTP/CLI surfaces."""
        return await self._ce.get_goal(goal_id)

    async def cancel_goal(self, goal_id: str, *, reason: str = "user_cancelled") -> GoalNode | None:
        """Cancel a goal: stop the worker (if any) and transition to ``cancelled``.

        RFC-222 H8: when the goal is currently dispatched, resolve the assigned
        worker via ``WorkerPool`` and call ``worker.runner.cancel()`` to abort
        the subprocess via RFC-221's cooperative cancellation.

        Args:
            goal_id: Goal to cancel.
            reason: Logged with the cancellation for audit.

        Returns:
            The GoalNode if it existed, else None.
        """
        goal = await self._ce.get_goal(goal_id)
        if goal is None:
            return None

        # H8: resolve and cancel the worker if a real-dispatch pool is wired
        # and the goal is currently active on a worker.
        if self._worker_pool is not None and goal.assigned_loop_id:
            worker = self._worker_pool.get_worker(goal.assigned_loop_id)
            if worker is not None and worker.current_goal_id == goal_id:
                try:
                    await worker.runner.cancel()
                    logger.info(
                        "[Autopilot] cancel_goal: requested cancel of worker %s for goal %s",
                        worker.loop_id,
                        goal_id,
                    )
                except Exception:
                    logger.warning(
                        "worker.runner.cancel() raised during cancel_goal(%s)",
                        goal_id,
                        exc_info=True,
                    )

        await self._ce.cancel_goal(goal_id, reason=reason)
        if self._workspace_reservation is not None:
            self._workspace_reservation.release(goal_id)
        await self._persist_goals()
        return await self._ce.get_goal(goal_id)

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

        Polls GoalEngine for ready goals, assigns loops,
        monitors loop health, releases idle loops.
        """
        poll_interval = self._config.poll_interval

        while self._running:
            try:
                # 1. Check scheduled tasks (if enabled)
                await self._check_scheduled_tasks()

                # 2. Schedule ready goals
                await self._schedule_ready_goals()

                # 3. Monitor active loops
                await self._monitor_loop_health()

                # 4. Release idle loops past timeout
                await self._release_idle_loops()

                # 5. Check for dreaming transition
                if self._ce.is_dag_complete():
                    await self._enter_dreaming_mode()

                # 6. Sleep for next tick
                await asyncio.sleep(
                    self._config.dreaming_poll_interval if self._dreaming else poll_interval
                )

            except asyncio.CancelledError:
                logger.debug("Scheduling loop cancelled")
                break
            except Exception:
                logger.exception("Scheduling loop error")
                await asyncio.sleep(poll_interval)

    async def _check_scheduled_tasks(self) -> None:
        """Check scheduled tasks and create goals for due tasks."""
        if not self._config.scheduler_enabled:
            return

        scheduler = self._get_or_init_scheduler()
        if scheduler is None:
            return

        due = scheduler.get_due_tasks()
        for task in due:
            scheduler.mark_running(task.id)
            try:
                await self.submit_task(task.description, priority=task.priority)
                if task.schedule.kind in ("every", "cron"):
                    scheduler.schedule_next(task.id)
                else:
                    scheduler.mark_completed(task.id)
            except Exception:
                logger.warning(
                    "Failed to create goal from scheduled task %s",
                    task.id,
                    exc_info=True,
                )
                scheduler.cancel_task(task.id)

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

        # Bound by min(WorkerPool capacity, max_parallel_goals semaphore)
        cap_remaining = max(0, self._config.max_loops - self._worker_pool.active_count())
        if cap_remaining <= 0:
            return

        candidates = self._ce.peek_ready_goals(limit=cap_remaining)
        for candidate in candidates:
            if not await self._try_dispatch_goal(candidate):
                break

    async def _try_dispatch_goal(self, goal: GoalNode) -> bool:
        """Attempt WorkerPool dispatch for one ready goal."""
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

        worker = await self._worker_pool.pick_worker(goal)
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

    async def _dispatch_to_worker(self, goal: GoalNode, worker: Any) -> None:
        """Build the LoopRunRequest and spawn a stream-consuming task."""
        from soothe.protocols.runner import GoalDispatchEnvelope, LoopRunRequest

        # Phase C ships an empty merged_context. Phase C+ wires the
        # ContextProjector to fetch and project parents' contributions.
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

        Hooks the ``ContextProjector`` if one was wired (Phase C+ optional).
        Returns an empty bundle by default so dispatch always succeeds.
        """
        from soothe.foundation.autopilot.engine.models import GoalDispatchContextBundle

        projector = getattr(self, "_context_projector", None)
        if projector is None:
            return GoalDispatchContextBundle()
        try:
            return await projector.project(goal, self._ce._dag.goals)
        except Exception:
            logger.warning(
                "ContextProjector failed for goal %s; falling back to empty bundle",
                goal.id,
                exc_info=True,
            )
            return GoalDispatchContextBundle()

    async def _consume_worker_stream(self, goal_id: str, worker: Any, request: Any) -> None:
        """Drain a worker's stream and react to ``GoalCompletionChunk``.

        On a successful completion: mark goal completed in GoalEngine,
        store the contribution if a context store is wired, return the
        worker to the idle queue, release any workspace reservation.

        On exception or non-completion termination: mark goal failed.
        """
        from soothe.foundation.autopilot.engine.models import (
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

                # RFC-204 Group C: Apply directives BEFORE outcome handling.
                # This creates subgoals that inherit from the active goal.
                directives_data = data.get("goal_directives", [])
                if directives_data:
                    try:
                        from soothe.protocols.planner import GoalDirective

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
                    )
                else:  # failed / needs_replan → fail with evidence
                    evidence = EvidenceBundle(
                        structured={
                            "outcome": outcome,
                            "plan_result_status": data.get("plan_result_status"),
                        },
                        narrative=str(data.get("evidence_summary", ""))
                        or str(data.get("error_text", "no narrative")),
                        source="layer2_execute",
                    )
                    try:
                        await self._ce.fail_goal(
                            goal_id, evidence=evidence, allow_retry=outcome == "needs_replan"
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
            from soothe.foundation.autopilot.engine.models import EvidenceBundle as _EvBundle

            try:
                await self._ce.fail_goal(
                    goal_id,
                    evidence=_EvBundle(
                        structured={"outcome": "no_completion_chunk"},
                        narrative="Worker exited without emitting GoalCompletionChunk",
                        source="layer2_execute",
                    ),
                    allow_retry=False,
                )
            except Exception:
                logger.debug("fail_goal raised on missing completion", exc_info=True)

        # Always release worker + reservation, even on errors.
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
    ) -> None:
        """RFC-204: validate worker completion before accepting the goal."""
        from soothe.foundation.autopilot.engine.consensus import evaluate_goal_completion

        goal = await self._ce.get_goal(goal_id)
        if goal is None:
            return

        response_text = evidence_summary or goal.description
        try:
            decision, reasoning = await evaluate_goal_completion(
                goal.description,
                response_text,
                evidence_summary,
                model=self._consensus_model,
            )
        except Exception:
            logger.exception("Consensus evaluation failed for goal %s", goal_id)
            decision, reasoning = "suspend", "Consensus evaluation failed"

        try:
            if decision == "accept":
                await self._ce.complete_goal(goal_id)
            elif decision == "send_back":
                await self._ce.send_back_goal(goal_id, reason=reasoning)
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

    async def _schedule_next_goal(self) -> None:
        """Schedule next ready goal (single goal trigger)."""
        await self._schedule_ready_goals()

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

        from soothe.foundation.autopilot.engine.models import EvidenceBundle

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
                    allow_retry=False,
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
        """Force-enter dreaming mode (HTTP/CLI ``dream`` command)."""
        if not self._config.dreaming_enabled:
            logger.info("Dreaming disabled in config; ignoring force_dream")
            return
        await self._enter_dreaming_mode()

    async def approve_confirmation(self, confirmation_id: str) -> bool:
        """Approve a pending MUST-confirmation and create the goal."""
        import json

        from soothe.config import SOOTHE_HOME

        path = SOOTHE_HOME / "autopilot" / "pending_confirmations.json"
        if not path.exists():
            return False
        try:
            confirmations = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return False

        for item in confirmations:
            if item.get("id") != confirmation_id:
                continue
            description = str(item.get("description") or "").strip()
            if not description:
                return False
            priority = int(item.get("priority", 50))
            await self.submit_task(description, priority=priority)
            remaining = [c for c in confirmations if c.get("id") != confirmation_id]
            path.write_text(json.dumps(remaining, indent=2))
            return True
        return False

    async def reject_confirmation(self, confirmation_id: str) -> bool:
        """Reject a pending MUST-confirmation without creating a goal."""
        import json

        from soothe.config import SOOTHE_HOME

        path = SOOTHE_HOME / "autopilot" / "pending_confirmations.json"
        if not path.exists():
            return False
        try:
            confirmations = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return False

        remaining = [c for c in confirmations if c.get("id") != confirmation_id]
        if len(remaining) == len(confirmations):
            return False
        path.write_text(json.dumps(remaining, indent=2))
        return True

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
        except Exception:
            logger.warning("Failed to persist autopilot goals snapshot", exc_info=True)

    async def _restore_persisted_goals(self) -> None:
        """Restore ContextEngine DAG from persistence and recover stranded actives."""
        if self._goal_persist_store is None:
            return
        try:
            data = await self._goal_persist_store.load(self._GOALS_SNAPSHOT_KEY)
            if isinstance(data, dict) and "goals" in data:
                from soothe.foundation.context.models import GoalStepDAGSnapshot

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

    def _get_or_init_scheduler(self) -> Any:
        """Lazily construct SchedulerService bound to SOOTHE_HOME."""
        if self._scheduler is not None:
            return self._scheduler
        if not self._config.scheduler_enabled:
            return None

        from soothe.config import SOOTHE_HOME
        from soothe.foundation.autopilot.engine.scheduled_tasks import SchedulerService

        persist_path = SOOTHE_HOME / "autopilot" / "scheduled_tasks.json"
        self._scheduler = SchedulerService(persist_path=persist_path)
        return self._scheduler

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

    async def dag_snapshot(self, root_goal_id: str) -> dict[str, Any]:
        """Export DAG structure for visualization (RFC-228).

        Returns a structure suitable for React Flow rendering with
        nodes containing goal details and edges for dependencies.

        Args:
            root_goal_id: Root goal ID (job_id) to traverse from.

        Returns:
            Dict with 'nodes' and 'edges' arrays for DAG visualization.
            Nodes contain: id, description, status, priority, depends_on,
            assigned_loop_id, steps_completed, steps_total, tool_calls,
            summary (if completed), findings (if completed).
            Edges contain: source, target for dependency relationships.
        """
        goals = await self._ce.list_goals()

        # Build parent → children map from depends_on relationships
        children_map: dict[str, list[str]] = {}
        goal_by_id: dict[str, GoalNode] = {}

        for g in goals:
            goal_by_id[g.id] = g
            for dep_id in g.depends_on or []:
                if dep_id not in children_map:
                    children_map[dep_id] = []
                children_map[dep_id].append(g.id)

        # Traverse descendants of root goal
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

            # Add children to queue
            for child_id in children_map.get(current_id, []):
                if child_id not in visited:
                    queue.append(child_id)

        # Build nodes for React Flow
        nodes: list[dict[str, Any]] = []
        for g in descendants:
            node: dict[str, Any] = {
                "id": g.id,
                "description": (g.description[:100] if len(g.description) > 100 else g.description),
                "status": g.status,
                "priority": g.priority,
                "depends_on": list(g.depends_on or []),
                "assigned_loop_id": g.assigned_loop_id,
                "steps_completed": 0,
                "steps_total": 0,
                "tool_calls": 0,
            }
            # Add report fields if available
            if g.report is not None:
                node["steps_completed"] = getattr(g.report, "steps_completed", 0) or 0
                node["steps_total"] = getattr(g.report, "steps_total", 0) or 0
                node["tool_calls"] = getattr(g.report, "tool_calls", 0) or 0
                if g.status == "completed":
                    node["summary"] = getattr(g.report, "summary", None)
                    findings = getattr(g.report, "findings", None)
                    node["findings"] = findings if findings else []
            nodes.append(node)

        # Build edges from depends_on relationships
        edges: list[dict[str, str]] = []
        for g in descendants:
            for dep_id in g.depends_on or []:
                edges.append({"source": dep_id, "target": g.id})

        return {
            "nodes": nodes,
            "edges": edges,
            "root_id": root_goal_id,
        }
