"""CronService — orchestrator for cron jobs (RFC-229).

Coordinates NL extraction, persistence, and execution through AutopilotService.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.foundation.autopilot.engine.schedule_timezone import schedule_timezone_label
from soothe.foundation.autopilot.engine.scheduled_tasks import ScheduleSpec
from soothe.foundation.cron.extraction import AutopilotDisabledError, CronExtractionService
from soothe.foundation.cron.messages import AUTOPILOT_REQUIRED_FOR_CRON
from soothe.foundation.cron.models import CronJob, DuplicateCronJobError, JobStatus
from soothe.foundation.cron.store_factory import create_cron_job_store

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.foundation.autopilot.service.service import AutopilotService

logger = logging.getLogger(__name__)


class CronService:
    """Orchestrating service for cron jobs (RFC-229).

    Coordinates:
    - NL extraction via CronExtractionService
    - Schedule math via ScheduleSpec
    - Persistence via CronJobStore / PostgresCronJobStore
    - Execution via AutopilotService.submit_task()

    Runs periodic monitoring tick to dispatch due jobs.

    Args:
        config: SootheConfig for settings and LLM factory.
        autopilot: AutopilotService for goal dispatch.
        store: Optional store (created from ``persistence.default_backend`` if None).
    """

    def __init__(
        self,
        config: SootheConfig,
        autopilot: AutopilotService | None = None,
        store: Any | None = None,
    ) -> None:
        """Initialize CronService.

        Args:
            config: SootheConfig for settings and LLM factory.
            autopilot: AutopilotService for goal dispatch.
            store: Optional cron store (created from config when None).
        """
        self._config = config
        self._autopilot = autopilot
        self._cron_config = config.cron

        # Create components
        self._store = store or create_cron_job_store(config)
        self._extraction_service = CronExtractionService(
            config,
            model_role=self._cron_config.extraction_model,
            timeout=self._cron_config.extraction_timeout,
        )

        # Running state
        self._running = False
        self._tick_task: asyncio.Task | None = None

        logger.info(
            "CronService initialized: max_jobs=%d poll_interval=%d timezone=%s",
            self._cron_config.max_jobs,
            self._cron_config.poll_interval,
            schedule_timezone_label(self._cron_config.timezone),
        )

    def _schedule_spec(self, kind: str, value: str) -> ScheduleSpec:
        """Build a schedule spec using the configured cron timezone."""
        return ScheduleSpec(
            kind=kind,
            value=value,
            timezone=self._cron_config.timezone,
        )

    async def _reconcile_pending_schedules(self) -> None:
        """Recompute next_run for pending jobs after timezone config changes."""
        now = datetime.now(tz=UTC)
        pending = await self._store.list_pending()
        for job in pending:
            spec = self._schedule_spec(job.schedule_kind.value, job.schedule_value)
            next_run = spec.next_after(now)
            if next_run is None:
                continue
            if next_run != job.next_run:
                await self._store.update_next_run(job.id, next_run, job.run_count)
                logger.info(
                    "Cron job next_run reconciled: id=%s next_run=%s timezone=%s",
                    job.id,
                    next_run.isoformat(),
                    schedule_timezone_label(self._cron_config.timezone),
                )

    async def start(self) -> None:
        """Start the cron service monitoring loop."""
        if self._running:
            logger.warning("CronService already running")
            return

        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())

        # RFC-229: Subscribe to goal completion events for recurring job rescheduling
        if self._autopilot is not None:
            self._autopilot._internal_bus.subscribe(
                "soothe.internal.goal.completed",
                self._handle_internal_goal_completed,
            )
            logger.debug("CronService subscribed to goal completion events")

        await self._reconcile_pending_schedules()

        logger.info(
            "CronService started with poll_interval=%ds timezone=%s",
            self._cron_config.poll_interval,
            schedule_timezone_label(self._cron_config.timezone),
        )

    async def stop(self) -> None:
        """Stop the cron service monitoring loop."""
        if not self._running:
            return

        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
            self._tick_task = None

        await self._store.close()
        logger.info("CronService stopped")

    async def add_job(
        self,
        natural_language: str,
        user_id: str,
        priority: int | None = None,
    ) -> CronJob:
        """Submit job via natural language.

        Args:
            natural_language: User's natural language request.
            user_id: Owner user identifier.
            priority: Optional priority override.

        Returns:
            Created CronJob with id and next_run set.

        Raises:
            AutopilotDisabledError: If autopilot scheduling is disabled in config.
            ExtractionError: If NL extraction fails.
            DuplicateCronJobError: If an equivalent active job already exists.
            ValueError: If max_jobs limit exceeded.
        """
        if not self._config.agent.autopilot.enabled:
            logger.warning(
                "Cron job submission rejected: agent.autopilot.enabled=false (user=%s)",
                user_id,
            )
            raise AutopilotDisabledError(AUTOPILOT_REQUIRED_FOR_CRON)

        # Check job limit
        current_count = await self._store.count_by_user(user_id)
        if current_count >= self._cron_config.max_jobs:
            raise ValueError(
                f"Maximum scheduled jobs ({self._cron_config.max_jobs}) reached for user {user_id}"
            )

        # Extract schedule from natural language
        extraction = await self._extraction_service.extract(natural_language)

        existing = await self._store.find_active_duplicate(
            user_id,
            description=extraction.description,
            schedule_kind=extraction.schedule_kind,
            schedule_value=extraction.schedule_value,
        )
        if existing is not None:
            logger.info(
                "Cron job duplicate rejected: existing=%s user=%s description=%s",
                existing.id,
                user_id,
                extraction.description[:50],
            )
            raise DuplicateCronJobError(existing)

        # Generate job ID
        job_id = uuid.uuid4().hex[:12]

        # Compute next_run via ScheduleSpec
        spec = self._schedule_spec(extraction.schedule_kind.value, extraction.schedule_value)
        next_run = spec.next_after(datetime.now(tz=UTC))
        if next_run is None:
            raise ValueError(
                f"Schedule {extraction.schedule_kind}={extraction.schedule_value} has no valid next run"
            )

        # Create CronJob
        job = CronJob(
            id=job_id,
            user_id=user_id,
            description=extraction.description,
            schedule_kind=extraction.schedule_kind,
            schedule_value=extraction.schedule_value,
            end_condition=extraction.end_condition,
            priority=priority or self._cron_config.default_priority,
            status=JobStatus.PENDING,
            next_run=next_run,
        )

        # Persist to store
        await self._store.create(job)

        logger.info(
            "Cron job created: id=%s user=%s next_run=%s description=%s",
            job_id,
            user_id,
            next_run.isoformat(),
            extraction.description[:50],
        )

        return job

    async def list_jobs(
        self,
        user_id: str,
        status: JobStatus | str | None = None,
    ) -> list[CronJob]:
        """List jobs for user, optionally filtered by status.

        Args:
            user_id: User identifier.
            status: Optional status filter.

        Returns:
            List of CronJob objects owned by this user.
        """
        return await self._store.list_by_user(user_id, status)

    async def cancel_job(self, job_id: str, user_id: str) -> bool:
        """Cancel a pending job.

        Args:
            job_id: Job identifier.
            user_id: User identifier (for ownership validation).

        Returns:
            True if cancelled, False if not found or not owned.
        """
        job = await self._store.get(job_id)
        if job is None or job.user_id != user_id:
            return False

        if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False

        await self._store.update_status(job_id, JobStatus.CANCELLED)
        logger.info("Cron job cancelled: id=%s user=%s", job_id, user_id)
        return True

    async def show_job(self, job_id: str, user_id: str) -> CronJob | None:
        """Get job details.

        Args:
            job_id: Job identifier.
            user_id: User identifier (for ownership validation).

        Returns:
            CronJob if found and owned by user, None otherwise.
        """
        job = await self._store.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def _tick_loop(self) -> None:
        """Periodic monitoring loop for due jobs."""
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Cron tick error")

            await asyncio.sleep(self._cron_config.poll_interval)

    async def _tick(self) -> None:
        """Single tick: check due jobs and dispatch."""
        now = datetime.now(tz=UTC)
        due_jobs = await self._store.get_due_jobs(now)

        if not due_jobs:
            return

        logger.debug("Cron tick: %d due jobs", len(due_jobs))

        for job in due_jobs:
            # Check end condition
            if self._is_job_expired(job, now):
                await self._store.update_status(job.id, JobStatus.COMPLETED, last_run=now)
                logger.info("Cron job expired: id=%s end_condition=%s", job.id, job.end_condition)
                continue

            # Mark as running
            await self._store.update_status(job.id, JobStatus.RUNNING)

            # Dispatch to AutopilotService
            if self._autopilot:
                try:
                    goal = await self._autopilot.submit_task(
                        job.description,
                        priority=job.priority,
                        cron_job_id=job.id,  # RFC-229: Link goal to cron job for rescheduling
                    )
                    logger.info(
                        "Cron job dispatched: id=%s goal_id=%s",
                        job.id,
                        goal.id,
                    )

                    # For one-shot jobs, mark completed after dispatch
                    # (goal execution is async, we just track dispatch success)
                    if job.is_one_shot():
                        await self._store.update_status(
                            job.id,
                            JobStatus.COMPLETED,
                            last_run=now,
                        )
                        logger.info("One-shot cron job completed: id=%s", job.id)

                except Exception:
                    logger.exception("Cron job dispatch failed: id=%s", job.id)
                    await self._store.update_status(job.id, JobStatus.FAILED)
            else:
                logger.warning("No AutopilotService, cannot dispatch cron job: id=%s", job.id)

    def _is_job_expired(self, job: CronJob, now: datetime) -> bool:
        """Check if recurring job has reached end condition.

        Args:
            job: CronJob to check.
            now: Current time.

        Returns:
            True if job should be marked completed due to end condition.
        """
        if not job.end_condition:
            return False

        # Parse end condition
        # Format: "until YYYY-MM-DD" or "for N days/weeks"
        cond = job.end_condition.lower()

        if cond.startswith("until "):
            try:
                end_date = datetime.fromisoformat(cond[6:].strip())
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=UTC)
                return now >= end_date
            except ValueError:
                logger.warning("Invalid end_condition: %s", job.end_condition)
                return False

        if cond.startswith("for "):
            # Parse duration: "for 2 weeks", "for 10 days"
            import re

            match = re.match(r"for (\d+) (day|days|week|weeks)", cond)
            if match:
                count = int(match.group(1))
                unit = match.group(2)
                if unit in ("week", "weeks"):
                    delta_days = count * 7
                else:
                    delta_days = count

                expiry = job.created_at + __import__("datetime").timedelta(days=delta_days)
                return now >= expiry

        return False

    async def handle_goal_completion(
        self,
        job_id: str,
        success: bool,
    ) -> None:
        """Handle goal completion callback for recurring jobs.

        Called when a goal dispatched from a cron job completes.

        Args:
            job_id: Cron job identifier.
            success: Whether goal execution succeeded.
        """
        job = await self._store.get(job_id)
        if job is None:
            logger.warning("Goal completion for unknown cron job: %s", job_id)
            return

        if job.is_recurring() and job.status == JobStatus.RUNNING:
            # Compute next run
            spec = self._schedule_spec(job.schedule_kind.value, job.schedule_value)
            next_run = spec.next_after(datetime.now(tz=UTC))

            if next_run and not self._is_job_expired(job, next_run):
                # Reschedule
                await self._store.update_next_run(
                    job_id,
                    next_run,
                    job.run_count + 1,
                )
                logger.info(
                    "Cron job rescheduled: id=%s next_run=%s run_count=%d",
                    job_id,
                    next_run.isoformat(),
                    job.run_count + 1,
                )
            else:
                # Mark completed
                await self._store.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    last_run=datetime.now(tz=UTC),
                )
                logger.info("Recurring cron job completed: id=%s", job_id)
        elif success:
            await self._store.update_status(
                job_id,
                JobStatus.COMPLETED,
                last_run=datetime.now(tz=UTC),
            )
        else:
            await self._store.update_status(job_id, JobStatus.FAILED)

    async def _handle_internal_goal_completed(self, event: Any) -> None:
        """Handle InternalGoalCompletedEvent for recurring job rescheduling (RFC-229).

        Bridge from internal event to handle_goal_completion when goal has cron_job_id.

        Args:
            event: InternalGoalCompletedEvent from AutopilotService.
        """
        # Extract goal_id from event
        goal_id = getattr(event, "goal_id", None)
        if goal_id is None:
            return

        # Look up goal to check if it has cron_job_id
        if self._autopilot is None:
            return
        goal = await self._autopilot.get_goal(goal_id)
        if goal is None:
            return

        cron_job_id = getattr(goal, "cron_job_id", None)
        if cron_job_id is None:
            return

        # Check if plan_result indicates success
        plan_result = getattr(event, "plan_result", {})
        success = plan_result.get("outcome", "success") == "success"

        logger.debug(
            "Goal %s completed (success=%s), triggering cron job %s rescheduling",
            goal_id,
            success,
            cron_job_id,
        )
        await self.handle_goal_completion(cron_job_id, success=success)


import contextlib  # noqa: E402  # Used in stop() above
