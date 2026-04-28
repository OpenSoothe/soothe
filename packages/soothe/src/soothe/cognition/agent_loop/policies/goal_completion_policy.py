"""Goal completion decision policy (RFC-615, IG-298, IG-299).

Unified decision logic combining hybrid assessment with completion action selection.
Consolidated from synthesis_policy.py and strategy selection (IG-299).

Decision flow:
1. Hybrid logic: LLM primary + execution heuristics (determine_goal_completion_needs)
2. Completion action: skip/direct/synthesis/summary (determine_completion_action)

Decision modes (hybrid):
- llm_only: Trust LLM decision completely (no fallback)
- heuristic_only: Ignore LLM, use execution metrics only
- hybrid: LLM primary, heuristic fallback (default)

Heuristic categories (execution-focused, IG-298):
- Wave execution: Parallel multi-step, subagent cap
- Multi-wave: Multiple execution waves (≥2)
- Step complexity: Many steps (≥3), DAG dependencies
- Completion quality: Failed steps with low success rate
- Step diversity: Multiple execution types

Removed: Word count, evidence vs output ratio (output metrics unreliable).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal

    from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult

    GoalCompletionMode = Literal["llm_only", "heuristic_only", "hybrid"]
    FinalResponseMode = Literal["adaptive", "always_synthesize", "always_last_execute"]

logger = logging.getLogger(__name__)

# Execution complexity thresholds (IG-298)
_COMPLEX_WAVE_THRESHOLD = 2  # ≥2 waves indicates multi-stage execution
_COMPLEX_STEPS_THRESHOLD = 3  # ≥3 steps indicates non-trivial task
_DAG_DEPENDENCY_THRESHOLD = 2  # ≥2 dependencies indicates complex orchestration
_LOW_SUCCESS_RATE_THRESHOLD = 0.7  # <70% success rate needs explanation

# Structural fallbacks below the word-count floor (IG-273).
_STRUCTURED_PAYLOAD_MIN_LINES = 6


def _word_count(text: str) -> int:
    """Return whitespace-separated word count; cheap proxy aligned with IG-268 targets."""
    return len(re.findall(r"\S+", text))


def _min_word_floor(category: str | None) -> int:
    """Map IG-268 category to its minimum word count, with a default for unknown inputs."""
    try:
        from soothe.cognition.agent_loop.policies.response_length_policy import (
            ResponseLengthCategory,
        )

        return ResponseLengthCategory(category).min_words if category else 150
    except ValueError:
        return 150


def determine_goal_completion_needs(
    llm_decision: bool,
    state: TYPE_CHECKING.Any,  # LoopState
    mode: str = "hybrid",
) -> bool:
    """Unified hybrid decision for goal completion synthesis.

    Priority (hybrid mode):
    1. LLM primary: If assessment.require_goal_completion=True → True
    2. Heuristic fallback: If LLM returns False → check execution complexity
    3. Agree to skip: Only False if both LLM and heuristics agree

    Args:
        llm_decision: LLM's require_goal_completion from StatusAssessment.
        state: Loop state with execution history and wave metrics.
        mode: Decision mode (llm_only, heuristic_only, hybrid).

    Returns:
        Final require_goal_completion decision.
    """
    if mode == "llm_only":
        logger.debug("GoalCompletion: mode=llm_only result=%s", llm_decision)
        return llm_decision

    if mode == "heuristic_only":
        result = _heuristic_requires_goal_completion(state)
        logger.debug("GoalCompletion: mode=heuristic_only result=%s", result)
        return result

    # Hybrid mode: LLM primary, heuristic fallback
    if llm_decision:
        logger.debug("GoalCompletion: mode=hybrid LLM=True (honored)")
        return True

    # Heuristic fallback when LLM returns False
    heuristic_result = _heuristic_requires_goal_completion(state)
    if heuristic_result:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=True")
    else:
        logger.debug("GoalCompletion: mode=hybrid LLM=False heuristic=False (skip)")

    return heuristic_result


def _heuristic_requires_goal_completion(state: TYPE_CHECKING.Any) -> bool:
    """Check execution complexity indicators requiring synthesis.

    Simplified heuristics (IG-298):
    - Execution complexity (parallel multi-step, subagent cap)
    - Step diversity (multiple step types, DAG dependencies)
    - Wave patterns (multiple execution waves)
    - Completion quality (failed steps needing explanation)

    Removed word count metrics (output-focused, unreliable).

    Args:
        state: Loop state with execution history.

    Returns:
        True if execution complexity suggests synthesis needed.
    """
    # 1. Wave execution complexity (IG-130, IG-132)
    if state.last_execute_wave_parallel_multi_step:
        logger.info("Heuristic: parallel_multi_step=True")
        return True

    if state.last_wave_hit_subagent_cap:
        logger.info("Heuristic: subagent_cap=True")
        return True

    # 2. Multi-wave execution (≥2 waves indicates non-trivial task)
    if state.iteration >= _COMPLEX_WAVE_THRESHOLD:
        logger.info("Heuristic: multi_wave (iter=%d)", state.iteration)
        return True

    # 3. Completion quality: failed steps need explanation
    failed_count = sum(1 for r in state.step_results if not r.success)
    if failed_count > 0:
        # Failed steps with low success rate need synthesis
        total = len(state.step_results)
        success_rate = (total - failed_count) / total if total > 0 else 0.0
        if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
            logger.info("Heuristic: failed_steps (rate=%.0f%%)", success_rate * 100)
            return True
        # Failed steps with high success rate don't need synthesis
        # Return False early to avoid triggering on step count
        logger.debug(
            "Heuristic: failed_steps_high_success (rate=%.0f%%) → skip", success_rate * 100
        )
        # Don't return - continue to check other indicators
        # But skip step complexity check below for this case

    # 4. Step complexity (≥3 steps or DAG dependencies)
    # Only check when all steps are successful OR when we want complexity for other reasons
    # Skip this check when there are failed steps with high success rate (handled above)
    if failed_count == 0:  # Only trigger on step count when no failures
        if len(state.step_results) >= _COMPLEX_STEPS_THRESHOLD:
            logger.info("Heuristic: many_steps (count=%d)", len(state.step_results))
            return True

    # Check for DAG dependencies in current decision
    if state.current_decision:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
            for step in state.current_decision.steps
        )
        if has_deps:
            logger.info("Heuristic: dag_dependencies=True")
            return True

    # 5. Step diversity: multiple execution modes
    if len(state.step_results) >= 2:
        # Check if steps used different tools/subagents
        step_types = set()
        for result in state.step_results:
            outcome_type = result.outcome.get("type", "unknown")
            step_types.add(outcome_type)

        if len(step_types) >= 2:
            logger.info("Heuristic: diverse_execution (types=%d)", len(step_types))
            return True

    logger.debug("Heuristic: simple_execution (skip synthesis)")
    return False


def determine_completion_action(
    state: LoopState,
    plan_result: PlanResult,
    mode: FinalResponseMode = "adaptive",
    response_length_category: str | None = None,
) -> tuple[str, str | None]:
    """Single entry point for completion decision and action (IG-299).

    Consolidates strategy selection from synthesis_policy and completion_strategies.
    Returns action and optional precomputed text for direct/skip branches.

    Args:
        state: Loop state with execution history.
        plan_result: Plan result with planner's hybrid decision.
        mode: Final-response mode (adaptive, always_synthesize, always_last_execute).
        response_length_category: IG-268 category for richness check.

    Returns:
        (action, precomputed_text) where action in {"skip", "direct", "synthesize", "summary"}
        and precomputed_text is reuse text for skip/direct, None for synthesize/summary.
    """
    # 1. Mode overrides
    if mode == "always_synthesize":
        return "synthesize", None

    if mode == "always_last_execute":
        assistant = (state.last_execute_assistant_text or "").strip()
        return ("direct", assistant) if assistant else ("summary", None)

    # 2. Planner skip: trust hybrid decision (IG-298)
    if not plan_result.require_goal_completion:
        reuse = (state.last_execute_assistant_text or "").strip()
        return "skip", reuse

    # 3. Wave execution vetoes
    if state.last_execute_wave_parallel_multi_step:
        return "synthesize", None

    if state.last_wave_hit_subagent_cap:
        return "synthesize", None

    # 4. Direct return check: richness + overlap
    assistant = (state.last_execute_assistant_text or "").strip()
    if not assistant:
        return "synthesize", None

    if _can_return_directly(assistant, plan_result, response_length_category):
        return "direct", assistant

    # 5. Synthesis needed per planner + execution complexity
    return "synthesize", None


def _can_return_directly(
    assistant_text: str,
    plan_result: PlanResult,
    response_length_category: str | None,
) -> bool:
    """Check richness (word count/structure) + overlap with planner output (IG-299).

    Args:
        assistant_text: Execute assistant output.
        plan_result: Plan result with full_output for overlap check.
        response_length_category: Length category for word floor.

    Returns:
        True if output is rich enough and aligned with planner.
    """
    # Richness check (IG-268)
    if not _is_rich_enough(assistant_text, response_length_category):
        return False

    # Overlap check (avoid unrelated chatter)
    return _overlaps_with_plan_output(assistant_text, plan_result)


def _is_rich_enough(
    assistant_text: str,
    response_length_category: str | None,
) -> bool:
    """Heuristic guard for rich, user-facing completion content (IG-268, IG-273).

    Thresholds are expressed in words to stay aligned with ResponseLengthCategory minimums.
    Short-but-structured payloads (code fences, multi-line lists) are accepted as escape hatch.
    """
    text = assistant_text.strip()
    if not text:
        return False

    min_words = _min_word_floor(response_length_category)
    if _word_count(text) >= min_words:
        return True

    # Shorter responses may still be complete when they carry structured payloads.
    if "```" in text:
        return True
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    return len(non_empty_lines) >= _STRUCTURED_PAYLOAD_MIN_LINES


def _overlaps_with_plan_output(assistant_text: str, plan_result: PlanResult) -> bool:
    """Return True when Execute text appears to reflect the planner's full_output (IG-299).

    Used only as an adaptive-mode veto signal: if the planner captured a distinct
    full_output and the Execute assistant text shares no common substring with it,
    we assume Execute did not actually answer the goal and require synthesis.
    """
    plan_out = (plan_result.full_output or "").strip()
    if not plan_out:
        # No planner reference available; do not veto on this signal.
        return True

    assistant_lower = assistant_text.lower()
    # Sample the first chunk of plan output for a lightweight overlap probe.
    probe = plan_out[:160].lower()
    if not probe.strip():
        return True

    # Split on whitespace and keep substantive tokens (avoid stopwords-ish noise).
    tokens = [t for t in re.split(r"\W+", probe) if len(t) >= 4]
    if not tokens:
        return True

    hits = sum(1 for t in tokens if t in assistant_lower)
    # Require at least 25% token overlap to accept direct return.
    return hits * 4 >= len(tokens)
