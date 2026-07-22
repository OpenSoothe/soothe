"""Step-level planning subengine for ContextEngine (RFC-624 Phase 3c).

Absorbs PlanManager responsibilities: plan ingestion, step outcome recording,
DagPlanningContext construction, completion heuristics, and DAG report formatting.
Operates on ContextEngine's GoalStepDAG directly, eliminating the
ContextEnginePlanAdapter bridge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from soothe.context.models import GoalNode, GoalStepDAG, StepExecution, StepNode
from soothe.context.planning_completion import (
    determine_completion_strategy as _determine_completion_strategy,
)
from soothe.context.planning_completion import (
    determine_goal_completion_needs as _determine_goal_completion_needs,
)
from soothe.context.planning_models import (
    CompletionStrategy,
    DagPlanningContext,
    PlanWave,
)
from soothe.utils.text_preview import goal_description_for_log

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import PlanResult, StepExecutionRecord

logger = logging.getLogger(__name__)


@dataclass
class _DagStats:
    """Primitive DAG stats extracted from a goal's StepDAG for heuristic functions."""

    plan_wave_count: int
    failed_steps: int
    completed_steps: int
    total_steps: int
    has_dag_dependencies: bool
    chain_depth: int
    success_rate: float
    pending_step_ids: set[str]
    failed_step_ids: set[str]
    ready_step_ids: set[str]


def _extract_dag_stats(goal: GoalNode, plan_wave_count: int) -> _DagStats:
    """Extract primitive stats from a goal's StepDAG for heuristic functions."""
    step_dag = goal.steps
    has_deps = any(n.dependencies for n in step_dag.nodes.values())
    return _DagStats(
        plan_wave_count=plan_wave_count,
        failed_steps=step_dag.failed_steps,
        completed_steps=step_dag.completed_steps,
        total_steps=step_dag.total_steps,
        has_dag_dependencies=has_deps,
        chain_depth=step_dag.chain_depth,
        success_rate=step_dag.success_rate,
        pending_step_ids=step_dag.pending_step_ids(),
        failed_step_ids=step_dag.failed_step_ids(),
        ready_step_ids=step_dag.ready_steps(),
    )


