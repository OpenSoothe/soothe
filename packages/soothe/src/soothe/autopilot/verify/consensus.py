"""RFC-204 / IG-707: Consensus loop for Autopilot validation of StrangeLoop completions.

Autopilot validates StrangeLoop's "done" judgment before accepting goal completion.
If not satisfied, Autopilot send_backs the goal with refined instructions, or fails
it so host recovery (monitor / LoopRail / engine health) can act — never parks for
an operator mid-goal.

IG-724: when ``send_back`` is primarily a missing workspace/git/file proof gap,
``evidence_follow_up`` requests a StrangeLoop ``collect_evidence`` turn instead of
immediate product rework. The host judge never opens the workspace.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, NamedTuple

from pydantic import BaseModel, Field
from soothe_nano.utils.text_preview import preview_first

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


ConsensusDecision = Literal["accept", "send_back", "fail"]


class ConsensusVerdict(BaseModel):
    """Structured consensus outcome (RFC-630 — no free-text decision parsing)."""

    decision: ConsensusDecision = Field(
        description="accept if complete; send_back to retry; fail if blocked/unrecoverable"
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation for the decision",
    )
    evidence_follow_up: bool = Field(
        default=False,
        description=(
            "When decision is send_back: true if the gap is missing "
            "workspace/git/file proof that tools could gather; false for "
            "product rework / wrong approach. Ignored for accept/fail."
        ),
    )


class ConsensusResult(NamedTuple):
    """Host-facing consensus outcome (IG-724)."""

    decision: ConsensusDecision
    reasoning: str
    evidence_follow_up: bool = False


class ConsensusEvaluationError(RuntimeError):
    """Raised when consensus validation cannot run (missing model or LLM failure)."""


async def evaluate_goal_completion(
    goal_description: str,
    response_text: str,
    evidence_summary: str = "",
    model: BaseChatModel | None = None,
) -> ConsensusResult:
    """RFC-204 / IG-707 / IG-724: Holistic evaluation of goal completion via structured LLM.

    Args:
        goal_description: The original goal text.
        response_text: Agentic loop's response/output.
        evidence_summary: Accumulated evidence from execution.
        model: LLM for evaluation (required).

    Returns:
        ConsensusResult with decision, reasoning, and evidence_follow_up.

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
        evidence_follow_up = bool(verdict.evidence_follow_up) and decision == "send_back"

        logger.info(
            "Consensus evaluation: decision=%s evidence_follow_up=%s reasoning=%s",
            decision,
            evidence_follow_up,
            preview_first(reasoning, 200),
        )
        return ConsensusResult(decision, reasoning, evidence_follow_up)
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
    with ``preview_first`` here — truncation caused false ``fail`` when the
    model mistook the preview for incomplete work.

    Args:
        goal: Goal description.
        response: StrangeLoop response text.
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
        "- fail: the goal appears fundamentally blocked or unrecoverable by "
        "further agent retries (host recovery will decide next steps)\n"
        "Judge from the Goal and Agent Response (StrangeLoop Plan-Execute-Eval "
        "output). Prefer send_back when the response is thin relative to the "
        "goal; do not choose fail solely because the narrative is short.\n"
        "When decision is send_back, set evidence_follow_up=true if the main "
        "gap is missing workspace proof (branch name, git commits, completion "
        "report, file paths) that a short tool-using gather pass could supply; "
        "set evidence_follow_up=false when the approach itself must be reworked "
        "or product code is clearly incomplete/wrong.\n"
        "Provide a brief reasoning string."
    )
    return "\n".join(parts)
