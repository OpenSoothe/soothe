"""RFC-204: Consensus Loop for Layer 3 validation of Layer 2 completions.

Layer 3 validates Layer 2's "done" judgment before accepting goal completion.
If not satisfied, Layer 3 can send the goal back with refined instructions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_RESPONSE_MIN_LENGTH = 50


ConsensusDecision = Literal["accept", "send_back", "suspend"]


async def evaluate_goal_completion(
    goal_description: str,
    response_text: str,
    evidence_summary: str = "",
    success_criteria: list[str] | None = None,
    model: BaseChatModel | None = None,
    config: Any | None = None,  # IG-143: Add config for tracing
) -> tuple[ConsensusDecision, str]:
    """RFC-204: Holistic evaluation of goal completion.

    Layer 3 reflection LLM evaluates whether Layer 2's output truly
    satisfies the goal criteria.

    Args:
        goal_description: The original goal text.
        response_text: Layer 2's response/output.
        evidence_summary: Accumulated evidence from execution.
        success_criteria: List of success criteria to check.
        model: LLM for evaluation. If None, uses heuristic fallback.
        config: Optional SootheConfig for LLM tracing support.

    Returns:
        Tuple of (decision, reasoning).
        decision is "accept", "send_back", or "suspend".
    """
    if model is None:
        return _heuristic_evaluation(response_text, evidence_summary, success_criteria)

    # IG-143: Wrap model with tracing if enabled
    from soothe.core.middleware._utils import create_llm_call_metadata

    if config and hasattr(config, "llm_tracing") and config.llm_tracing.enabled:
        from soothe.core.middleware._wrapper import LLMTracingWrapper

        model = LLMTracingWrapper(model)

    prompt = _build_consensus_prompt(goal_description, response_text, evidence_summary, success_criteria)
    try:
        response = await model.ainvoke(
            prompt,
            config={
                "metadata": create_llm_call_metadata(
                    purpose="consensus_vote",
                    component="cognition.consensus",
                    phase="layer3",
                )
            },
        )
        content = response.content.strip().lower() if hasattr(response, "content") else ""

        if "send_back" in content:
            return "send_back", _extract_reasoning(content)
        if "suspend" in content:
            return "suspend", _extract_reasoning(content)
        return "accept", _extract_reasoning(content)
    except Exception:
        logger.debug("Consensus LLM evaluation failed, falling back to heuristic")
        return _heuristic_evaluation(response_text, evidence_summary, success_criteria)


def _heuristic_evaluation(
    response_text: str,
    evidence_summary: str,
    success_criteria: list[str] | None = None,
) -> tuple[ConsensusDecision, str]:
    """Fallback heuristic when LLM is unavailable.

    Args:
        response_text: Layer 2's response text.
        evidence_summary: Evidence from execution.
        success_criteria: Success criteria to check.

    Returns:
        Tuple of (decision, reasoning).
    """
    if not response_text or len(response_text.strip()) < _RESPONSE_MIN_LENGTH:
        return "send_back", "Response too short, likely incomplete or error"

    evidence = evidence_summary or response_text

    # Check for common failure indicators
    failure_indicators = [
        "i could not",
        "i was unable",
        "i don't have access",
        "i don't have the ability",
        "unfortunately, i cannot",
    ]
    lower = evidence.lower()
    for indicator in failure_indicators:
        if indicator in lower:
            return "send_back", f"Failure indicator detected: {indicator}"

    # Check success criteria mentions
    if success_criteria:
        unmet = [c for c in success_criteria if c.lower() not in lower]
        if len(unmet) > len(success_criteria) / 2:
            return "send_back", f"Most success criteria not addressed: {unmet}"

    return "accept", "Response appears substantive and relevant"


def _build_consensus_prompt(
    goal: str,
    response: str,
    evidence: str,
    criteria: list[str] | None,
) -> str:
    """Build prompt for consensus evaluation.

    Args:
        goal: Goal description.
        response: Layer 2 response text.
        evidence: Evidence summary.
        criteria: Success criteria.

    Returns:
        Prompt string for LLM evaluation.
    """
    parts = [
        "You are evaluating whether an AI agent has successfully completed a goal.",
        f"\nGoal: {goal}",
        f"\nAgent Response Preview: {response[:500]}",
    ]
    if evidence:
        parts.append(f"\nEvidence Summary: {evidence[:500]}")
    if criteria:
        parts.append("\nSuccess Criteria:")
        parts.extend(f"  - {c}" for c in criteria)

    parts.append(
        "\nRespond with exactly one line in this format:\n"
        "DECISION: <accept|send_back|suspend>\n"
        "REASONING: <brief explanation>\n\n"
        "Use 'send_back' if the agent should try again with a different approach.\n"
        "Use 'suspend' if the goal appears fundamentally blocked or needs external input.\n"
        "Use 'accept' if the goal appears completed satisfactorily."
    )
    return "\n".join(parts)


def _extract_reasoning(content: str) -> str:
    """Extract reasoning from LLM response.

    Args:
        content: LLM response text.

    Returns:
        Reasoning text.
    """
    for line in content.splitlines():
        if line.lower().startswith("reasoning:"):
            return line.split(":", 1)[1].strip()
    return content[:200]
