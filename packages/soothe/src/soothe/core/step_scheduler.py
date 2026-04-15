"""StepScheduler -- DAG-based plan step scheduling (RFC-0009).

Resolves step dependencies and provides batches of ready steps for
parallel execution within concurrency limits. Each ``StepScheduler``
instance is scoped to a single ``Plan``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.protocols.planner import Plan, PlanStep
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class StepScheduler:
    """DAG-based step scheduler for a single plan.

    Resolves step dependencies declared via ``PlanStep.depends_on`` and
    provides ``ready_steps()`` to drive the runner's step loop.  Steps
    whose dependencies have all completed become eligible; steps with a
    failed dependency are transitively marked failed.

    Args:
        plan: The plan whose steps to schedule.

    Raises:
        ValueError: If a cycle is detected in step dependencies.
    """

    def __init__(self, plan: Plan) -> None:
        """Initialize with a plan whose steps to schedule."""
        self._plan = plan
        self._step_map: dict[str, PlanStep] = {s.id: s for s in plan.steps}
        self._validate_dag()

    def _validate_dag(self) -> None:
        """Validate no cycles exist in step dependencies."""
        visited: set[str] = set()
        in_stack: set[str] = set()

        def _dfs(sid: str) -> None:
            if sid in in_stack:
                msg = f"Cycle detected in step dependencies involving {sid}"
                raise ValueError(msg)
            if sid in visited:
                return
            in_stack.add(sid)
            step = self._step_map.get(sid)
            if step:
                for dep_id in step.depends_on:
                    if dep_id in self._step_map:
                        _dfs(dep_id)
            in_stack.discard(sid)
            visited.add(sid)

        for step in self._plan.steps:
            _dfs(step.id)

    def ready_steps(self, limit: int = 0, parallelism: str = "dependency") -> list[PlanStep]:
        """Return steps whose dependencies are all completed.

        Args:
            limit: Max steps to return (0 = no limit).
            parallelism: Scheduling mode:
                ``sequential`` -- at most 1 step.
                ``dependency`` -- all DAG-ready steps up to ``limit``.
                ``max`` -- same as ``dependency``.

        Returns:
            List of ready-to-execute steps.
        """
        if parallelism == "sequential":
            limit = 1

        self._propagate_failures()

        ready: list[PlanStep] = []
        for step in self._plan.steps:
            if step.status != "pending":
                continue
            deps_met = all(
                self._step_map[dep_id].status == "completed"
                for dep_id in step.depends_on
                if dep_id in self._step_map
            )
            if deps_met:
                ready.append(step)

        if limit > 0:
            ready = ready[:limit]
        return ready

    def _propagate_failures(self) -> None:
        """Mark pending steps as failed if any dependency has failed."""
        changed = True
        while changed:
            changed = False
            for step in self._plan.steps:
                if step.status != "pending":
                    continue
                for dep_id in step.depends_on:
                    dep = self._step_map.get(dep_id)
                    if dep and dep.status == "failed":
                        step.status = "failed"
                        step.result = f"Blocked by failed dependency: {dep_id}"
                        logger.info("Step %s blocked by failed dependency %s", step.id, dep_id)
                        changed = True
                        break

    def mark_completed(self, step_id: str, result: str) -> None:
        """Mark a step as completed with its result.

        Args:
            step_id: Step to mark.
            result: Step output text.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "completed"
            step.result = result
            logger.info("Step %s completed (%d chars)", step_id, len(result))

    def mark_failed(self, step_id: str, error: str) -> None:
        """Mark a step as failed.

        Args:
            step_id: Step to mark.
            error: Error description.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "failed"
            step.result = error
            logger.warning("Step %s failed: %s", step_id, preview_first(error, 100))

    def mark_in_progress(self, step_id: str) -> None:
        """Mark a step as in-progress.

        Args:
            step_id: Step to mark.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "in_progress"
            logger.info("Step %s started: %s", step_id, preview_first(step.description, 60))

    def is_complete(self) -> bool:
        """Check if all steps are terminal (completed or failed)."""
        return all(s.status in ("completed", "failed") for s in self._plan.steps)

    def get_dependency_results(self, step: PlanStep) -> list[tuple[str, str]]:
        """Get results from a step's completed dependencies.

        Args:
            step: Step whose dependency results to collect.

        Returns:
            List of ``(step_description, result)`` tuples.
        """
        results: list[tuple[str, str]] = []
        for dep_id in step.depends_on:
            dep = self._step_map.get(dep_id)
            if dep and dep.status == "completed" and dep.result:
                results.append((dep.description, dep.result))
        return results

    def summary(self) -> dict[str, Any]:
        """Return a summary of step statuses.

        Returns:
            Dict with ``total``, per-status counts, and ``is_complete``.
        """
        counts: dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
        for step in self._plan.steps:
            counts[step.status] = counts.get(step.status, 0) + 1
        return {
            "total": len(self._plan.steps),
            **counts,
            "is_complete": self.is_complete(),
        }
