"""Completion heuristics for goal and step-level planning (RFC-624 Phase 3c).

Single source of truth for completion strategy determination. Extracted from
PlanManager to eliminate duplication with ContextEnginePlanAdapter.

All functions take primitive/keyword arguments rather than LoopState or PlanDAG,
preserving ContextEngine's independence from StrangeLoop (RFC-624 invariant).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from soothe.config.models import CompletionRulesConfig

logger = logging.getLogger(__name__)

_DEFAULT_RULES = CompletionRulesConfig()

# Backward-compatible module aliases (tests and legacy imports).
DAG_DEPENDENCY_THRESHOLD = _DEFAULT_RULES.dag_dependency_threshold
LOW_SUCCESS_RATE_THRESHOLD = _DEFAULT_RULES.low_success_rate_threshold
STRUCTURED_PAYLOAD_MIN_LINES = _DEFAULT_RULES.structured_payload_min_lines
_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS = _DEFAULT_RULES.simple_ledger_direct_max_steps


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


def _is_simple_execution(
    *,
    plan_wave_count: int,
    has_dag_dependencies: bool,
    failed_steps: int,
    total_steps: int,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Check if the DAG represents a simple, single-plan execution."""
    rules = _rules(completion_rules)
    return (
        plan_wave_count <= 1
        and not has_dag_dependencies
        and failed_steps == 0
        and total_steps <= rules.simple_ledger_direct_max_steps
    )


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
    current_decision_steps: list[Any] | None = None,
    ledger_text: str | None = None,
    plan_result: Any = None,
    final_response_mode: str = "adaptive",
    completion_rules: CompletionRulesConfig | None = None,
) -> str:
    """Determine goal completion strategy from DAG + history."""
    if final_response_mode == "always_synthesize":
        return "synthesize"

    if not plan_result_require_goal_completion:
        if _is_simple_execution(
            plan_wave_count=plan_wave_count,
            has_dag_dependencies=has_dag_dependencies,
            failed_steps=failed_steps,
            total_steps=total_steps,
            completion_rules=completion_rules,
        ):
            if (ledger_text or "").strip():
                return "ledger_direct"
            logger.info(
                "Completion: simple execution but empty ledger → synthesize",
            )
            return "synthesize"
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

    if not ledger_text:
        return "synthesize"

    if plan_result is not None and can_return_directly_from_ledger(
        ledger_text,
        plan_result,
        completion_rules=completion_rules,
    ):
        return "ledger_direct"

    return "synthesize"


# ── Ledger overlap helpers ─────────────────────────────────────────────


def can_return_directly_from_ledger(
    ledger_text: str,
    plan_result: Any,
    *,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Check richness + overlap with planner output for ledger direct return."""
    if not is_rich_enough(ledger_text, completion_rules=completion_rules):
        return False
    return overlaps_with_plan_output(
        ledger_text,
        plan_result,
        completion_rules=completion_rules,
    )


def is_rich_enough(
    text: str,
    *,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Heuristic guard for rich, user-facing completion content."""
    rules = _rules(completion_rules)
    text = text.strip()
    if not text:
        return False
    if "```" in text:
        return True
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if len(non_empty_lines) >= rules.structured_payload_min_lines:
        return True
    return len(text) >= rules.rich_text_min_chars


def overlaps_with_plan_output(
    ledger_text: str,
    plan_result: Any,
    *,
    completion_rules: CompletionRulesConfig | None = None,
) -> bool:
    """Return True when ledger text appears to reflect the planner's full_output."""
    rules = _rules(completion_rules)
    plan_out = (plan_result.full_output or "").strip() if plan_result else ""
    if not plan_out:
        return True

    ledger_lower = ledger_text.lower()
    probe = plan_out[:160].lower()
    if not probe.strip():
        return True

    min_len = rules.ledger_overlap_min_token_len
    tokens = [t for t in re.split(r"\W+", probe) if len(t) >= min_len]
    if not tokens:
        return True

    hits = sum(1 for t in tokens if t in ledger_lower)
    return hits * 4 >= len(tokens)
