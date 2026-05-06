"""Goal-level plan orchestration and completion strategy (replaces goal_completion_policy)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from soothe.core.agent_loop.utils.messages import last_ledger_ai_content

from .dag import PlanDAG

if TYPE_CHECKING:
    from soothe.core.agent_loop.state.schemas import LoopState, PlanResult, StepResult

logger = logging.getLogger(__name__)


@dataclass
class DagPlanningContext:
    """Structured DAG summary for LLM planning (IG-400 interleaving)."""

    pending_step_ids: set[str] = field(default_factory=set)
    failed_step_ids: set[str] = field(default_factory=set)
    ready_step_ids: set[str] = field(default_factory=set)
    chain_depth: int = 0
    success_rate: float = 1.0
    replan_count: int = 0
    total_steps: int = 0
    completed_steps: int = 0

    @property
    def has_prior_state(self) -> bool:
        return self.total_steps > 0


# Execution complexity thresholds
_DAG_DEPENDENCY_THRESHOLD = 3
_LOW_SUCCESS_RATE_THRESHOLD = 0.6
_STRUCTURED_PAYLOAD_MIN_LINES = 6
_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS = 2


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
    """Standalone heuristic check (used by planner.py without PlanManager)."""
    if getattr(state, "last_execute_wave_parallel_multi_step", False):
        return True
    if getattr(state, "last_wave_hit_subagent_cap", False):
        return True

    failed_count = sum(1 for r in getattr(state, "step_results", []) if not r.success)
    if failed_count > 0:
        total = len(getattr(state, "step_results", []))
        success_rate = (total - failed_count) / total if total > 0 else 0.0
        if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
            return True

    if state.current_decision:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
            for step in state.current_decision.steps
        )
        if has_deps:
            return True

    return False


class CompletionStrategy(StrEnum):
    LEDGER_DIRECT = "ledger_direct"
    SYNTHESIZE = "synthesize"
    SUMMARY = "summary"


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
        if mode == "llm_only":
            logger.debug("GoalCompletion: mode=llm_only result=%s", llm_decision)
            return llm_decision

        if mode == "heuristic_only":
            result = self._heuristic_requires_goal_completion(state)
            logger.debug("GoalCompletion: mode=heuristic_only result=%s", result)
            return result

        # Hybrid mode: LLM primary, heuristic fallback
        if llm_decision:
            logger.debug("GoalCompletion: mode=hybrid LLM=True (honored)")
            return True

        heuristic_result = self._heuristic_requires_goal_completion(state)
        if heuristic_result:
            logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=True")
        else:
            logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=False (skip)")

        return heuristic_result

    def _heuristic_requires_goal_completion(self, state: TYPE_CHECKING.Any) -> bool:
        """Check execution complexity indicators requiring synthesis."""
        # Wave execution complexity
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            logger.info("Heuristic: parallel_multi_step=True")
            return True

        if getattr(state, "last_wave_hit_subagent_cap", False):
            logger.info("Heuristic: subagent_cap=True")
            return True

        # Completion quality: failed steps need explanation
        failed_count = self.dag.failed_steps
        if failed_count > 0:
            total = self.dag.completed_steps + failed_count
            success_rate = self.dag.completed_steps / total if total > 0 else 0.0
            if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
                logger.info("Heuristic: failed_steps (rate=%.0f%%)", success_rate * 100)
                return True
            logger.debug(
                "Heuristic: failed_steps_high_success (rate=%.0f%%) → skip", success_rate * 100
            )

        # DAG dependencies on the current plan
        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
                for step in state.current_decision.steps
            )
            if has_deps:
                logger.info("Heuristic: dag_dependencies=True")
                return True

        logger.debug("Heuristic: simple_execution (skip synthesis)")
        return False

    # --- Completion strategy ---

    def determine_completion_strategy(
        self,
        state: LoopState,
        plan_result: PlanResult,
        mode: FinalResponseMode = "adaptive",
    ) -> CompletionStrategy:
        """Determine goal completion strategy from the full DAG + history."""
        # 1. Mode override
        if mode == "always_synthesize":
            return CompletionStrategy.SYNTHESIZE

        # 2. Planner says no synthesis needed
        if not plan_result.require_goal_completion:
            if self._is_simple_execution():
                return CompletionStrategy.LEDGER_DIRECT
            return CompletionStrategy.SYNTHESIZE

        # 3. DAG complexity vetoes — complex execution needs synthesis
        if self._dag_requires_synthesis(state):
            return CompletionStrategy.SYNTHESIZE

        # 4. Ledger richness check
        ledger_text = last_ledger_ai_content(state)
        if not ledger_text:
            return CompletionStrategy.SYNTHESIZE

        if _can_return_directly_from_ledger(ledger_text, plan_result):
            return CompletionStrategy.LEDGER_DIRECT

        # 5. Default
        return CompletionStrategy.SYNTHESIZE

    def _is_simple_execution(self) -> bool:
        """Check if the DAG represents a simple, single-plan execution."""
        return (
            self.dag.plan_count <= 1
            and not self.dag.has_dag_dependencies
            and self.dag.failed_steps == 0
            and self.dag.total_steps <= _SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS
        )

    def _dag_requires_synthesis(self, state: LoopState) -> bool:
        """Check whether DAG complexity warrants synthesis."""
        if self.dag.plan_count >= 2:
            logger.info("PlanManager: replan detected (plans=%d) → synthesize", self.dag.plan_count)
            return True

        if self.dag.failed_steps > 0:
            logger.info("PlanManager: failed steps (%d) → synthesize", self.dag.failed_steps)
            return True

        if self.dag.used_subagents:
            logger.info("PlanManager: subagents used → synthesize")
            return True

        if self.dag.max_chain_depth >= 3:
            logger.info("PlanManager: deep chain (depth=%d) → synthesize", self.dag.max_chain_depth)
            return True

        if getattr(state, "last_wave_hit_subagent_cap", False):
            logger.info("PlanManager: subagent cap hit → synthesize")
            return True

        # Heuristic: parallel multi-step wave
        if getattr(state, "last_execute_wave_parallel_multi_step", False):
            logger.info("PlanManager: parallel multi-step → synthesize")
            return True

        # Heuristic: low success rate with failed steps
        failed_count = self.dag.failed_steps
        if failed_count > 0:
            total = self.dag.completed_steps + failed_count
            success_rate = self.dag.completed_steps / total if total > 0 else 0.0
            if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
                logger.info(
                    "PlanManager: low success rate (%.0f%%) → synthesize", success_rate * 100
                )
                return True

        # Heuristic: DAG dependencies on current plan
        if state.current_decision:
            has_deps = any(
                step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
                for step in state.current_decision.steps
            )
            if has_deps:
                logger.info("PlanManager: dag_dependencies → synthesize")
                return True

        logger.debug("PlanManager: simple execution → no synthesis required")
        return False


# --- Ledger overlap helpers (migrated from goal_completion_policy) ---


def _can_return_directly_from_ledger(
    ledger_text: str,
    plan_result: PlanResult,
) -> bool:
    """Check richness + overlap with planner output for ledger direct return."""
    if not _is_rich_enough(ledger_text):
        return False
    return _overlaps_with_plan_output(ledger_text, plan_result)


def _is_rich_enough(text: str) -> bool:
    """Heuristic guard for rich, user-facing completion content."""
    text = text.strip()
    if not text:
        return False
    if "```" in text:
        return True
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if len(non_empty_lines) >= _STRUCTURED_PAYLOAD_MIN_LINES:
        return True
    return len(text) >= 100


def _overlaps_with_plan_output(ledger_text: str, plan_result: PlanResult) -> bool:
    """Return True when ledger text appears to reflect the planner's full_output."""
    plan_out = (plan_result.full_output or "").strip()
    if not plan_out:
        return True

    ledger_lower = ledger_text.lower()
    probe = plan_out[:160].lower()
    if not probe.strip():
        return True

    tokens = [t for t in re.split(r"\W+", probe) if len(t) >= 4]
    if not tokens:
        return True

    hits = sum(1 for t in tokens if t in ledger_lower)
    return hits * 4 >= len(tokens)
