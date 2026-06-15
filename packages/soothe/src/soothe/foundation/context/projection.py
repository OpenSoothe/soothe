"""Context projection for the Context Engine (RFC-624)."""

import logging

from pydantic import BaseModel, Field

from soothe.foundation.context.ledger import LedgerManager
from soothe.foundation.context.models import GoalNode, GoalStepDAG, StepNode
from soothe.foundation.context.semantic import SemanticLoader

logger = logging.getLogger(__name__)

_GOAL_PROGRESS_MAX = 500


class ProjectionConfig(BaseModel):
    """Limits for bounded projection."""

    max_goals: int = 5
    max_steps_per_goal: int = 10
    max_ledger_chars: int = 4000
    max_ledger_messages: int = 20
    max_lineage_chars: int = 2000
    max_project_instructions_chars: int = 8000


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
    """

    active_goal: GoalNode | None = None
    goal_progress: str = ""

    pending_steps: list[StepNode] = Field(default_factory=list)
    completed_steps: list[StepNode] = Field(default_factory=list)
    failed_steps: list[StepNode] = Field(default_factory=list)

    ledger_summary: str = ""
    ledger_messages: list[dict] = Field(default_factory=list)

    project_instructions: str = ""
    agent_instructions: str = ""
    memory_instructions: str = ""

    goal_lineage: str = ""
    step_lineage: str = ""

    total_tokens_used: int = 0
    goal_dag_summary: str = ""

    # RFC-624 Phase 4: cross-goal context
    prior_goals: list[PriorGoalSummary] = Field(default_factory=list)
    cross_goal_ledger: list[dict] = Field(default_factory=list)


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
            ledger: Current ledger manager.
            semantic: Current semantic loader.
            goal_id: Target goal. If None, uses the active goal.

        Returns:
            Bounded ContextBundle for prompt template rendering.
        """

        # Resolve target goal
        goal: GoalNode | None = None
        if goal_id:
            goal = dag.get_goal(goal_id)
        else:
            active = dag.active_goals()
            goal = active[0] if active else None

        cfg = self._config

        # Goal context
        goal_progress = ""
        pending_steps: list[StepNode] = []
        completed_steps: list[StepNode] = []
        failed_steps: list[StepNode] = []
        goal_lineage = ""
        step_lineage = ""

        if goal is not None:
            goal_progress = self._render_goal_progress(goal)
            goal_progress = _truncate(goal_progress, _GOAL_PROGRESS_MAX)

            step_dag = goal.steps
            pending_steps = [step_dag.nodes[sid] for sid in sorted(step_dag.pending_step_ids())][
                : cfg.max_steps_per_goal
            ]
            completed_list = [step_dag.nodes[sid] for sid in sorted(step_dag.completed_step_ids())]
            failed_list = [step_dag.nodes[sid] for sid in sorted(step_dag.failed_step_ids())]
            completed_steps = completed_list[: cfg.max_steps_per_goal]
            failed_steps = failed_list[: cfg.max_steps_per_goal]

            # Lineage
            lineage_chain = dag.goal_lineage(goal.id)
            goal_lineage = _truncate(
                " → ".join(lineage_chain),
                cfg.max_lineage_chars,
            )

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

        # Ledger context
        ledger_summary = ledger.render_for_reason(max_chars=cfg.max_ledger_chars)

        ledger_messages: list[dict] = []
        for msg, phase in ledger.entries():
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = ""
            ledger_messages.append(
                {
                    "type": type(msg).__name__,
                    "phase": phase,
                    "content": _truncate(content, 500),
                }
            )
        ledger_messages = ledger_messages[-cfg.max_ledger_messages :]

        # Semantic context
        project_instructions = _truncate(
            semantic.load_project_instructions(),
            cfg.max_project_instructions_chars,
        )
        agent_instructions = _truncate(
            semantic.load_agent_instructions(),
            cfg.max_project_instructions_chars,
        )
        memory_instructions = _truncate(
            semantic.load_memory(),
            cfg.max_project_instructions_chars,
        )

        # Observability
        total_tokens = sum(g.total_tokens_used for g in dag.goals.values())
        goal_dag_summary = self._render_dag_summary(dag)

        # RFC-624 Phase 4: cross-goal context
        prior_goals = self._render_prior_goals(dag, cfg.max_goals)
        cross_goal_ledger = self._render_cross_goal_ledger(ledger, cfg.max_ledger_messages)

        return ContextBundle(
            active_goal=goal,
            goal_progress=goal_progress,
            pending_steps=pending_steps,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            ledger_summary=ledger_summary,
            ledger_messages=ledger_messages,
            project_instructions=project_instructions,
            agent_instructions=agent_instructions,
            memory_instructions=memory_instructions,
            goal_lineage=goal_lineage,
            step_lineage=step_lineage,
            total_tokens_used=total_tokens,
            goal_dag_summary=goal_dag_summary,
            prior_goals=prior_goals,
            cross_goal_ledger=cross_goal_ledger,
        )

    @staticmethod
    def _render_goal_progress(goal: GoalNode) -> str:
        steps = goal.steps
        total = steps.total_steps
        completed = steps.completed_steps
        failed = steps.failed_steps
        if total == 0:
            return "No steps planned yet."
        parts = [f"Steps: {completed}/{total} completed"]
        if failed:
            parts.append(f"{failed} failed")
        return ", ".join(parts)

    @staticmethod
    def _render_dag_summary(dag: GoalStepDAG) -> str:
        if not dag.goals:
            return "No goals."
        total = len(dag.goals)
        active = len(dag.active_goals())
        completed = sum(1 for g in dag.goals.values() if g.status == "completed")
        failed = sum(1 for g in dag.goals.values() if g.status == "failed")
        parts = [f"Goals: {total} total"]
        if active:
            parts.append(f"{active} active")
        parts.append(f"{completed} completed")
        if failed:
            parts.append(f"{failed} failed")
        return ", ".join(parts)

    @staticmethod
    def _render_prior_goals(dag: GoalStepDAG, max_goals: int) -> list[PriorGoalSummary]:
        """Build PriorGoalSummary list from completed/failed goals."""
        from soothe.foundation.context.models import TERMINAL_STATES

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

    @staticmethod
    def _render_cross_goal_ledger(ledger: LedgerManager, max_messages: int) -> list[dict]:
        """Build cross-goal ledger entries from LedgerManager."""
        messages: list[dict] = []
        for msg, phase in ledger.entries():
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = ""
            messages.append(
                {
                    "type": type(msg).__name__,
                    "phase": phase,
                    "content": _truncate(content, 500),
                }
            )
        return messages[-max_messages:]