class StepPlanningSubengine:
    """Manages step-level DAG planning within ContextEngine.

    Absorbs PlanManager responsibilities: plan ingestion, step outcome
    recording, DagPlanningContext construction, completion heuristics,
    and DAG report formatting. Operates on ContextEngine's GoalStepDAG
    directly, eliminating the ContextEnginePlanAdapter bridge.

    This class does NOT own state — it reads/writes through the
    GoalStepDAG passed to it, maintaining ContextEngine as the single
    source of truth.

    All methods take ``goal_id`` as the first parameter to support
    multi-goal awareness.
    """

    def __init__(self, dag: GoalStepDAG) -> None:
        self._dag = dag
        self._plan_waves: list[PlanWave] = []

    @property
    def plan_waves(self) -> list[PlanWave]:
        return self._plan_waves

    # --- Ingestion ---

    def ingest_plan(
        self,
        goal_id: str,
        plan_result: PlanResult,
        plan_id: str | None,
        iteration: int,
    ) -> None:
        """Map PlanResult.steps → GoalStepDAG StepNodes.

        Replaces both PlanManager.ingest_plan and
        ContextEnginePlanAdapter.ingest_plan.
        """
        self._plan_waves.append(
            PlanWave(
                plan_id=plan_id,
                iteration=iteration,
                step_count=len(plan_result.decision.steps) if plan_result.decision else 0,
            )
        )

        goal = self._dag.get_goal(goal_id)
        if goal is None:
            logger.warning(
                "StepPlanningSubengine: goal %s not found, skipping ingest_plan", goal_id
            )
            return

        decision = plan_result.decision
        if decision is None:
            return

        for step in decision.steps:
            cid = step.id
            if cid in goal.steps.nodes:
                # Node already exists (e.g., from a keep plan); update if needed
                existing = goal.steps.nodes[cid]
                if existing.status == "pending" and step.dependencies:
                    existing.dependencies = list(step.dependencies)
                continue

            deps = list(step.dependencies) if step.dependencies else []
            goal.steps.add_step(
                StepNode(
                    id=cid,
                    description=step.description,
                    dependencies=deps,
                    plan_iteration=iteration,
                )
            )

        logger.debug(
            "StepPlanningSubengine: ingested %d steps for goal %s (plan_id=%s, iter=%d)",
            len(decision.steps),
            goal_id,
            plan_id,
            iteration,
        )

    def record_step_outcomes(
        self,
        goal_id: str,
        step_results: list[StepExecutionRecord],
    ) -> None:
        """Map StepExecutionRecord → StepDAG status transitions.

        Replaces both PlanManager.record_step_outcomes and
        ContextEnginePlanAdapter.record_step_outcomes.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return

        for r in step_results:
            execution = StepExecution(
                duration_ms=r.duration_ms,
                thread_id=r.thread_id,
                error=r.error,
                error_type=r.error_type,
                outcome=r.outcome if r.outcome else None,
                tool_call_count=r.tool_call_count,
                subagent_task_completions=r.subagent_task_completions,
                hit_subagent_cap=r.hit_subagent_cap,
                hit_tool_budget=r.hit_tool_budget,
            )
            if r.success:
                goal.steps.mark_completed(r.step_id, execution)
            else:
                goal.steps.mark_failed(r.step_id, execution)

    # --- Planning context ---

    def get_planning_context(self, goal_id: str) -> DagPlanningContext:
        """Return DagPlanningContext for a specific goal.

        Reads from the goal's StepDAG via GoalStepDAG. Identical
        9-attribute output to PlanManager.get_planning_context.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return DagPlanningContext()

        step_dag = goal.steps
        return DagPlanningContext(
            pending_step_ids=step_dag.pending_step_ids(),
            failed_step_ids=step_dag.failed_step_ids(),
            ready_step_ids=step_dag.ready_steps(),
            chain_depth=step_dag.chain_depth,
            success_rate=step_dag.success_rate,
            replan_count=max(0, len(self._plan_waves) - 1),
            total_steps=step_dag.total_steps,
            completed_steps=step_dag.completed_steps,
        )

    # --- Completion ---

    def determine_goal_completion_needs(
        self,
        goal_id: str,
        llm_decision: bool,
        state: Any,
        mode: str = "llm_only",
    ) -> bool:
        """Delegate to completion.determine_goal_completion_needs.

        Extracts DAG stats from goal_id's StepDAG and passes
        them as keyword arguments, preserving CE independence.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return llm_decision

        stats = _extract_dag_stats(goal, len(self._plan_waves))

        return _determine_goal_completion_needs(
            llm_decision=llm_decision,
            mode=mode,
            dag_failed_steps=stats.failed_steps,
            dag_completed_steps=stats.completed_steps,
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
        )

    def determine_completion_strategy(
        self,
        goal_id: str,
        state: Any,
        plan_result: Any,
        mode: str = "auto",
    ) -> CompletionStrategy:
        """Delegate to completion.determine_completion_strategy."""
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return CompletionStrategy.SYNTHESIZE

        stats = _extract_dag_stats(goal, len(self._plan_waves))

        from soothe.sloop.utils.messages import last_ledger_ai_content

        ledger_text = last_ledger_ai_content(state) if state else None

        assessment_terminal = False
        if plan_result is not None:
            assessment_terminal = (
                getattr(plan_result, "status", None) == "done"
                or getattr(plan_result, "goal_progress", None) == "complete"
            )

        strategy_str = _determine_completion_strategy(
            plan_result_require_goal_completion=(
                plan_result.require_goal_completion if plan_result else True
            ),
            plan_wave_count=stats.plan_wave_count,
            has_dag_dependencies=stats.has_dag_dependencies,
            failed_steps=stats.failed_steps,
            total_steps=stats.total_steps,
            completed_steps=stats.completed_steps,
            chain_depth=stats.chain_depth,
            last_wave_hit_subagent_cap=getattr(state, "last_wave_hit_subagent_cap", False),
            last_execute_wave_parallel_multi_step=getattr(
                state, "last_execute_wave_parallel_multi_step", False
            ),
            current_decision_steps=(
                state.current_decision.steps if getattr(state, "current_decision", None) else None
            ),
            ledger_text=ledger_text,
            final_response_mode=mode,
            last_wave_tool_call_count=int(getattr(state, "last_wave_tool_call_count", 0) or 0),
            assessment_terminal=assessment_terminal,
        )

        return CompletionStrategy(strategy_str)

    def format_completion_dag_report(self, goal_id: str | None = None) -> str:
        """Render the full GoalStepDAG report.

        When goal_id is provided, produces a focused single-goal step DAG
        report. When None, renders all goals (hierarchical report).
        """
        all_goals = list(self._dag.goals.values())

        # Single-goal focused report
        if goal_id is not None:
            goal = self._dag.get_goal(goal_id)
            if goal is None:
                return ""
            if goal.steps.total_steps == 0:
                # Goal exists but has no steps — render minimal goal report
                return self._format_goal_only_report(goal)
            return self._format_single_goal_report(goal)

        # No goals at all
        if not all_goals:
            return ""

        # Hierarchical report (all goals)
        return self._format_hierarchical_report(all_goals)

    # --- Internal helpers ---

    def _format_goal_only_report(self, goal: GoalNode) -> str:
        """Format a minimal report for a goal with no steps."""
        lines: list[str] = [
            "### Context Engine Goal DAG (at goal completion)",
            "",
            f"**Goal {goal.id}** — {goal.status.upper()}",
            f"- Description: {goal_description_for_log(goal.description)}",
            f"- Source: {goal.source}, Priority: {goal.priority}",
            "",
        ]
        return "\n".join(lines).strip()

    def _format_single_goal_report(self, goal: GoalNode) -> str:
        """Format a single goal's step DAG report (backward-compat with PlanManager output)."""
        ctx = self.get_planning_context(goal.id)
        step_dag = goal.steps
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
            f"- Distinct plan waves ingested: {len(self._plan_waves)}",
        ]
        if ctx.replan_count > 0:
            lines.append(f"- Replans after first wave: {ctx.replan_count}")
        lines.extend(["", "**Steps**", ""])
        for cid in sorted(step_dag.nodes.keys()):
            node = step_dag.nodes[cid]
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

    def _format_hierarchical_report(self, all_goals: list[GoalNode]) -> str:
        """Render the full GoalStepDAG with all goals and nested step DAGs."""
        lines: list[str] = [
            "### Context Engine Goal DAG (at goal completion)",
            "",
        ]

        # Goal-level statistics
        status_counts: dict[str, int] = {}
        for g in all_goals:
            status_counts[g.status] = status_counts.get(g.status, 0) + 1
        lines.append("**Goal statistics**")
        lines.append(f"- Total goals: {len(all_goals)}")
        for status in ("active", "completed", "failed", "pending", "suspended", "cancelled"):
            count = status_counts.get(status, 0)
            if count:
                lines.append(f"- {status.capitalize()}: {count}")
        lines.append("")

        # Sort goals: failed first, then completed, then by created_at
        status_order = {
            "failed": 0,
            "active": 1,
            "completed": 2,
            "pending": 3,
            "suspended": 4,
            "cancelled": 5,
        }
        sorted_goals = sorted(
            all_goals, key=lambda g: (status_order.get(g.status, 9), g.created_at)
        )

        for goal in sorted_goals:
            status_label = goal.status.upper()
            lines.append(f"**Goal {goal.id}** — {status_label}")
            lines.append(f"- Description: {goal_description_for_log(goal.description)}")
            lines.append(f"- Source: {goal.source}, Priority: {goal.priority}")
            lines.append(f"- Parent: {goal.parent_id or '—'}")

            # Lineage for sub-goals
            if goal.parent_id:
                lineage = self._dag.goal_lineage(goal.id)
                if lineage:
                    lines.append(f"- Lineage: {' > '.join(lineage)}")

            if goal.thread_id:
                lines.append(f"- Thread: {goal.thread_id}")
            if goal.assigned_loop_id:
                lines.append(f"- Loop: {goal.assigned_loop_id}")
            if goal.total_tokens_used:
                lines.append(f"- Tokens used: {goal.total_tokens_used}")

            # Nested StepDAG
            step_dag = goal.steps
            if step_dag.total_steps > 0:
                executed = step_dag.completed_steps + step_dag.failed_steps
                success_pct = f"{step_dag.success_rate:.0%}" if executed else "N/A"
                lines.append("")
                lines.append(
                    f"  **Step DAG** "
                    f"({step_dag.total_steps} steps, "
                    f"completed={step_dag.completed_steps}, "
                    f"failed={step_dag.failed_steps}, "
                    f"depth={step_dag.chain_depth}, "
                    f"success={success_pct})"
                )
                for cid in sorted(step_dag.nodes.keys()):
                    node = step_dag.nodes[cid]
                    dep_s = ", ".join(sorted(node.dependencies)) if node.dependencies else "—"
                    step_status = node.status.upper()
                    desc = (node.description or "").replace("\n", " ").strip()
                    if len(desc) > 280:
                        desc = desc[:277] + "..."
                    lines.append(f"  - **{cid}** — {step_status}")
                    lines.append(f"    - Depends on: {dep_s}")
                    if desc:
                        lines.append(f"    - {desc}")

            lines.append("")

        # Plan wave metadata
        lines.append(f"Distinct plan waves ingested: {len(self._plan_waves)}")
        replan_count = max(0, len(self._plan_waves) - 1)
        if replan_count > 0:
            lines.append(f"Replans after first wave: {replan_count}")

        return "\n".join(lines).strip()


