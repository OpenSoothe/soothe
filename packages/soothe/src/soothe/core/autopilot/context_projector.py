"""Project parents' GoalDispatchContextContribution entries into one bundle (RFC-222 revised).

The projector is what makes bounded summarization work for arbitrary DAG
shapes. It reads every parent goal's stored contribution, merges + dedups
them, and emits a single ``GoalDispatchContextBundle`` capped at the limits
configured in ``ContextProjectionConfig``.

Relevance heuristic (v1, per RFC-222 Q2):
- Findings: rank by ``relevance_score * recency_weight`` where recency_weight
  decays the older the parent goal was. Take top-K.
- Files: dedup by path; latest hash wins.
- Plan steps: union, prefer most recent N by parent ``updated_at``.
- Tool stats: simple counter union.
- Cached prompt prefix: take the most recent parent's hash (best chance of
  provider-side cache hit on the next call).

The projector never mutates the goal store or the goal engine; it only reads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.core.goal_engine.models import (
    GoalDispatchContextBundle,
    ParentFinding,
)

if TYPE_CHECKING:
    from soothe.config.models import ContextProjectionConfig
    from soothe.core.autopilot.context_store import GoalDispatchContextStoreProtocol
    from soothe.core.goal_engine.models import (
        FileTouchSummary,
        Goal,
        GoalDispatchContextContribution,
        PriorStepSummary,
        ToolCallStats,
    )

logger = logging.getLogger(__name__)


class ContextProjector:
    """Builds a GoalDispatchContextBundle from a goal's parents (RFC-222 revised).

    Bounded by ``ContextProjectionConfig``. Reads contributions from the
    injected ``GoalDispatchContextStoreProtocol``; never writes.

    Args:
        store: Store of per-goal contributions.
        config: Limits on bundle size (max_findings / max_files / max_plan_steps).
    """

    def __init__(
        self,
        store: GoalDispatchContextStoreProtocol,
        config: ContextProjectionConfig,
    ) -> None:
        self._store = store
        self._config = config

    async def project(
        self,
        goal: Goal,
        all_goals: dict[str, Goal],
    ) -> GoalDispatchContextBundle:
        """Project parents' stored contributions into a hydration bundle.

        Args:
            goal: The goal that is about to be dispatched.
            all_goals: Lookup table {goal_id: Goal} used to read parent
                metadata (recency, status). Pass ``goal_engine._goals``
                or any equivalent mapping.

        Returns:
            A bundle merged from ``goal.depends_on`` (hard parents) and
            ``goal.informs`` (soft parents). Empty bundle when goal has
            no parents or no parent has a stored contribution.
        """
        parent_ids = list(goal.depends_on) + list(goal.informs)
        if not parent_ids:
            return GoalDispatchContextBundle()

        contributions = await self._store.get_many(parent_ids)
        if not contributions:
            return GoalDispatchContextBundle()

        # Order parents by recency (most-recently-updated parent first).
        ordered_pairs = self._order_by_recency(parent_ids, contributions, all_goals)

        return GoalDispatchContextBundle(
            prior_plan_steps=self._merge_plan_steps(ordered_pairs),
            files_touched=self._merge_files(ordered_pairs),
            findings=self._merge_findings(ordered_pairs),
            tool_call_summary=self._merge_tool_stats(ordered_pairs),
            cached_system_prompt_hash=self._pick_prompt_cache_hash(ordered_pairs),
        )

    # ---- merge helpers --------------------------------------------------

    @staticmethod
    def _order_by_recency(
        parent_ids: list[str],
        contributions: dict[str, GoalDispatchContextContribution],
        all_goals: dict[str, Goal],
    ) -> list[tuple[str, GoalDispatchContextContribution]]:
        """Return (parent_id, contribution) pairs ordered most-recent-first."""

        def recency(pid: str) -> float:
            parent = all_goals.get(pid)
            if parent is None:
                return 0.0
            return parent.updated_at.timestamp()

        pairs = [(pid, contributions[pid]) for pid in parent_ids if pid in contributions]
        pairs.sort(key=lambda p: recency(p[0]), reverse=True)
        return pairs

    def _merge_plan_steps(
        self,
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> list[PriorStepSummary]:
        from soothe.core.goal_engine.models import PriorStepSummary

        merged: list[PriorStepSummary] = []
        for parent_id, contribution in ordered_pairs:
            for step in contribution.plan_steps_executed:
                merged.append(
                    PriorStepSummary(
                        id=step.id,
                        description=step.action,
                        status=step.outcome,
                        duration_ms=step.duration_ms,
                        goal_id_origin=parent_id,
                    )
                )
            if len(merged) >= self._config.max_plan_steps:
                break
        return merged[: self._config.max_plan_steps]

    def _merge_files(
        self,
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> dict[str, FileTouchSummary]:
        """Dedup files by path. Latest contribution wins (recency-ordered)."""
        merged: dict[str, FileTouchSummary] = {}
        for _, contribution in ordered_pairs:
            for path, summary in contribution.files_touched.items():
                if path in merged:
                    continue  # already taken by a more-recent parent
                merged[path] = summary
                if len(merged) >= self._config.max_files:
                    return merged
        return merged

    def _merge_findings(
        self,
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> list[ParentFinding]:
        """Union all findings, score by relevance × recency, take top-K."""

        # Weight is 1.0 for most-recent parent, decays linearly to 0.5 for oldest.
        n = max(len(ordered_pairs), 1)
        ranked: list[tuple[float, ParentFinding]] = []
        for idx, (parent_id, contribution) in enumerate(ordered_pairs):
            recency_w = 1.0 - (0.5 * idx / n)
            for f in contribution.findings:
                score = f.relevance_score * recency_w
                ranked.append(
                    (
                        score,
                        ParentFinding(
                            goal_id_origin=parent_id,
                            summary=f.summary,
                            relevance_score=f.relevance_score,
                        ),
                    )
                )

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [pf for _, pf in ranked[: self._config.max_findings]]

    @staticmethod
    def _merge_tool_stats(
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> ToolCallStats:
        from soothe.core.goal_engine.models import ToolCallStats

        counts: dict[str, int] = {}
        failures: dict[str, int] = {}
        for _, contribution in ordered_pairs:
            for name, n in contribution.tool_call_stats.counts_by_name.items():
                counts[name] = counts.get(name, 0) + n
            for name, n in contribution.tool_call_stats.failures_by_name.items():
                failures[name] = failures.get(name, 0) + n
        return ToolCallStats(counts_by_name=counts, failures_by_name=failures)

    @staticmethod
    def _pick_prompt_cache_hash(
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> str | None:
        # GoalDispatchContextContribution doesn't carry a prompt hash on the
        # output side today; this hook is reserved for Phase B when the worker
        # emits its last-used prompt prefix. For now, return None so callers
        # can degrade gracefully.
        return None
