"""RFC-204: Consensus Loop for Layer 3 validation of StrangeLoop completions.

Layer 3 validates StrangeLoop's "done" judgment before accepting goal completion.
If not satisfied, Layer 3 can send the goal back with refined instructions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from soothe_nano.utils.text_preview import preview_first

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


ConsensusDecision = Literal["accept", "send_back", "suspend"]


class ConsensusVerdict(BaseModel):
    """Structured consensus outcome (RFC-630 — no free-text decision parsing)."""

    decision: ConsensusDecision = Field(
        description="accept if complete; send_back to retry; suspend if blocked"
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation for the decision",
    )


class ConsensusEvaluationError(RuntimeError):
    """Raised when consensus validation cannot run (missing model or LLM failure)."""


async def evaluate_goal_completion(
    goal_description: str,
    response_text: str,
    evidence_summary: str = "",
    model: BaseChatModel | None = None,
) -> tuple[ConsensusDecision, str]:
    """RFC-204: Holistic evaluation of goal completion via structured LLM.

    Args:
        goal_description: The original goal text.
        response_text: Agentic loop's response/output.
        evidence_summary: Accumulated evidence from execution.
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

    prompt = _build_consensus_prompt(goal_description, response_text, evidence_summary)
    try:
        from langchain_core.messages import HumanMessage
        from soothe_nano.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe_nano.utils.llm.observability import create_llm_call_metadata
        from soothe_nano.utils.llm.structured import invoke_structured_chat_typed

        invoke_config = {
            "metadata": create_llm_call_metadata(
                purpose="consensus_vote",
                component="cognition.consensus",
                phase="post-loop",
            )
        }

        async def _invoke() -> ConsensusVerdict:
            return await invoke_structured_chat_typed(
                model,
                [HumanMessage(content=prompt)],
                ConsensusVerdict,
                config=invoke_config,
            )

        verdict = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(None),
        )
        decision: ConsensusDecision = verdict.decision
        reasoning = (verdict.reasoning or "").strip() or f"Consensus decided {decision}"

        logger.info(
            "Consensus evaluation: decision=%s reasoning=%s",
            decision,
            preview_first(reasoning, 200),
        )
        return decision, reasoning
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
) -> str:
    """Build prompt for structured consensus evaluation.

    Pass full response/evidence into the judge prompt (IG-690). Do not clip
    with ``preview_first`` here — truncation caused false ``suspend`` when the
    model mistook the preview for incomplete work.

    Args:
        goal: Goal description.
        response: Layer 2 response text.
        evidence: Evidence summary.

    Returns:
        Prompt string for LLM evaluation.
    """
    parts = [
        "You are evaluating whether an AI agent has successfully completed a goal.",
        f"\nGoal: {goal}",
        f"\nAgent Response:\n{response}",
    ]
    if evidence:
        parts.append(f"\nEvidence Summary:\n{evidence}")

    parts.append(
        "\nChoose one decision:\n"
        "- accept: the goal appears completed satisfactorily\n"
        "- send_back: more verification detail is needed, or the agent should "
        "retry with a different approach\n"
        "- suspend: the goal appears fundamentally blocked or needs external input\n"
        "Do not choose suspend solely because the narrative is short when evidence "
        "lists commits, files, tool results, or workspace probe hits. Prefer "
        "send_back when more verification detail is needed.\n"
        "Provide a brief reasoning string."
    )
    return "\n".join(parts)
