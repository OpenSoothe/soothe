"""Context projection for the Context Engine (RFC-624).

ContextBundle is a pure projection of DAG/ledger state for prompt templates.
Observability (token totals, DAG summaries) and semantic-instruction loading
belong to LoopState / checkpoint and the SemanticLoader call sites
respectively — not the projection bundle.
"""

import logging

from pydantic import BaseModel, Field

from soothe.context.ledger import LedgerManager
from soothe.context.models import GoalNode, GoalStepDAG
from soothe.context.semantic import SemanticLoader

logger = logging.getLogger(__name__)


class ProjectionConfig(BaseModel):
    """Limits for bounded projection."""

    max_goals: int = 5
    max_lineage_chars: int = 2000


class PriorGoalSummary(BaseModel):
    """Condensed summary of a completed goal for cross-goal context (RFC-624 Phase 4)."""

    goal_id: str
    description: str
    status: str
    step_summary: str
    completion_text: str = ""
    total_duration_ms: int = 0
    total_tokens_used: int = 0


class ContextBundle(BaseModel):
    """Structured output of ContextEngine.project() for prompt templates.

    This is not a rendered string — it is structured data that prompt
    templates render into appropriate message sections.

    Fields are limited to what prompt consumers actually read:
    ``active_goal``, ``goal_lineage``, ``step_lineage``, ``prior_goals``.
    """

    active_goal: GoalNode | None = None
    goal_lineage: str = ""
    step_lineage: str = ""

    # RFC-624 Phase 4: cross-goal context
    prior_goals: list[PriorGoalSummary] = Field(default_factory=list)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "…"


class ProjectionEngine:
    """Builds a ContextBundle from ContextEngine state, bounded by ProjectionConfig."""

    def __init__(self, config: ProjectionConfig | None = None) -> None:
        self._config = config or ProjectionConfig()

    async def project(
        self,
        dag: GoalStepDAG,
        ledger: LedgerManager,
        semantic: SemanticLoader,
        goal_id: str | None = None,
    ) -> ContextBundle:
        """Build ContextBundle for a specific goal (or the active goal).

        Args:
            dag: Current GoalStepDAG state.
            ledger: Current ledger manager (unused — ledger context is projected
                by the prompt layer via plan_ledger_projection, not the bundle).
            semantic: Current semantic loader (unused — instruction loading is
                performed at the consumer call site, not in the bundle).
            goal_id: Target goal. If None, uses the active goal.

        Returns:
            Bounded ContextBundle for prompt template rendering.
        """
        _ = (ledger, semantic)

        # Resolve target goal
        goal: GoalNode | None = None
        if goal_id:
            goal = dag.get_goal(goal_id)
        else:
            active = dag.active_goals()
            goal = active[0] if active else None

        cfg = self._config

        goal_lineage = ""
        step_lineage = ""

        if goal is not None:
            # Lineage
            lineage_chain = dag.goal_lineage(goal.id)
            goal_lineage = _truncate(
                " → ".join(lineage_chain),
                cfg.max_lineage_chars,
            )

            step_dag = goal.steps
            reasoning_parts = [
                n.reasoning_trace
                for n in step_dag.nodes.values()
                if n.reasoning_trace and n.status == "pending"
            ]
            if reasoning_parts:
                step_lineage = _truncate(
                    "\n".join(reasoning_parts),
                    cfg.max_lineage_chars,
                )

        # RFC-624 Phase 4: cross-goal context
        prior_goals = self._render_prior_goals(dag, cfg.max_goals)

        return ContextBundle(
            active_goal=goal,
            goal_lineage=goal_lineage,
            step_lineage=step_lineage,
            prior_goals=prior_goals,
        )

    @staticmethod
    def _render_prior_goals(dag: GoalStepDAG, max_goals: int) -> list[PriorGoalSummary]:
        """Build PriorGoalSummary list from completed/failed goals."""
        from soothe.context.models import TERMINAL_STATES

        terminal = [g for g in dag.goals.values() if g.status in TERMINAL_STATES]
        # Most recent first
        terminal.sort(key=lambda g: g.updated_at, reverse=True)
        terminal = terminal[:max_goals]

        summaries: list[PriorGoalSummary] = []
        for g in terminal:
            step_parts: list[str] = []
            for sid in sorted(g.steps.nodes.keys()):
                node = g.steps.nodes[sid]
                if node.status == "completed":
                    desc = (node.description or "").strip().replace("\n", " ")[:80]
                    step_parts.append(f"  - {sid}: {desc}")
            summaries.append(
                PriorGoalSummary(
                    goal_id=g.id,
                    description=g.description,
                    status=g.status,
                    step_summary="\n".join(step_parts) if step_parts else "",
                    total_duration_ms=g.total_duration_ms,
                    total_tokens_used=g.total_tokens_used,
                )
            )
        return summaries
