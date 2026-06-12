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
    _DAG_DEPENDENCY_THRESHOLD,
    _LOW_SUCCESS_RATE_THRESHOLD,
    _SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS,
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

        goal = self._ce.get_goal_sync(self._goal_id)
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

        goal = self._ce.get_goal_sync(self._goal_id)
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

        goal = self._ce.get_goal_sync(self._goal_id)
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
        """Render the full GoalStepDAG with all goals and nested step DAGs.

        When CE is enabled, produces a hierarchical report showing every goal
        in the GoalStepDAG with its status, metadata, lineage, and nested
        StepDAG. Falls back to the active goal's StepDAG when no goal_id is set.
        """
        all_goals = self._ce.get_all_goals()

        # Fallback: no goals at all
        if not all_goals:
            if self._goal_id is None:
                return ""
            goal = self._ce.get_goal_sync(self._goal_id)
            if goal is None or goal.steps.total_steps == 0:
                return ""

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
            lines.append(f"- Description: {goal.description}")
            lines.append(f"- Source: {goal.source}, Priority: {goal.priority}")
            lines.append(f"- Parent: {goal.parent_id or '—'}")

            # Lineage for sub-goals
            if goal.parent_id:
                lineage = self._ce.get_goal_lineage(goal.id)
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
        lines.append(f"Distinct plan waves ingested: {len(self.plan_history)}")
        replan_count = max(0, len(self.plan_history) - 1)
        if replan_count > 0:
            lines.append(f"Replans after first wave: {replan_count}")

        return "\n".join(lines).strip()

    def determine_goal_completion_needs(
        self,
        llm_decision: bool,
        state: Any,
        mode: str = "llm_only",
    ) -> bool:
        """Delegate to existing heuristics — identical logic to PlanManager."""
        if mode == "llm_only":
            logger.debug("CEPlanAdapter: goal completion mode=llm_only, decision=%s", llm_decision)
            return llm_decision
        if mode == "heuristic_only":
            result = self._heuristic_requires_goal_completion(state)
            logger.debug("CEPlanAdapter: goal completion mode=heuristic_only, result=%s", result)
            return result
        if llm_decision:
            logger.debug("CEPlanAdapter: goal completion LLM decided True")
            return True
        result = self._heuristic_requires_goal_completion(state)
        logger.debug("CEPlanAdapter: goal completion hybrid, heuristic=%s", result)
        return result

    def _heuristic_requires_goal_completion(self, state: Any) -> bool:
        """Same heuristic as PlanManager._heuristic_requires_goal_completion."""
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            logger.info("CEPlanAdapter: goal completion required (parallel multi-step)")
            return True
        if getattr(state, "last_wave_hit_subagent_cap", False):
            logger.info("CEPlanAdapter: goal completion required (subagent cap hit)")
            return True

        if self._goal_id is None:
            return False
        goal = self._ce.get_goal_sync(self._goal_id)
        if goal is None:
            return False

        failed_count = goal.steps.failed_steps
        if failed_count > 0:
            total = goal.steps.completed_steps + failed_count
            success_rate = goal.steps.completed_steps / total if total > 0 else 0.0
            if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
                logger.info(
                    "CEPlanAdapter: goal completion required (low success rate: %.0f%%)",
                    success_rate * 100,
                )
                return True

        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
                for step in state.current_decision.steps
            )
            if has_deps:
                logger.info("CEPlanAdapter: goal completion required (deep DAG dependencies)")
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
        goal = self._ce.get_goal_sync(self._goal_id)
        if goal is None:
            return True
        step_dag = goal.steps
        result = (
            len(self.plan_history) <= 1
            and not any(n.dependencies for n in step_dag.nodes.values())
            and step_dag.failed_steps == 0
            and step_dag.total_steps <= _SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS
        )
        logger.debug(
            "CEPlanAdapter: simple_execution=%s (plans=%d, steps=%d)",
            result,
            len(self.plan_history),
            step_dag.total_steps,
        )
        return result

    def _dag_requires_synthesis(self, state: LoopState) -> bool:
        """Check whether DAG complexity warrants synthesis."""
        if len(self.plan_history) >= 2:
            logger.info(
                "CEPlanAdapter: synthesis required (multiple plan waves: %d)",
                len(self.plan_history),
            )
            return True

        if self._goal_id is not None:
            goal = self._ce.get_goal_sync(self._goal_id)
            if goal is not None:
                if goal.steps.failed_steps > 0:
                    logger.info(
                        "CEPlanAdapter: synthesis required (failed steps: %d)",
                        goal.steps.failed_steps,
                    )
                    return True
                if goal.steps.chain_depth >= 3:
                    logger.info(
                        "CEPlanAdapter: synthesis required (chain depth: %d)",
                        goal.steps.chain_depth,
                    )
                    return True

        if getattr(state, "last_wave_hit_subagent_cap", False):
            logger.info("CEPlanAdapter: synthesis required (subagent cap hit)")
            return True
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            logger.info("CEPlanAdapter: synthesis required (parallel multi-step)")
            return True

        if self._goal_id is not None:
            goal = self._ce.get_goal_sync(self._goal_id)
            if goal is not None:
                failed_count = goal.steps.failed_steps
                if failed_count > 0:
                    total = goal.steps.completed_steps + failed_count
                    success_rate = goal.steps.completed_steps / total if total > 0 else 0.0
                    if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
                        logger.info(
                            "CEPlanAdapter: synthesis required (low success rate: %.0f%%)",
                            success_rate * 100,
                        )
                        return True

        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
                for step in state.current_decision.steps
            )
            if has_deps:
                logger.info("CEPlanAdapter: synthesis required (deep DAG dependencies)")
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
            self._ce.ledger.record_message(message, phase)


