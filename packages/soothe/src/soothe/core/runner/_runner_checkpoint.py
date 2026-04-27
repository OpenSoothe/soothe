"""Checkpoint, artifact store, and report synthesis mixin for SootheRunner (RFC-0010).

Extracted from ``runner.py`` to isolate progressive persistence and
goal report generation from the main runner orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.protocols.planner import Plan

from ._runner_shared import StreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.core.artifact_store import RunArtifactStore

logger = logging.getLogger(__name__)


class CheckpointMixin:
    """Progressive checkpoint, artifact store, and report synthesis (RFC-0010).

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    def _ensure_artifact_store(self, state: Any) -> RunArtifactStore | None:
        """Lazily create the artifact store on *state* when thread_id is known."""
        from soothe.core.artifact_store import RunArtifactStore
        from soothe.utils.runtime import current_run_dir

        thread_id = getattr(state, "thread_id", None) or ""
        if not thread_id:
            return None

        existing = getattr(state, "artifact_store", None)
        if existing is None or getattr(existing, "_thread_id", None) != thread_id:
            store = RunArtifactStore(thread_id, config=self._config)
            state.artifact_store = store
            current_run_dir.set(store.run_dir)
            self._artifact_store = store  # last-known for CLI / debugging (IG-110)
            logger.info("Artifact store initialized for thread %s", thread_id)
            return store
        self._artifact_store = existing
        return existing

    async def _save_checkpoint(
        self,
        state: Any,
        *,
        user_input: str,
        mode: str = "single_pass",
        status: str = "in_progress",
    ) -> AsyncGenerator[StreamChunk]:
        """Save progressive checkpoint for crash recovery (RFC-0010).

        IG-271: checkpoint events removed from normal execution, replaced with logging.
        Events only emitted conditionally during recovery mode.

        Yields:
            No events in normal execution (logging replacement).
        """
        from datetime import UTC, datetime

        store = getattr(state, "artifact_store", None)
        if not store:
            return

        plan_data = state.plan.model_dump(mode="json") if state.plan else None
        completed = [
            s.id for s in (state.plan.steps if state.plan else []) if s.status == "completed"
        ]
        goals_data = self._goal_engine.snapshot() if self._goal_engine else []

        envelope = {
            "version": 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": mode,
            "last_query": user_input,
            "thread_id": state.thread_id,
            "goals": goals_data,
            "active_goal_id": None,
            "plan": plan_data,
            "completed_step_ids": completed,
            "total_iterations": 0,
            "status": status,
        }
        try:
            store.save_checkpoint(envelope)
            # IG-271: Replace checkpoint event with compact logging
            logger.debug(
                "Checkpoint saved: mode=%s status=%s completed=%d", mode, status, len(completed)
            )

            # Update thread's updated_at timestamp to track activity
            if hasattr(self, "_durability") and state.thread_id:
                try:
                    # Load current thread info
                    thread_data = self._durability._store.load(f"thread:{state.thread_id}")
                    if thread_data:
                        from soothe.protocols.durability import ThreadInfo

                        thread_info = ThreadInfo.model_validate(thread_data)
                        # Update timestamp
                        thread_info = thread_info.model_copy(
                            update={"updated_at": datetime.now(UTC)}
                        )
                        self._durability._store.save(
                            f"thread:{state.thread_id}", thread_info.model_dump(mode="json")
                        )
                        logger.debug("Thread %s updated_at refreshed", state.thread_id)
                except Exception:
                    logger.debug("Failed to update thread timestamp", exc_info=True)
        except Exception:
            logger.debug("Checkpoint save failed", exc_info=True)

        # IG-271: No events emitted in normal execution (logging replacement)
        # Maintain async generator signature with dummy yield
        if False:
            yield

    async def _try_recover_checkpoint(
        self,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Attempt to restore from a progressive checkpoint (RFC-0010).

        Loads checkpoint from ``RunArtifactStore``, restores goal engine
        and plan state, marks previously completed steps so
        ``StepScheduler`` will skip them.

        Args:
            state: Current runner state to populate with recovered data.

        Yields:
            Recovery stream events.
        """
        self._ensure_artifact_store(state)
        store = getattr(state, "artifact_store", None)
        if not store:
            return

        try:
            loaded = store.load_checkpoint()
        except Exception:
            logger.debug("Checkpoint load failed", exc_info=True)
            return

        if not loaded or not isinstance(loaded, dict):
            logger.debug("No checkpoint to recover for thread %s", state.thread_id)
            return
        cp_status = loaded.get("status")
        if cp_status != "in_progress":
            logger.debug("Checkpoint status is %s, skipping recovery", cp_status)
            return
        if loaded.get("version", 0) < 1:
            logger.debug("Checkpoint version too old, skipping recovery")
            return

        goals_data = loaded.get("goals", [])
        if goals_data and self._goal_engine:
            self._goal_engine.restore_from_snapshot(goals_data)
            logger.info("Recovered %d goals from checkpoint", len(goals_data))

        plan_data = loaded.get("plan")
        completed_ids = set(loaded.get("completed_step_ids", []))
        if plan_data:
            plan = Plan.model_validate(plan_data)
            for step in plan.steps:
                if step.id in completed_ids:
                    step.status = "completed"
            state.plan = plan
            self._current_plan = plan
            logger.info(
                "Recovered plan: %d/%d steps completed",
                len(completed_ids),
                len(plan.steps),
            )

        completed_goals = [g["id"] for g in goals_data if g.get("status") == "completed"]
        logger.info(
            "Recovery resumed: %s | Steps: %d | Goals: %d | Mode: %s",
            state.thread_id,
            len(completed_ids),
            len(completed_goals),
            loaded.get("mode", "single_pass"),
        )

    # -- report synthesis ---------------------------------------------------

    async def _synthesize_root_goal_report(
        self,
        goal: Any,
        step_reports: list[Any],
        child_goal_reports: list[Any],
        max_chars: int = 0,
    ) -> str:
        """Generate a cross-validated summary for a goal (RFC-0010).

        Uses an LLM call to synthesize findings from all steps and child
        goals, cross-checking for contradictions and gaps.  Falls back to
        a structured heuristic summary when the LLM is unavailable.

        Args:
            goal: The goal being summarized.
            step_reports: StepReport instances from this goal's plan.
            child_goal_reports: GoalReport instances from dependency goals.
            max_chars: Maximum chars for summary (0 = unlimited).

        Returns:
            Synthesized summary string.
        """
        parts: list[str] = [f"Goal: {goal.description}\n"]

        if step_reports:
            parts.append("Step results:")
            for r in step_reports:
                icon = "+" if r.status == "completed" else "x"
                parts.append(
                    f"  [{icon}] {r.step_id}: {r.description}\n      Result: {r.result[:2000]}"
                )

        if child_goal_reports:
            parts.append("\nChild goal reports:")
            parts.extend(
                f"  Goal {cr.goal_id}: {cr.description}\n    Summary: {cr.summary[:500]}"
                for cr in child_goal_reports
            )

        synthesis_prompt = "\n".join(parts) + (
            "\n\n---\n"
            "Produce a comprehensive final report in Markdown for a human reader.\n"
            "Structure the report as follows:\n"
            "1. **Executive Summary**: 2-3 sentence overview of what was accomplished.\n"
            "2. **Key Findings**: Consolidate the most important data points, facts,\n"
            "   and conclusions from all steps into a coherent narrative. Use tables,\n"
            "   bullet points, or numbered lists where appropriate. Do NOT simply\n"
            "   repeat each step -- synthesize and deduplicate across steps.\n"
            "3. **Cross-Validation**: Note any contradictions, conflicting data, or\n"
            "   discrepancies found across steps. If none, state that sources agree.\n"
            "4. **Gaps & Limitations**: What information is missing or incomplete?\n"
            "5. **Confidence**: State high/medium/low based on source agreement.\n\n"
            "Keep the report between 500-2000 words. Write in the same language as\n"
            "the original goal. Use Markdown formatting for readability.\n"
        )

        try:
            if self._planner and hasattr(self._planner, "_invoke"):
                summary = await self._planner._invoke(synthesis_prompt)  # type: ignore[attr-defined]
                logger.info("LLM synthesis complete for goal %s (%d chars)", goal.id, len(summary))

                # Only truncate if max_chars > 0
                if max_chars > 0 and len(summary) > max_chars:
                    logger.warning(
                        "Truncating synthesis from %d to %d chars", len(summary), max_chars
                    )
                    return summary[:max_chars]
                return summary
        except Exception:
            logger.debug("LLM synthesis failed, using heuristic", exc_info=True)

        return self._heuristic_goal_summary(goal, step_reports)

    def _heuristic_goal_summary(self, goal: Any, step_reports: list[Any]) -> str:
        """Build a structured heuristic summary when LLM synthesis is unavailable.

        Concatenates step results into sections rather than a one-liner.

        Args:
            goal: The goal being summarized.
            step_reports: StepReport instances from this goal's plan.

        Returns:
            Markdown-formatted summary string.
        """
        completed = [r for r in step_reports if r.status == "completed"]
        failed = [r for r in step_reports if r.status == "failed"]
        logger.info(
            "Heuristic fallback for goal %s: %d completed, %d failed",
            goal.id,
            len(completed),
            len(failed),
        )

        lines: list[str] = []
        lines.append(f"# {goal.description}\n")
        lines.append(f"**Status**: {len(completed)}/{len(step_reports)} steps completed")
        if failed:
            lines.append(f"**Failed**: {', '.join(r.step_id for r in failed)}\n")
        else:
            lines.append("")

        for r in completed:
            lines.append(f"## {r.description}\n")
            result_text = r.result[:2000].strip() if r.result else "(no output)"
            lines.append(result_text)
            lines.append("")

        return "\n".join(lines)
