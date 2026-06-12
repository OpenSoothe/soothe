"""Context Engine adapters bridging CE to existing AgentLoop interfaces (RFC-624 Phase 3).

Three adapter classes wrap `ContextEngine` to present identical interfaces to
existing code, ensuring 100% behavioral equivalence when the ContextEngine path
is enabled:

- `ContextEnginePlanAdapter` → satisfies `PlanManager` interface
- `ContextEngineLedgerAdapter` → mirrors ledger writes to both `loop_messages` and `LedgerManager`
- `ContextEngineGoalContextAdapter` → satisfies `GoalContextManager` interface
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.context.engine import ContextEngine
from soothe.context.models import StepExecution, StepNode
from soothe.foundation.loop.planning.manager import (
    CompletionStrategy,
    DagPlanningContext,
    FinalResponseMode,
)

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import LoopState, PlanResult, StepResult

logger = logging.getLogger(__name__)


class ContextEnginePlanAdapter:
    """Wraps ContextEngine to satisfy the PlanManager interface.

    The existing orchestrator nodes (plan_assess, plan_generate, resolve_decision,
    record_iteration) call the adapter as if it were PlanManager. The adapter
    maintains its own `plan_history` and `goal_id` to track the active goal
    within ContextEngine.

    Key insight: `_format_dag_context()` in builder.py uses duck typing on
    exactly 9 attributes. The adapter's `get_planning_context()` returns a
    `DagPlanningContext` dataclass providing all of them, so builder.py works
    without modification.
    """

    def __init__(
        self,
        context_engine: ContextEngine,
        goal: str,
        goal_id: str | None = None,
    ) -> None:
        self._ce = context_engine
        self._goal = goal
        self._goal_id = goal_id
        self.plan_history: list[PlanResult] = []

    @property
    def goal_id(self) -> str | None:
        return self._goal_id

    @goal_id.setter
    def goal_id(self, value: str) -> None:
        self._goal_id = value

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        """Map PlanResult.steps → ContextEngine StepDAG, preserving composite step IDs."""
        self.plan_history.append(plan_result)

        if self._goal_id is None:
            logger.warning("ContextEnginePlanAdapter: no goal_id set, skipping ingest_plan")
            return

        decision = plan_result.decision
        if decision is None:
            return

        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return

        for step in decision.steps:
            cid = step.id
            if cid in goal.steps.nodes:
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
            "ContextEnginePlanAdapter: ingested %d steps for goal %s (plan_id=%s, iter=%d)",
            len(decision.steps),
            self._goal_id,
            plan_id,
            iteration,
        )

    def record_step_outcomes(self, step_results: list[StepResult]) -> None:
        """Map each StepResult → StepDAG status transitions directly."""
        if self._goal_id is None:
            return

        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return

        for r in step_results:
            execution = StepExecution(
                duration_ms=r.duration_ms,
                thread_id=r.thread_id,
                error=r.error,
            )
            if r.success:
                goal.steps.mark_completed(r.step_id, execution)
            else:
                goal.steps.mark_failed(r.step_id, execution)

    def get_planning_context(self) -> DagPlanningContext:
        """Return DagPlanningContext with identical fields to PlanManager.get_planning_context().

        Reads from the active goal's StepDAG via ContextEngine, constructing
        the same 9 attributes that `_format_dag_context()` accesses via duck typing.
        """
        if self._goal_id is None:
            return DagPlanningContext()

        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return DagPlanningContext()

        step_dag = goal.steps
        return DagPlanningContext(
            pending_step_ids=step_dag.pending_step_ids(),
            failed_step_ids=step_dag.failed_step_ids(),
            ready_step_ids=step_dag.ready_steps(),
            chain_depth=step_dag.chain_depth,
            success_rate=step_dag.success_rate,
            replan_count=max(0, len(self.plan_history) - 1),
            total_steps=step_dag.total_steps,
            completed_steps=step_dag.completed_steps,
        )

    def format_completion_dag_report(self) -> str:
        """Render from GoalStepDAG instead of PlanDAG, same output format."""
        if self._goal_id is None:
            return ""

        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return ""

        step_dag = goal.steps
        if step_dag.total_steps == 0:
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
            f"- Distinct plan waves ingested: {len(self.plan_history)}",
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

    def determine_goal_completion_needs(
        self,
        llm_decision: bool,
        state: Any,
        mode: str = "llm_only",
    ) -> bool:
        """Delegate to existing heuristics — identical logic to PlanManager."""
        if mode == "llm_only":
            return llm_decision
        if mode == "heuristic_only":
            return self._heuristic_requires_goal_completion(state)
        if llm_decision:
            return True
        return self._heuristic_requires_goal_completion(state)

    def _heuristic_requires_goal_completion(self, state: Any) -> bool:
        """Same heuristic as PlanManager._heuristic_requires_goal_completion."""
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            return True
        if getattr(state, "last_wave_hit_subagent_cap", False):
            return True

        if self._goal_id is None:
            return False
        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return False

        failed_count = goal.steps.failed_steps
        if failed_count > 0:
            total = goal.steps.completed_steps + failed_count
            success_rate = goal.steps.completed_steps / total if total > 0 else 0.0
            if success_rate < 0.6:
                return True

        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= 3
                for step in state.current_decision.steps
            )
            if has_deps:
                return True

        return False

    def determine_completion_strategy(
        self,
        state: LoopState,
        plan_result: PlanResult,
        mode: FinalResponseMode = "adaptive",
    ) -> CompletionStrategy:
        """Determine goal completion strategy — identical logic to PlanManager."""
        if mode == "always_synthesize":
            return CompletionStrategy.SYNTHESIZE

        if not plan_result.require_goal_completion:
            if self._is_simple_execution():
                return CompletionStrategy.LEDGER_DIRECT
            return CompletionStrategy.SYNTHESIZE

        if self._dag_requires_synthesis(state):
            return CompletionStrategy.SYNTHESIZE

        from soothe.foundation.loop.utils.messages import last_ledger_ai_content

        ledger_text = last_ledger_ai_content(state)
        if not ledger_text:
            return CompletionStrategy.SYNTHESIZE

        from soothe.foundation.loop.planning.manager import _can_return_directly_from_ledger

        if _can_return_directly_from_ledger(ledger_text, plan_result):
            return CompletionStrategy.LEDGER_DIRECT

        return CompletionStrategy.SYNTHESIZE

    def _is_simple_execution(self) -> bool:
        """Check if the DAG represents a simple, single-plan execution."""
        if self._goal_id is None:
            return True
        goal = self._ce._dag.get_goal(self._goal_id)
        if goal is None:
            return True
        step_dag = goal.steps
        return (
            len(self.plan_history) <= 1
            and not any(n.dependencies for n in step_dag.nodes.values())
            and step_dag.failed_steps == 0
            and step_dag.total_steps <= 2
        )

    def _dag_requires_synthesis(self, state: LoopState) -> bool:
        """Check whether DAG complexity warrants synthesis."""
        if len(self.plan_history) >= 2:
            return True

        if self._goal_id is not None:
            goal = self._ce._dag.get_goal(self._goal_id)
            if goal is not None:
                if goal.steps.failed_steps > 0:
                    return True
                if goal.steps.chain_depth >= 3:
                    return True

        if getattr(state, "last_wave_hit_subagent_cap", False):
            return True
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            return True

        if self._goal_id is not None:
            goal = self._ce._dag.get_goal(self._goal_id)
            if goal is not None:
                failed_count = goal.steps.failed_steps
                if failed_count > 0:
                    total = goal.steps.completed_steps + failed_count
                    success_rate = goal.steps.completed_steps / total if total > 0 else 0.0
                    if success_rate < 0.6:
                        return True

        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= 3
                for step in state.current_decision.steps
            )
            if has_deps:
                return True

        return False


class ContextEngineLedgerAdapter:
    """Mirrors ledger writes to both `LoopState.loop_messages` and `LedgerManager`.

    Every append to `loop_messages` is also recorded in `LedgerManager` with
    the correct phase tag. `project_loop_messages_for_plan()` continues to work
    on the native `loop_messages` list — the adapter doesn't change how the
    ledger is consumed by PromptBuilder.

    LedgerManager serves as the persistence/recovery path; `loop_messages`
    remains the real-time prompt path.
    """

    def __init__(self, context_engine: ContextEngine) -> None:
        self._ce = context_engine

    def record_message(
        self,
        message: Any,
        phase: str,
        loop_messages: list[Any],
    ) -> None:
        """Mirror a message to both loop_messages and LedgerManager.

        Args:
            message: The message to record.
            phase: Phase tag (e.g., "execute_step", "plan_assess", "plan_generate").
            loop_messages: The LoopState.loop_messages list to append to.
        """
        loop_messages.append(message)

        from langchain_core.messages import BaseMessage

        if isinstance(message, BaseMessage):
            self._ce._ledger.record_message(message, phase)


class ContextEngineGoalContextAdapter:
    """Wraps ContextEngine to provide the same interfaces as GoalContextManager.

    Reads goal history from the GoalStepDAG instead of AgentLoopStateManager,
    producing identical XML blocks for plan context and execute briefings.
    """

    def __init__(
        self,
        context_engine: ContextEngine,
        state_manager: Any,
        config: Any = None,
    ) -> None:
        self._ce = context_engine
        self._state_manager = state_manager
        self._config = config

    async def get_plan_context(self, limit: int | None = None) -> list[str]:
        """Get previous goal summaries for Plan phase (XML blocks).

        Reads completed goals from the GoalStepDAG and formats them identically
        to GoalContextManager.get_plan_context().
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return []

        try:
            checkpoint = await self._state_manager.load()
            if not checkpoint or not checkpoint.goal_history:
                return []

            current_thread = checkpoint.current_thread_id
            actual_limit = limit or getattr(self._config, "plan_limit", 10) if self._config else 10

            completed_goals = [
                g
                for g in checkpoint.goal_history
                if g.thread_id == current_thread and g.status == "completed"
            ][-actual_limit:]

            if not completed_goals:
                return []

            context_blocks = []
            for goal in completed_goals:
                context_block = (
                    f"<previous_goal>\n"
                    f"Goal: {goal.goal_text}\n"
                    f"Status: {goal.status}\n"
                    f"Thread: {goal.thread_id}\n"
                    f"Output:\n{goal.goal_completion}\n"
                    f"</previous_goal>"
                )
                context_blocks.append(context_block)

            logger.info(
                "CE Plan context: %d previous goals from thread %s",
                len(context_blocks),
                current_thread,
            )
            return context_blocks

        except Exception as e:
            logger.warning("CE GoalContextAdapter: failed to load plan context: %s", e)
            return []

    async def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).

        Delegates to the same logic as GoalContextManager since the checkpoint
        data source is the same.
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return None

        try:
            checkpoint = await self._state_manager.load()
            if not checkpoint:
                return None

            if not checkpoint.thread_switch_pending:
                return None

            checkpoint.thread_switch_pending = False
            await self._state_manager.save(checkpoint)

            actual_limit = (
                limit or getattr(self._config, "execute_limit", 10) if self._config else 10
            )
            previous_goals = [g for g in checkpoint.goal_history if g.status == "completed"][
                -actual_limit:
            ]

            if not previous_goals:
                return None

            from soothe.foundation.loop.engine.goal_context_manager import GoalContextManager

            gcm = GoalContextManager.__new__(GoalContextManager)
            gcm._state_manager = self._state_manager
            gcm._config = self._config

            return gcm._format_execute_briefing(previous_goals, checkpoint.current_thread_id)

        except Exception as e:
            logger.error("CE GoalContextAdapter: failed to generate execute briefing: %s", e)
            return None