class StepPlanManagerAdapter:
    """Binds goal_id to StepPlanningSubengine to satisfy the PlanManager duck-typed interface.

    The existing orchestrator nodes (plan_assess, plan_generate, resolve_decision,
    record_iteration, goal_completion, execute_steps) call 5 methods on the
    plan_manager object. This adapter binds a specific goal_id so the method
    signatures match exactly.

    ~30 lines vs the previous ContextEnginePlanAdapter at 420+ lines with
    150 lines of duplicated heuristic logic.
    """

    def __init__(
        self,
        subengine: StepPlanningSubengine,
        goal_id: str,
    ) -> None:
        self._subengine = subengine
        self._goal_id = goal_id
        self.plan_history: list[PlanResult] = []

    @property
    def goal_id(self) -> str | None:
        return self._goal_id or None

    @goal_id.setter
    def goal_id(self, value: str) -> None:
        self._goal_id = value

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        self.plan_history.append(plan_result)
        self._subengine.ingest_plan(self._goal_id, plan_result, plan_id, iteration)

    def record_step_outcomes(self, step_results: list[StepExecutionRecord]) -> None:
        self._subengine.record_step_outcomes(self._goal_id, step_results)

    def get_planning_context(self) -> DagPlanningContext:
        return self._subengine.get_planning_context(self._goal_id)

    def determine_goal_completion_needs(
        self,
        llm_decision: bool,
        state: Any,
        mode: str = "llm_only",
    ) -> bool:
        return self._subengine.determine_goal_completion_needs(
            self._goal_id, llm_decision, state, mode
        )

    def determine_completion_strategy(
        self,
        state: Any,
        plan_result: Any,
        mode: str = "auto",
    ) -> CompletionStrategy:
        return self._subengine.determine_completion_strategy(
            self._goal_id, state, plan_result, mode
        )

    def format_completion_dag_report(self) -> str:
        return self._subengine.format_completion_dag_report()
