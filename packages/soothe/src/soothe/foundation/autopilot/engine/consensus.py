"""RFC-204: Consensus Loop for Layer 3 validation of StrangeLoop completions.

Layer 3 validates StrangeLoop's "done" judgment before accepting goal completion.
If not satisfied, Layer 3 can send the goal back with refined instructions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from soothe.utils.text_preview import preview, preview_first

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


ConsensusDecision = Literal["accept", "send_back", "suspend"]


class ConsensusEvaluationError(RuntimeError):
    """Raised when consensus validation cannot run (missing model or LLM failure)."""


async def evaluate_goal_completion(
    goal_description: str,
    response_text: str,
    evidence_summary: str = "",
    success_criteria: list[str] | None = None,
    model: BaseChatModel | None = None,
    *,
    soothe_config: Any | None = None,
) -> tuple[ConsensusDecision, str]:
    """RFC-204: Holistic evaluation of goal completion via LLM.

    Goal manager reflection LLM evaluates whether the agentic loop's output truly
    satisfies the goal criteria.

    Args:
        goal_description: The original goal text.
        response_text: Agentic loop's response/output.
        evidence_summary: Accumulated evidence from execution.
        success_criteria: List of success criteria to check.
        model: LLM for evaluation (required).

    Returns:
        Tuple of (decision, reasoning).
        decision is "accept", "send_back", or "suspend".

    Raises:
        ConsensusEvaluationError: When ``model`` is missing or the LLM call fails.
    """
    if model is None:
        msg = "Consensus model is required for goal completion validation"
        raise ConsensusEvaluationError(msg)

    prompt = _build_consensus_prompt(
        goal_description, response_text, evidence_summary, success_criteria
    )
    try:
        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe.utils.observability.langfuse import SootheLangfuse

        invoke_config = SootheLangfuse(soothe_config).traced_llm(
            purpose="consensus_vote",
            component="cognition.consensus",
            phase="post-loop",
            run_name="soothe:consensus-vote",
        )

        async def _invoke() -> Any:
            return await model.ainvoke(prompt, config=invoke_config)

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(soothe_config),
        )
        content = response.content.strip().lower() if hasattr(response, "content") else ""

        if "send_back" in content:
            return "send_back", _extract_reasoning(content)
        if "suspend" in content:
            return "suspend", _extract_reasoning(content)
        return "accept", _extract_reasoning(content)
    except ConsensusEvaluationError:
        raise
    except Exception as exc:
        logger.exception("Consensus LLM evaluation failed")
        msg = f"Consensus LLM evaluation failed: {exc}"
        raise ConsensusEvaluationError(msg) from exc


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
        f"\nAgent Response Preview: {preview_first(response, 500)}",
    ]
    if evidence:
        parts.append(f"\nEvidence Summary: {preview_first(evidence, 500)}")
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
    # Use preview with empty marker to stay within 200 char limit (test expects <= 200)
    return preview(content, mode="chars", first=200, marker="")