class ContextEngineGoalContextAdapter:
    """Wraps ContextEngine to provide the same interfaces as GoalContextManager.

    Reads goal history from the GoalStepDAG (via ContextEngine public API)
    instead of AgentLoopStateManager, producing identical XML blocks for plan
    context and execute briefings.

    Thread switch detection still uses state_manager (that concern is outside
    CE's scope), but completed goal data comes from the CE DAG.
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

        Reads completed goals from the CE GoalStepDAG. Falls back to
        state_manager if CE has no completed goals.
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return []

        try:
            if limit is not None:
                actual_limit = limit
            elif self._config:
                actual_limit = getattr(self._config, "plan_limit", 10)
            else:
                actual_limit = 10

            # Primary: read from CE DAG
            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                # Fallback to state_manager if CE has no completed goals
                if self._state_manager is not None:
                    checkpoint = await self._state_manager.load()
                    if checkpoint and checkpoint.goal_history:
                        current_thread = checkpoint.current_thread_id
                        completed_goals = [
                            g
                            for g in checkpoint.goal_history
                            if g.thread_id == current_thread and g.status == "completed"
                        ][-actual_limit:]
                        if completed_goals:
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
                            return context_blocks
                return []

            context_blocks = []
            for goal in completed:
                step_summary = self._render_step_summary(goal)
                context_block = (
                    f"<previous_goal>\n"
                    f"Goal: {goal.description}\n"
                    f"Status: {goal.status}\n"
                    f"Output:\n{step_summary}\n"
                    f"</previous_goal>"
                )
                context_blocks.append(context_block)

            logger.info(
                "CE Plan context: %d previous goals from CE DAG",
                len(context_blocks),
            )
            return context_blocks

        except Exception as e:
            logger.warning("CE GoalContextAdapter: failed to load plan context: %s", e)
            return []

    async def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).

        Thread switch detection still uses state_manager. Completed goal
        data comes from the CE DAG.
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return None

        try:
            # Thread switch detection still needs state_manager
            current_thread = ""
            if self._state_manager is not None:
                checkpoint = await self._state_manager.load()
                if not checkpoint:
                    return None
                if not checkpoint.thread_switch_pending:
                    logger.debug(
                        "CE GoalContextAdapter: execute briefing skipped (no thread switch)"
                    )
                    return None
                checkpoint.thread_switch_pending = False
                await self._state_manager.save(checkpoint)
                current_thread = checkpoint.current_thread_id

            actual_limit = (
                limit or getattr(self._config, "execute_limit", 10) if self._config else 10
            )

            # Read completed goals from CE DAG
            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                # Fallback to state_manager if CE has no completed goals
                if self._state_manager is not None:
                    checkpoint = await self._state_manager.load()
                    if checkpoint and checkpoint.goal_history:
                        previous_goals = [
                            g for g in checkpoint.goal_history if g.status == "completed"
                        ][-actual_limit:]
                        if previous_goals:
                            from soothe.foundation.loop.engine.goal_context_manager import (
                                format_execute_briefing_from_goals,
                            )

                            return format_execute_briefing_from_goals(
                                previous_goals, current_thread
                            )
                logger.warning(
                    "CE GoalContextAdapter: thread switch but no completed goals for briefing"
                )
                return None

            return _format_execute_briefing_from_ce_goals(completed, current_thread)

        except Exception as e:
            logger.error("CE GoalContextAdapter: failed to generate execute briefing: %s", e)
            return None

    @staticmethod
    def _render_step_summary(goal: Any) -> str:
        """Build a text summary from a GoalNode's completed steps."""
        if not hasattr(goal, "steps") or not goal.steps.nodes:
            return ""
        parts = []
        for sid in sorted(goal.steps.nodes.keys()):
            node = goal.steps.nodes[sid]
            if node.status == "completed":
                desc = (node.description or "").strip().replace("\n", " ")
                execution = node.execution
                if execution and execution.error:
                    parts.append(f"  - {sid}: {desc} (error: {execution.error})")
                else:
                    parts.append(f"  - {sid}: {desc}")
        return "\n".join(parts) if parts else ""


def _format_execute_briefing_from_ce_goals(goals: list, current_thread: str) -> str:
    """Format CE GoalNode objects as condensed Execute briefing.

    Parallel to ``format_execute_briefing_from_goals()`` but works with
    GoalNode objects instead of GoalExecutionRecord.
    """
    sections = ["## Previous Goal Context (Thread Switch Recovery)\n\n"]

    for i, goal in enumerate(goals, 1):
        step_summary = ContextEngineGoalContextAdapter._render_step_summary(goal)
        sections.append(
            f"**Goal {i}** ({goal.status}):\n"
            f"Query: {goal.description}\n"
            f"Steps completed:\n{step_summary}\n\n"
        )

    sections.append(
        f"**Current thread**: {current_thread} (new thread, no conversation history)\n"
        f"**Instruction**: Use previous goal context to inform step execution strategy.\n"
        f"Reference critical files discovered in prior work. Avoid re-exploring solved problems."
    )

    return "".join(sections)
