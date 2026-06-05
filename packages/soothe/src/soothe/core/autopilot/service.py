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
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.core.autopilot.loop_pool import LoopHandle, LoopPool
from soothe.core.events.internal_bus import InternalEventBus
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
from soothe.core.goal_engine.models import TERMINAL_STATES

if TYPE_CHECKING:
    from soothe.config.models import AutonomousConfig
    from soothe.core.goal_engine.engine import GoalEngine
    from soothe.core.goal_engine.models import Goal

logger = logging.getLogger(__name__)


class AutopilotService:
    """Layer 3 Autopilot orchestration service.

    Manages AgentLoop worker pool and goal scheduling with
    lineage-aware loop reuse. Subscribes to GoalEngine events
    for reactive scheduling.

    Responsibilities:
    - Spawn and manage AgentLoop workers (loop pool)
    - Schedule ready goals to available loops
    - Lineage-aware loop assignment (reuse parent's loop)
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
        *,
        subscribe_to_bus: bool = True,
        runner_factory: Any | None = None,
        workspace_reservation: Any | None = None,
        consensus_model: Any | None = None,
        goal_persist_store: Any | None = None,
    ) -> None:
        """Initialize AutopilotService.

        Args:
            goal_engine: GoalEngine instance for goal management.
            config: Project-level AutonomousConfig carrying RFC-222 loop pool
                fields (``max_loops``, ``loop_idle_timeout``, ``poll_interval``,
                ``dreaming_poll_interval``).
            internal_bus: Internal EventBus (uses singleton if None).
            subscribe_to_bus: When True (default), subscribe handlers to the
                bus immediately. RFC-222 (revised, Phase B): the daemon
                constructs a daemon-owned ``AutopilotService`` alongside the
                per-runner one — they share the singleton bus, so the daemon
                instance must pass ``subscribe_to_bus=False`` to avoid
                double-handling every event. Phase D will retire the
                per-runner instance and the daemon's will start subscribing.
            runner_factory: Optional ``LoopRunnerFactory``-shaped object
                exposing ``create_runner(loop_id) -> LoopRunnerProtocol``.
                When provided (Phase C+), the scheduling loop dispatches
                goals to real subprocess workers via a ``WorkerPool``. When
                ``None`` (legacy / per-runner usage), the service uses the
                in-memory ``LoopPool`` which never spawns workers.
            workspace_reservation: Optional ``WorkspaceReservation`` gate.
                When provided, the scheduling loop refuses to dispatch a
                goal whose workspace overlaps an active reservation. When
                ``None``, no workspace gating is applied.
            consensus_model: Optional LLM for RFC-204 consensus validation.
                When ``None``, completed goals suspend until a model is configured.
            goal_persist_store: Optional ``AsyncPersistStore`` for persisting
                the GoalEngine DAG snapshot across daemon restarts.
        """
        self._goal_engine = goal_engine
        self._config = config
        self._internal_bus = internal_bus if internal_bus is not None else InternalEventBus()
        self._loop_pool = LoopPool(max_loops=self._config.max_loops)
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

        # RFC-222 revised (Phase C): optional WorkerPool-driven dispatch.
        # When ``runner_factory`` is supplied, ``WorkerPool`` wraps it and
        # the scheduling loop uses real subprocess dispatch. When None, the
        # legacy in-memory LoopPool path runs (used by the per-runner
        # AutopilotService instance for backward compat).
        self._runner_factory = runner_factory
        self._worker_pool: Any = None  # WorkerPool | None
        self._workspace_reservation = workspace_reservation
        self._consensus_model = consensus_model
        self._goal_persist_store = goal_persist_store
        self._scheduler: Any = None  # SchedulerService | None
        self._context_store: Any = None
        self._context_projector: Any = None
        self._dispatch_tasks: dict[str, asyncio.Task] = {}  # goal_id → consumer task
        if runner_factory is not None:
            from soothe.core.autopilot.worker_pool import WorkerPool

            self._worker_pool = WorkerPool(factory=runner_factory, max_loops=self._config.max_loops)

        if subscribe_to_bus:
            self._setup_subscriptions()
            self._subscribed = True

    @property
    def has_real_dispatch(self) -> bool:
        """True when a ``runner_factory`` was provided (RFC-222 Phase C+).

        When True, the scheduling loop uses ``WorkerPool`` + real subprocess
        dispatch. When False, it uses the legacy in-memory ``LoopPool``.
        """
        return self._worker_pool is not None

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

        # Release file locks if goal reached a terminal state
        if event.new_status in TERMINAL_STATES:
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

        await self._restore_persisted_goals()

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

        await self._persist_goals()

        # Cancel scheduling task
        if self._scheduling_task:
            self._scheduling_task.cancel()
            try:
                await self._scheduling_task
            except asyncio.CancelledError:
                pass
            self._scheduling_task = None

        # Cancel any in-flight dispatch consumer tasks (RFC-222 Phase C).
        for goal_id, task in list(self._dispatch_tasks.items()):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self._dispatch_tasks.pop(goal_id, None)

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

    # ---- Public submission API (RFC-222 revised, Phase C) -------------

    async def submit_task(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
        depends_on: list[str] | None = None,
        informs: list[str] | None = None,
        source_file: str | None = None,
        workspace: str | None = None,
    ) -> Goal:
        """Create a goal in this service's GoalEngine (RFC-222 revised).

        Public entry point for callers (HTTP ``/autopilot/submit`` and other
        programmatic clients) to add a
        new goal to the DAG. The scheduling loop will pick it up on its
        next tick when ``self._running`` is True.

        Args:
            description: Goal description text.
            priority: 0-100, higher schedules earlier.
            parent_id: Optional parent goal id for hierarchical decomposition.
            max_retries: Override default max retries.
            depends_on: Hard dependencies — goal won't run until these complete.
            informs: Soft dependencies — context flows from these but the
                child can still run if they haven't completed yet.
            source_file: Optional file path for goal-file-discovery use cases
                (RFC-204).
            workspace: Optional client workspace path. When set, workers execute
                in this directory and scheduling-time reservation uses it.

        Returns:
            The newly-created ``Goal``. Callers can read ``.id`` to track it.

        Raises:
            ValueError: If goal depth limit would be exceeded or workspace invalid.
        """
        resolved_workspace: str | None = None
        if workspace is not None and str(workspace).strip():
            from soothe.core.workspace import validate_client_workspace

            resolved_workspace = str(validate_client_workspace(workspace))

        goal = await self._goal_engine.create_goal(
            description,
            priority=priority,
            parent_id=parent_id,
            max_retries=max_retries,
            depends_on=depends_on,
            informs=informs,
            source_file=source_file,
            workspace=resolved_workspace,
        )
        if self._dreaming:
            await self.wake_from_dreaming(trigger="new_task")
        await self._persist_goals()
        return goal

    async def list_goals(self, *, status: str | None = None) -> list[Goal]:
        """Read-through to the underlying GoalEngine for HTTP/CLI surfaces."""
        # GoalStatus literal accepted; pass through as-is.
        return await self._goal_engine.list_goals(status=status)  # type: ignore[arg-type]

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Read-through to the underlying GoalEngine for HTTP/CLI surfaces."""
        return await self._goal_engine.get_goal(goal_id)

    async def cancel_goal(self, goal_id: str, *, reason: str = "user_cancelled") -> Goal | None:
        """Cancel a goal: stop the worker (if any) and transition to ``cancelled``.

        RFC-222 H8: when the goal is currently dispatched, resolve the assigned
        worker via ``WorkerPool`` and call ``worker.runner.cancel()`` to abort
        the subprocess via RFC-221's cooperative cancellation.

        Args:
            goal_id: Goal to cancel.
            reason: Logged with the cancellation for audit.

        Returns:
            The Goal if it existed, else None.
        """
        goal = await self._goal_engine.get_goal(goal_id)
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

        await self._goal_engine.cancel_goal(goal_id, reason=reason)
        if self._workspace_reservation is not None:
            self._workspace_reservation.release(goal_id)
        await self._persist_goals()
        return await self._goal_engine.get_goal(goal_id)

    # ---- Internals ----------------------------------------------------

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
                if self._goal_engine.is_complete():
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
        """Schedule all ready goals from GoalEngine.

        Two paths:
        - ``has_real_dispatch`` True (RFC-222 Phase C+): use ``WorkerPool``
          to pick subprocess workers and dispatch via ``LoopRunRequest``.
        - Else: legacy in-memory ``LoopPool`` path (per-runner instance).
        """
        if self.has_real_dispatch:
            await self._schedule_via_worker_pool()
            return

        # Legacy path (per-runner instance, no real dispatch)
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

    async def _schedule_via_worker_pool(self) -> None:
        """RFC-222 Phase C: schedule via WorkerPool + real subprocess dispatch.

        For each ready goal under capacity, optionally check workspace
        reservation, claim the goal, and spawn a stream-consuming task
        that drives ``worker.runner.run(LoopRunRequest)`` and reacts to
        the worker's terminal ``GoalCompletionChunk``.
        """
        if self._worker_pool is None:
            return  # safety: should never happen when has_real_dispatch is True

        # Bound by min(WorkerPool capacity, max_parallel_goals semaphore)
        cap_remaining = max(0, self._config.max_loops - self._worker_pool.active_count())
        if cap_remaining <= 0:
            return

        candidates = await self._goal_engine.peek_ready_goals(limit=cap_remaining)
        for candidate in candidates:
            # Workspace reservation gate (RFC-222 revised Q1).
            if self._workspace_reservation is not None:
                ws = self._infer_workspace(candidate)
                conflict = self._workspace_reservation.conflicts_with_active(
                    ws, exclude_goal_id=candidate.id
                )
                if conflict:
                    logger.debug(
                        "Goal %s deferred: workspace %s conflicts with active goal %s",
                        candidate.id,
                        ws,
                        conflict,
                    )
                    continue
                if not self._workspace_reservation.acquire(candidate.id, ws):
                    continue

            worker = await self._worker_pool.pick_worker(candidate)
            if worker is None:
                # Pool filled mid-iteration; release the reservation we just took.
                if self._workspace_reservation is not None:
                    self._workspace_reservation.release(candidate.id)
                logger.debug("No worker capacity for goal %s; deferring", candidate.id)
                break

            # Atomically claim — re-checks conflicts at flip time.
            claimed = await self._goal_engine.claim_goal(candidate.id, loop_id=worker.loop_id)
            if claimed is None:
                # Race: another path consumed the goal first.
                logger.debug("Goal %s vanished before claim; releasing worker", candidate.id)
                await self._worker_pool.mark_idle(worker.loop_id, success=True)
                if self._workspace_reservation is not None:
                    self._workspace_reservation.release(candidate.id)
                continue

            await self._dispatch_to_worker(claimed, worker)

    async def _dispatch_to_worker(self, goal: Goal, worker: Any) -> None:
        """Build the LoopRunRequest and spawn a stream-consuming task."""
        from soothe.protocols.runner import AutopilotJob, LoopRunRequest

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
            autopilot_job=AutopilotJob(
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

    async def _build_merged_context(self, goal: Goal) -> Any:
        """Build the GoalDispatchContextBundle for ``goal``.

        Hooks the ``ContextProjector`` if one was wired (Phase C+ optional).
        Returns an empty bundle by default so dispatch always succeeds.
        """
        from soothe.core.goal_engine.models import GoalDispatchContextBundle

        projector = getattr(self, "_context_projector", None)
        if projector is None:
            return GoalDispatchContextBundle()
        try:
            return await projector.project(goal, self._goal_engine._goals)
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
        from soothe.core.goal_engine.models import (
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
                        await self._goal_engine.fail_goal(
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
            from soothe.core.goal_engine.models import EvidenceBundle as _EvBundle

            try:
                await self._goal_engine.fail_goal(
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
        from soothe.core.goal_engine.consensus import evaluate_goal_completion

        goal = await self._goal_engine.get_goal(goal_id)
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
                await self._goal_engine.complete_goal(goal_id)
            elif decision == "send_back":
                await self._goal_engine.send_back_goal(goal_id, reason=reasoning)
            else:
                await self._goal_engine.suspend_goal(goal_id, reason=reasoning)
        except Exception:
            logger.exception("Goal transition failed after consensus for %s", goal_id)

    @staticmethod
    def _infer_workspace(goal: Goal) -> str:
        """Workspace path for scheduling-time reservation (RFC-222).

        Uses the goal's client workspace when set; otherwise a per-goal sentinel
        so goals without an explicit workspace still get distinct reservation slots.
        """
        if goal.workspace:
            return goal.workspace
        return f"$autopilot/goal/{goal.id}"

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
        """Monitor active workers — enforce wall-clock deadlines (RFC-222 H5).

        For each active worker, if ``goal_deadline_seconds`` is configured and
        the worker has been busy longer than that, request cooperative
        cancellation via ``worker.runner.cancel()`` and fail the goal with a
        deadline_exceeded evidence bundle. The stream consumer task will see
        the cancel and unwind cleanly (releasing reservation + worker).
        """
        if self._worker_pool is None:
            return  # legacy in-memory LoopPool path has no real workers

        deadline = getattr(self._config, "goal_deadline_seconds", None)
        if not deadline or deadline <= 0:
            return

        from soothe.core.goal_engine.models import EvidenceBundle

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
                await self._goal_engine.fail_goal(
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
        """Persist GoalEngine DAG snapshot when a store is wired."""
        if self._goal_persist_store is None:
            return
        try:
            await self._goal_persist_store.save(
                self._GOALS_SNAPSHOT_KEY,
                self._goal_engine.snapshot(),
            )
        except Exception:
            logger.warning("Failed to persist autopilot goals snapshot", exc_info=True)

    async def _restore_persisted_goals(self) -> None:
        """Restore GoalEngine DAG from persistence and recover stranded actives."""
        if self._goal_persist_store is None:
            return
        try:
            data = await self._goal_persist_store.load(self._GOALS_SNAPSHOT_KEY)
            if isinstance(data, list) and data:
                self._goal_engine.restore_from_snapshot(data)
        except Exception:
            logger.warning("Failed to restore autopilot goals snapshot", exc_info=True)
        recovered = self._goal_engine.recover_active_goals()
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
        from soothe.core.goal_engine.scheduled_tasks import SchedulerService

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
        goals = await self._goal_engine.list_goals()

        # Build parent → children map from depends_on relationships
        children_map: dict[str, list[str]] = {}
        goal_by_id: dict[str, Goal] = {}

        for g in goals:
            goal_by_id[g.id] = g
            for dep_id in g.depends_on or []:
                if dep_id not in children_map:
                    children_map[dep_id] = []
                children_map[dep_id].append(g.id)

        # Traverse descendants of root goal
        descendants: list[Goal] = []
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
