"""Completion heuristics for goal and step-level planning (RFC-624 Phase 3c).

Single source of truth for completion strategy determination. Extracted from
PlanManager to eliminate duplication with ContextEnginePlanAdapter.

All functions take primitive/keyword arguments rather than LoopState or PlanDAG,
preserving ContextEngine's independence from StrangeLoop (RFC-624 invariant).
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.config.models import CompletionRulesConfig, normalize_agentic_final_response_mode

logger = logging.getLogger(__name__)

_DEFAULT_RULES = CompletionRulesConfig()

# Backward-compatible module aliases (tests and legacy imports).
DAG_DEPENDENCY_THRESHOLD = _DEFAULT_RULES.dag_dependency_threshold
LOW_SUCCESS_RATE_THRESHOLD = _DEFAULT_RULES.low_success_rate_threshold
_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS = _DEFAULT_RULES.simple_ledger_direct_max_steps
_LEDGER_DIRECT_MAX_TOOL_CALLS = _DEFAULT_RULES.ledger_direct_max_tool_calls


def _rules(completion_rules: CompletionRulesConfig | None) -> CompletionRulesConfig:
    return completion_rules or _DEFAULT_RULES


# ── Core heuristic functions ───────────────────────────────────────────


def heuristic_requires_goal_completion(
    *,
    dag_failed_steps: int,
    dag_completed_steps: int,
    last_execute_wave_parallel_multi_step: bool,
    last_wave_hit_subagent_cap: bool,
    current_decision_steps: list[Any] | None = None,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Deterministic heuristic for whether goal-completion synthesis is needed."""
    rules = _rules(completion_rules)
    if last_execute_wave_parallel_multi_step:
        logger.info("Heuristic: parallel_multi_step=True")
        return True

    if last_wave_hit_subagent_cap:
        logger.info("Heuristic: subagent_cap=True")
        return True

    if dag_failed_steps > 0:
        total = dag_completed_steps + dag_failed_steps
        success_rate = dag_completed_steps / total if total > 0 else 0.0
        if success_rate < rules.low_success_rate_threshold:
            logger.info("Heuristic: failed_steps (rate=%.0f%%)", success_rate * 100)
            return True
        logger.debug(
            "Heuristic: failed_steps_high_success (rate=%.0f%%) → skip", success_rate * 100
        )

    if current_decision_steps:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= rules.dag_dependency_threshold
            for step in current_decision_steps
        )
        if has_deps:
            logger.info("Heuristic: dag_dependencies=True")
            return True

    logger.debug("Heuristic: simple_execution (skip synthesis)")
    return False


def _ledger_direct_eligible(
    *,
    plan_wave_count: int,
    has_dag_dependencies: bool,
    failed_steps: int,
    total_steps: int,
    last_wave_tool_call_count: int,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Declarative structural gates for ``ledger_direct`` (no content heuristics)."""
    rules = _rules(completion_rules)
    if not (
        plan_wave_count <= 1
        and not has_dag_dependencies
        and failed_steps == 0
        and total_steps <= rules.simple_ledger_direct_max_steps
    ):
        return False

    if last_wave_tool_call_count > rules.ledger_direct_max_tool_calls:
        logger.info(
            "LedgerDirect: tool_calls=%d > max=%d → synthesize",
            last_wave_tool_call_count,
            rules.ledger_direct_max_tool_calls,
        )
        return False

    return True


def _dag_requires_synthesis(
    *,
    plan_wave_count: int,
    failed_steps: int,
    completed_steps: int,
    chain_depth: int,
    last_wave_hit_subagent_cap: bool,
    last_execute_wave_parallel_multi_step: bool,
    current_decision_steps: list[Any] | None = None,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Check whether DAG complexity warrants synthesis."""
    rules = _rules(completion_rules)
    if plan_wave_count >= 2:
        logger.info("Synthesis: replan detected (plans=%d) → synthesize", plan_wave_count)
        return True

    if failed_steps > 0:
        logger.info("Synthesis: failed steps (%d) → synthesize", failed_steps)
        return True

    if chain_depth >= 3:
        logger.info("Synthesis: deep chain (depth=%d) → synthesize", chain_depth)
        return True

    if last_wave_hit_subagent_cap:
        logger.info("Synthesis: subagent cap hit → synthesize")
        return True

    if last_execute_wave_parallel_multi_step:
        logger.info("Synthesis: parallel multi-step → synthesize")
        return True

    if failed_steps > 0:
        total = completed_steps + failed_steps
        success_rate = completed_steps / total if total > 0 else 0.0
        if success_rate < rules.low_success_rate_threshold:
            logger.info("Synthesis: low success rate (%.0f%%) → synthesize", success_rate * 100)
            return True

    if current_decision_steps:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= rules.dag_dependency_threshold
            for step in current_decision_steps
        )
        if has_deps:
            logger.info("Synthesis: dag_dependencies → synthesize")
            return True

    logger.debug("Synthesis: simple execution → no synthesis required")
    return False


