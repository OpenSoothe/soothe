"""Goal-level plan orchestration and completion strategy (replaces goal_completion_policy)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from soothe.context.planning.completion import (
    dag_requires_synthesis,
    heuristic_requires_goal_completion,
    is_simple_execution,
)
from soothe.context.planning.completion import (
    determine_completion_strategy as _determine_completion_strategy,
)
from soothe.context.planning.completion import (
    determine_goal_completion_needs as _determine_completion_needs,
)
from soothe.context.planning.models import CompletionStrategy, DagPlanningContext
from soothe.foundation.loop.utils.messages import last_ledger_ai_content

from .dag import PlanDAG

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import LoopState, PlanResult, StepResult

logger = logging.getLogger(__name__)


def determine_goal_completion_needs(
    llm_decision: bool,
    state: TYPE_CHECKING.Any,
    mode: str = "llm_only",
) -> bool:
    """Standalone function for goal-completion needs (used by planner.py).

    For graph nodes, use ``PlanManager.determine_goal_completion_needs`` instead,
    which has access to the full DAG state.

    Priority by ``mode``:
    - ``llm_only``: Return ``llm_decision`` directly.
    - ``heuristic_only``: Return execution-heuristic result only.
    - ``hybrid``: True if LLM says true; else heuristic fallback.
    """
    if mode == "llm_only":
        return llm_decision

    if mode == "heuristic_only":
        return _heuristic_requires_goal_completion_standalone(state)

    if llm_decision:
        return True

    return _heuristic_requires_goal_completion_standalone(state)


def _heuristic_requires_goal_completion_standalone(state: TYPE_CHECKING.Any) -> bool:
    """Standalone heuristic check (used by planner.py without PlanManager).

    Extracts primitive values from LoopState and delegates to
    completion.heuristic_requires_goal_completion.
    """
    return heuristic_requires_goal_completion(
        dag_failed_steps=sum(1 for r in getattr(state, "step_results", []) if not r.success),
        dag_completed_steps=sum(1 for r in getattr(state, "step_results", []) if r.success),
        last_execute_wave_parallel_multi_step=getattr(
            state, "last_execute_wave_parallel_multi_step", False
        ),
        last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
        current_decision_steps=(
            state.current_decision.steps if getattr(state, "current_decision", None) else None
        ),
    )


FinalResponseMode = Literal["adaptive", "always_synthesize"]


@dataclass
class PlanManager:
    """Manages the DAG of all planned steps for a single goal across iterations.

    Created at goal start, ingested at each plan phase, and consulted at goal
    completion to determine the final response strategy.
    """

    goal: str
    dag: PlanDAG = field(default_factory=PlanDAG)
    plan_history: list[PlanResult] = field(default_factory=list)

    # --- Ingestion ---

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        """Called from plan_assess / plan_generate after finalize_plan_result."""
        self.plan_history.append(plan_result)
        self.dag.ingest_plan(plan_result, plan_id, iteration)

    def record_step_outcomes(self, step_results: list[StepResult]) -> None:
        """Called from record_iteration after execute."""
        for r in step_results:
            if r.success:
                self.dag.mark_completed(r.step_id, r)
            else:
                self.dag.mark_failed(r.step_id, r)

    def get_planning_context(self) -> DagPlanningContext:
        """Return structured DAG summary for LLM planning."""
        return DagPlanningContext(
            pending_step_ids=self.dag.pending_step_ids,
            failed_step_ids=self.dag.failed_step_ids,
            ready_step_ids=self.dag.ready_step_ids,
            chain_depth=self.dag.max_chain_depth,
            success_rate=self.dag.success_rate,
            replan_count=self.dag.plan_count - 1,
            total_steps=self.dag.total_steps,
            completed_steps=self.dag.completed_steps,
        )

    def format_completion_dag_report(self) -> str:
        """Format unified plan DAG for operator logs (goal end).

        Includes per-step composite id, terminal status, dependencies, optional subagent,
        execution statistics, and a one-line description. Returns empty string when the
        DAG has no nodes.

        Returns:
            Plain text suitable for a single log record (may span multiple lines).
        """
        dag = self.dag
        if dag.total_steps == 0:
            return ""
        ctx = self.get_planning_context()
        failed_n = len(ctx.failed_step_ids)
        pending_n = len(ctx.pending_step_ids)
        lines: list[str] = [
            "### Plan DAG (at goal completion)",
            "",
            "**Execution statistics**",
            f"- Planned steps (nodes): {ctx.total_steps}",
            f"- Completed: {ctx.completed_steps}",
            f"- Failed: {failed_n}",
            f"- Pending (not executed): {pending_n}",
            f"- Max dependency chain depth: {ctx.chain_depth}",
            f"- Success rate over executed steps: {ctx.success_rate:.0%}",
            f"- Distinct plan waves ingested: {dag.plan_count}",
        ]
        if ctx.replan_count > 0:
            lines.append(f"- Replans after first wave: {ctx.replan_count}")
        lines.extend(["", "**Steps**", ""])
        for cid in sorted(dag.nodes.keys()):
            node = dag.nodes[cid]
            dep_s = ", ".join(sorted(node.dependencies)) if node.dependencies else "—"
            status_label = node.status.upper()
            desc = (node.description or "").replace("\n", " ").strip()
            if len(desc) > 280:
                desc = desc[:277] + "..."
            lines.append(f"- **{cid}** — {status_label}")
            lines.append(f"  - Depends on: {dep_s}")
            if desc:
                lines.append(f"  - {desc}")
        return "\n".join(lines).strip()

    def determine_goal_completion_needs(
        self,
        llm_decision: bool,
        state: TYPE_CHECKING.Any,
        mode: str = "llm_only",
    ) -> bool:
        """Decide whether goal-completion synthesis/reporting is required.

        Priority by ``mode``:
        - ``llm_only``: Return ``llm_decision`` directly.
        - ``heuristic_only``: Return execution-heuristic result only.
        - ``hybrid``: True if LLM says true; else heuristic fallback.
        """
        return _determine_completion_needs(
            llm_decision=llm_decision,
            mode=mode,
            dag_failed_steps=self.dag.failed_steps,
            dag_completed_steps=self.dag.completed_steps,
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
        )

    def _heuristic_requires_goal_completion(self, state: TYPE_CHECKING.Any) -> bool:
        """Check execution complexity indicators requiring synthesis."""
        return heuristic_requires_goal_completion(
            dag_failed_steps=self.dag.failed_steps,
            dag_completed_steps=self.dag.completed_steps,
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
        )

    # --- Completion strategy ---

    def determine_completion_strategy(
        self,
        state: LoopState,
        plan_result: PlanResult,
        mode: FinalResponseMode = "adaptive",
    ) -> CompletionStrategy:
        """Determine goal completion strategy from the full DAG + history."""
        ledger_text = last_ledger_ai_content(state)
        strategy_str = _determine_completion_strategy(
            plan_result_require_goal_completion=plan_result.require_goal_completion,
            plan_wave_count=self.dag.plan_count,
            has_dag_dependencies=self.dag.has_dag_dependencies,
            failed_steps=self.dag.failed_steps,
            total_steps=self.dag.total_steps,
            completed_steps=self.dag.completed_steps,
            chain_depth=self.dag.max_chain_depth,
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
            ledger_text=ledger_text,
            plan_result=plan_result,
            final_response_mode=mode,
        )
        return CompletionStrategy(strategy_str)

    def _is_simple_execution(self) -> bool:
        """Check if the DAG represents a simple, single-plan execution."""
        return is_simple_execution(
            plan_wave_count=self.dag.plan_count,
            has_dag_dependencies=self.dag.has_dag_dependencies,
            failed_steps=self.dag.failed_steps,
            total_steps=self.dag.total_steps,
        )

    def _dag_requires_synthesis(self, state: LoopState) -> bool:
        """Check whether DAG complexity warrants synthesis."""
        return dag_requires_synthesis(
            plan_wave_count=self.dag.plan_count,
            failed_steps=self.dag.failed_steps,
            completed_steps=self.dag.completed_steps,
            chain_depth=self.dag.max_chain_depth,
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
        )
