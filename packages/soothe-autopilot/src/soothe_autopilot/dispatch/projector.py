"""Project parents' GoalDispatchContextContribution entries into one bundle (RFC-222 revised).

The projector is what makes bounded summarization work for arbitrary DAG
shapes. It reads every parent goal's stored contribution, merges + dedups
them, and emits a single ``GoalDispatchContextBundle`` capped at the limits
configured in ``ContextProjectionConfig``.

Relevance heuristic (v1, per RFC-222 Q2):
- Findings: rank by ``relevance_score * recency_weight`` where recency_weight
  decays the older the parent goal was. Take top-K.
- Effects: dedup by ``ref``; latest parent wins (IG-712).
- Plan steps: union, prefer most recent N by parent ``updated_at``.
- Tool stats: simple counter union.

The projector never mutates the goal store or the goal engine; it only reads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.goal_contracts import (
    MAX_PREAMBLE_TURNS,
    GoalDispatchContextBundle,
    GoalEffect,
    GoalReportAITurn,
    GoalReportUserTurn,
    ParentFinding,
)

if TYPE_CHECKING:
    from soothe.config.models import ContextProjectionConfig
    from soothe.context.models import GoalNode
    from soothe.goal_contracts import (
        GoalDispatchContextContribution,
        PriorStepSummary,
        ToolCallStats,
    )

    from soothe_autopilot.dispatch.store import GoalDispatchContextStoreProtocol

logger = logging.getLogger(__name__)


class ContextProjector:
    """Builds a GoalDispatchContextBundle from a goal's parents (RFC-222 revised).

    Bounded by ``ContextProjectionConfig``. Reads contributions from the
    injected ``GoalDispatchContextStoreProtocol``; never writes.

    Args:
        store: Store of per-goal contributions.
        config: Limits on bundle size (max_findings / max_effects / max_plan_steps).
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
        goal: GoalNode,
        all_goals: dict[str, GoalNode],
    ) -> GoalDispatchContextBundle:
        """Project parents' stored contributions into a hydration bundle.

        Args:
            goal: The goal that is about to be dispatched.
            all_goals: Lookup table {goal_id: GoalNode} used to read parent
                metadata (recency, status). Pass ``goal_engine._goals``
                or any equivalent mapping.

        Returns:
            A bundle merged from ``goal.depends_on`` (hard parents) and
            ``goal.informs`` (soft parents). Empty bundle when goal has
            no parents. When direct parents lack contributions but
            transitive ancestors have them, the flat fields are empty
            but ``preamble_messages`` may still carry ancestor pairs.
        """
        parent_ids = list(goal.depends_on) + list(goal.informs)
        if not parent_ids:
            return GoalDispatchContextBundle()

        contributions = await self._store.get_many(parent_ids)

        # RFC-222 §Goal-Report-Pair Projection: build a real (user, ai)
        # transcript from the full transitive ancestor subgraph. Built even
        # when direct parents lack contributions — transitive ancestors
        # (e.g. a grandparent) may still carry context the flat fields miss.
        preamble = await self._build_preamble(goal, all_goals, contributions)

        if not contributions:
            # No direct-parent contributions: flat fields are empty, but the
            # preamble may still carry transitive ancestor pairs.
            return GoalDispatchContextBundle(preamble_messages=preamble)

        # Order parents by recency (most-recently-updated parent first).
        ordered_pairs = self._order_by_recency(parent_ids, contributions, all_goals)

        return GoalDispatchContextBundle(
            prior_plan_steps=self._merge_plan_steps(ordered_pairs),
            prior_effects=self._merge_effects(ordered_pairs),
            findings=self._merge_findings(ordered_pairs),
            tool_call_summary=self._merge_tool_stats(ordered_pairs),
            preamble_messages=preamble,
        )

    async def build_preamble_text(
        self,
        goal: GoalNode,
        all_goals: dict[str, GoalNode],
    ) -> str:
        """Render the ancestor pair transcript as readable text (RFC-222 §Goal-Report-Pair).

        Used by the backoff reasoner so its LLM sees the same ancestor
        (user → ai) transcript the executing StrangeLoop worker does — with
        outcome, summary, findings, and effects per ancestor — instead of a
        flat description-only chain. Returns ``""`` when the goal has no
        ancestors with a stored contribution.
        """
        preamble = await self._build_preamble(goal, all_goals, {})
        if not preamble:
            return ""
        return "\n\n".join(_render_turn_text(turn) for turn in preamble)

    # ---- merge helpers --------------------------------------------------

    @staticmethod
    def _order_by_recency(
        parent_ids: list[str],
        contributions: dict[str, GoalDispatchContextContribution],
        all_goals: dict[str, GoalNode],
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
        from soothe.goal_contracts import PriorStepSummary

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

    def _merge_effects(
        self,
        ordered_pairs: list[tuple[str, GoalDispatchContextContribution]],
    ) -> list[GoalEffect]:
        """Dedup effects by ref. Latest contribution wins (recency-ordered)."""
        merged: list[GoalEffect] = []
        seen_refs: set[str] = set()
        for parent_id, contribution in ordered_pairs:
            for effect in contribution.effects:
                ref = (effect.ref or "").strip()
                if not ref or ref in seen_refs:
                    continue
                seen_refs.add(ref)
                merged.append(
                    GoalEffect(
                        kind=effect.kind,
                        ref=ref,
                        statement=effect.statement,
                        digest=effect.digest,
                        confidence=effect.confidence,
                        goal_id_origin=parent_id,
                    )
                )
                if len(merged) >= self._config.max_effects:
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
        from soothe.goal_contracts import ToolCallStats

        counts: dict[str, int] = {}
        failures: dict[str, int] = {}
        for _, contribution in ordered_pairs:
            for name, n in contribution.tool_call_stats.counts_by_name.items():
                counts[name] = counts.get(name, 0) + n
            for name, n in contribution.tool_call_stats.failures_by_name.items():
                failures[name] = failures.get(name, 0) + n
        return ToolCallStats(counts_by_name=counts, failures_by_name=failures)

    # ---- preamble (RFC-222 §Goal-Report-Pair Projection) ----------------

    async def _build_preamble(
        self,
        goal: GoalNode,
        all_goals: dict[str, GoalNode],
        direct_contributions: dict[str, GoalDispatchContextContribution],
    ) -> list[GoalReportUserTurn | GoalReportAITurn]:
        """Build the projected ancestor (user, ai) transcript.

        Walks the full transitive ancestor subgraph (``depends_on`` hard +
        ``informs`` soft, recursively), topologically sorts roots-first, and
        emits one pair per ancestor with a stored contribution. Bounded by
        ``MAX_PREAMBLE_TURNS`` (the hard IPC cap also enforced
        by ``GoalDispatchContextBundle._enforce_bounds``). Returns ``[]`` when
        the goal has no ancestors with a stored contribution.

        Args:
            goal: The goal about to be dispatched.
            all_goals: Lookup table {goal_id: GoalNode}.
            direct_contributions: Contributions already fetched for direct
                parents (reused to avoid a re-fetch for the first layer).
        """
        ancestors = self._collect_ancestors(goal, all_goals)
        if not ancestors:
            return []

        # Fetch contributions for ancestors we don't already have. The walk
        # may have surfaced transitive ancestors beyond the direct parents.
        ancestor_ids = [a.id for a in ancestors]
        missing = [aid for aid in ancestor_ids if aid not in direct_contributions]
        all_contributions = dict(direct_contributions)
        if missing:
            fetched = await self._store.get_many(missing)
            all_contributions.update(fetched)

        return self._build_preamble_pairs(ancestors, all_contributions)

    @staticmethod
    def _collect_ancestors(
        goal: GoalNode,
        all_goals: dict[str, GoalNode],
    ) -> list[GoalNode]:
        """Return transitive ancestors in topological order (roots first).

        Walks ``depends_on`` (hard) + ``informs`` (soft) recursively from
        ``goal``. A ``visited`` set guards against ``informs`` cycles. Ties
        within a topological level are broken by ``created_at`` ascending
        (older first) so the transcript reads chronologically.

        The dispatched ``goal`` itself is excluded; only its ancestors appear.
        """
        visited: set[str] = set()
        # adjacency: ancestor_id -> set of its ancestors (for topo sort)
        edges: dict[str, set[str]] = {}

        # BFS over the ancestor subgraph. Seed with goal's direct parents.
        queue: list[str] = []
        for pid in list(goal.depends_on) + list(goal.informs):
            if pid and pid not in visited:
                queue.append(pid)

        while queue:
            aid = queue.pop(0)
            if aid in visited:
                continue
            visited.add(aid)
            node = all_goals.get(aid)
            if node is None:
                edges.setdefault(aid, set())
                continue
            edges.setdefault(aid, set())
            for pid in list(node.depends_on) + list(node.informs):
                if pid:
                    edges[aid].add(pid)
                    if pid not in visited:
                        queue.append(pid)

        # Topological sort (Kahn-style) over the ancestor subset, roots-first.
        # A node is a root when none of its own parents are in the ancestor set.
        resolved: list[str] = []
        remaining = dict(edges)

        while remaining:
            # Roots: ancestors whose parents are all outside the subset or
            # already resolved.
            roots = [aid for aid, deps in remaining.items() if not (deps & set(remaining.keys()))]
            if not roots:
                # Defensive: a cycle in `informs` soft-links that the visited
                # guard didn't fully prevent. Break by taking the lowest-id
                # remaining node to guarantee forward progress.
                roots = [min(remaining.keys())]
            roots.sort(
                key=lambda aid: (
                    (all_goals[aid].created_at.timestamp() if aid in all_goals else 0.0),
                    aid,
                )
            )
            for aid in roots:
                resolved.append(aid)
                del remaining[aid]
                # No need to mutate remaining edge sets — removing the node
                # from `remaining` already makes it invisible to the roots
                # check for its dependents.

        return [all_goals[aid] for aid in resolved if aid in all_goals]

    @staticmethod
    def _build_preamble_pairs(
        ancestors: list[GoalNode],
        contributions: dict[str, GoalDispatchContextContribution],
    ) -> list[GoalReportUserTurn | GoalReportAITurn]:
        """Emit one (user, ai) pair per ancestor with a stored contribution.

        Skips ancestors with no contribution (e.g. crashed before emitting
        one) — no empty AI turns. Stops at ``MAX_PREAMBLE_TURNS``
        messages (the hard IPC cap also enforced by
        ``GoalDispatchContextBundle._enforce_bounds``). When the cap bites
        mid-subgraph, logs the drop count (no silent truncation) and keeps the
        most-recently-completed ancestors by ``updated_at``.
        """
        # Pair-ify each ancestor, skipping those without a contribution.
        candidate_pairs: list[tuple[GoalNode, GoalDispatchContextContribution]] = []
        for node in ancestors:
            contrib = contributions.get(node.id)
            if contrib is None:
                continue
            candidate_pairs.append((node, contrib))

        max_turns = MAX_PREAMBLE_TURNS
        max_pairs = max_turns // 2
        if len(candidate_pairs) > max_pairs:
            # Keep most-recently-completed by updated_at; drop oldest.
            candidate_pairs.sort(
                key=lambda pair: pair[0].updated_at.timestamp(),
                reverse=True,
            )
            dropped = len(candidate_pairs) - max_pairs
            candidate_pairs = candidate_pairs[:max_pairs]
            # Re-sort topologically by created_at (oldest first) so the
            # transcript reads chronologically.
            candidate_pairs.sort(key=lambda pair: pair[0].created_at.timestamp())
            logger.info(
                "[ContextProjector] preamble cap bit: dropped %d ancestor pair(s)",
                dropped,
            )
        else:
            # Already topologically ordered by _collect_ancestors; preserve.
            pass

        out: list[GoalReportUserTurn | GoalReportAITurn] = []
        for node, contrib in candidate_pairs:
            if len(out) + 2 > max_turns:
                break
            out.append(
                GoalReportUserTurn(
                    goal_id_origin=node.id,
                    content=(node.description or "").strip()[:2000],
                )
            )
            out.append(_build_ai_turn(node, contrib))
        return out


def _build_ai_turn(
    node: GoalNode,
    contribution: GoalDispatchContextContribution,
) -> GoalReportAITurn:
    """Build the AI half of a projected ancestor pair.

    Prefers ``GoalNode.report`` — the committed CE goal report (IG-726 SoT),
    built via ``build_goal_report`` + ``commit_goal_report`` — so the
    preamble mirrors exactly what was judged. Falls back to a minimal report
    synthesized from the stored contribution when ``report`` is absent
    (defensive: a terminal goal should always have one).

    Per-pair caps: 8 findings, 8 effects (tighter than the 40-item report
    caps — ancestor pairs are bounded context, not the full report).
    """
    report = getattr(node, "report", None)
    if isinstance(report, dict) and report:
        outcome = str(report.get("outcome") or "unknown").strip() or "unknown"
        summary = str(report.get("summary") or "").strip()
        if not summary:
            summary = f"Loop ended with outcome={outcome}"
        raw_findings = report.get("findings") or []
        findings = [str(f).strip() for f in raw_findings if str(f).strip()][:8]
        raw_effects = report.get("effects") or []
        effects: list[GoalEffect] = []
        for item in raw_effects[:8]:
            if not isinstance(item, dict):
                continue
            try:
                effects.append(GoalEffect.model_validate(item))
            except Exception:
                continue
        return GoalReportAITurn(
            goal_id_origin=node.id,
            outcome=outcome,
            summary=summary[:2000],
            findings=findings,
            effects=effects,
        )

    # Fallback: synthesize a minimal report from the contribution.
    summary = synthesize_sloop_response_from_contribution(contribution)
    return GoalReportAITurn(
        goal_id_origin=node.id,
        outcome="completed",
        summary=(summary or f"Loop ended for goal {node.id}")[:2000],
        findings=[],
        effects=list(contribution.effects)[:8],
    )


def synthesize_sloop_response_from_contribution(
    contribution: GoalDispatchContextContribution,
) -> str:
    """Best-effort one-line summary from a contribution (fallback path).

    Reuses the finding summaries when present; else a fixed string. The
    committed ``GoalNode.report`` is the primary path above; this only runs
    when ``report`` is absent.
    """
    for finding in contribution.findings:
        text = getattr(finding, "summary", None) or str(finding)
        text = str(text).strip()
        if text:
            return text[:2000]
    return ""


def _render_turn_text(turn: GoalReportUserTurn | GoalReportAITurn) -> str:
    """Render a projected pair turn as readable text (for the backoff prompt).

    Mirrors the worker's ``_render_ai_turn_text`` format so the backoff LLM
    sees the same ancestor context the executing worker did.
    """
    if isinstance(turn, GoalReportUserTurn):
        return f"[user / goal {turn.goal_id_origin}]: {turn.content}"
    # GoalReportAITurn
    parts: list[str] = [f"[ai / goal {turn.goal_id_origin}]"]
    summary = (turn.summary or "").strip()
    if summary:
        parts.append(summary)
    findings = list(turn.findings or [])
    if findings:
        lines = [f"  - {str(f).strip()}" for f in findings if str(f).strip()]
        if lines:
            parts.append("Findings:\n" + "\n".join(lines))
    effects = list(turn.effects or [])
    if effects:
        elines: list[str] = []
        for eff in effects:
            kind = getattr(eff, "kind", "")
            ref = getattr(eff, "ref", "")
            statement = getattr(eff, "statement", "")
            bit = f"[{kind}] {ref}: {statement}" if kind else f"{ref}: {statement}"
            if bit.strip(": []"):
                elines.append(f"  - {bit}")
        if elines:
            parts.append("Effects:\n" + "\n".join(elines))
    return "\n".join(parts)