# ── Composite decision functions ───────────────────────────────────────


def determine_goal_completion_needs(
    llm_decision: bool,
    mode: str = "llm_only",
    *,
    dag_failed_steps: int = 0,
    dag_completed_steps: int = 0,
    last_execute_wave_parallel_multi_step: bool = False,
    last_wave_hit_subagent_cap: bool = False,
    current_decision_steps: list[Any] | None = None,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Decide whether goal-completion synthesis/reporting is required."""
    if mode == "llm_only":
        logger.debug("GoalCompletion: mode=llm_only result=%s", llm_decision)
        return llm_decision

    if mode == "heuristic_only":
        result = heuristic_requires_goal_completion(
            dag_failed_steps=dag_failed_steps,
            dag_completed_steps=dag_completed_steps,
            last_execute_wave_parallel_multi_step=last_execute_wave_parallel_multi_step,
            last_wave_hit_subagent_cap=last_wave_hit_subagent_cap,
            current_decision_steps=current_decision_steps,
            completion_rules=completion_rules,
        )
        logger.debug("GoalCompletion: mode=heuristic_only result=%s", result)
        return result

    if llm_decision:
        logger.debug("GoalCompletion: mode=hybrid LLM=True (honored)")
        return True

    heuristic_result = heuristic_requires_goal_completion(
        dag_failed_steps=dag_failed_steps,
        dag_completed_steps=dag_completed_steps,
        last_execute_wave_parallel_multi_step=last_execute_wave_parallel_multi_step,
        last_wave_hit_subagent_cap=last_wave_hit_subagent_cap,
        current_decision_steps=current_decision_steps,
        completion_rules=completion_rules,
    )
    if heuristic_result:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=True")
    else:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=False (skip)")

    return heuristic_result


def determine_completion_strategy(
    *,
    plan_result_require_goal_completion: bool,
    plan_wave_count: int,
    has_dag_dependencies: bool,
    failed_steps: int,
    total_steps: int,
    completed_steps: int,
    chain_depth: int,
    last_wave_hit_subagent_cap: bool,
    last_execute_wave_parallel_multi_step: bool,
    last_wave_tool_call_count: int = 0,
    current_decision_steps: list[Any] | None = None,
    ledger_text: str | None = None,
    final_response_mode: str = "auto",
    completion_rules: CompletionRulesConfig | None = None,
) -> str:
    """Determine goal completion strategy from DAG + history."""
    mode = normalize_agentic_final_response_mode(final_response_mode)

    if mode == "always_synthesize":
        return "synthesize"

    if plan_result_require_goal_completion:
        logger.info("Completion: require_goal_completion=True → synthesize")
        return "synthesize"

    if _dag_requires_synthesis(
        plan_wave_count=plan_wave_count,
        failed_steps=failed_steps,
        completed_steps=completed_steps,
        chain_depth=chain_depth,
        last_wave_hit_subagent_cap=last_wave_hit_subagent_cap,
        last_execute_wave_parallel_multi_step=last_execute_wave_parallel_multi_step,
        current_decision_steps=current_decision_steps,
        completion_rules=completion_rules,
    ):
        return "synthesize"

    if not (ledger_text or "").strip():
        logger.info("Completion: empty ledger → synthesize")
        return "synthesize"

    if _ledger_direct_eligible(
        plan_wave_count=plan_wave_count,
        has_dag_dependencies=has_dag_dependencies,
        failed_steps=failed_steps,
        total_steps=total_steps,
        last_wave_tool_call_count=last_wave_tool_call_count,
        completion_rules=completion_rules,
    ):
        return "ledger_direct"

    return "synthesize"
