"""RFC-204 §1.3 / IG-726: Report-commit judgment for Autopilot completions.

Autopilot validates StrangeLoop's "done" judgment from the **CE-committed goal
report** before accepting completion. If not satisfied, Autopilot send_backs
the goal with refined instructions, or fails it so host recovery (monitor /
LoopRail / engine health) can act — never parks for an operator mid-goal.

IG-725/IG-726: no ``evidence_follow_up`` / ``collect_evidence`` turns. Prefer
accepting StrangeLoop Plan-Execute-Eval completions; product send_back/fail
only. Optional bounded ``dag_ops`` may revise pending CE plan fields. Post-accept
DAG structure for rail phases remains LoopRail's job. The host judge never
opens the workspace (IG-710).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, NamedTuple

from pydantic import BaseModel, Field
from soothe_nano.utils.text_preview import preview_first

from soothe_autopilot.prompts import build_consensus_prompt
from soothe_autopilot.verify.dag_ops import DagOp

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


ConsensusDecision = Literal["accept", "send_back", "fail"]


class ConsensusVerdict(BaseModel):
    """Structured judgment outcome (RFC-630 — no free-text decision parsing)."""

    decision: ConsensusDecision = Field(
        description="accept if complete; send_back to retry; fail if blocked/unrecoverable"
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation; used as send_back rework brief",
    )
    dag_ops: list[DagOp] = Field(
        default_factory=list,
        description=(
            "Optional bounded CE DAG ops: wire_depends, unwire_depends, "
            "set_priority, update_pending_brief. Do not spawn/cancel unless "
            "explicitly allowed; prefer empty list."
        ),
    )


class ConsensusResult(NamedTuple):
    """Host-facing judgment outcome."""

    decision: ConsensusDecision
    reasoning: str
    dag_ops: tuple[DagOp, ...] = ()


class ConsensusEvaluationError(RuntimeError):
    """Raised when judgment cannot run (missing model or LLM failure)."""


async def evaluate_goal_completion(
    goal_description: str,
    response_text: str,
    model: BaseChatModel | None = None,
    *,
    dag_context: str = "",
) -> ConsensusResult:
    """RFC-204 §1.3 / IG-726: Holistic evaluation via structured LLM.

    Args:
        goal_description: The original goal text.
        response_text: CE GoalReport projection text.
        model: LLM for evaluation (required).
        dag_context: Optional compact CE DAG slice for bounded ops.

    Returns:
        ConsensusResult with decision, reasoning, and optional dag_ops.

    Raises:
        ConsensusEvaluationError: When ``model`` is missing or the LLM call fails.
    """
    if model is None:
        msg = "Consensus model is required for goal completion validation"
        raise ConsensusEvaluationError(msg)

    prompt = build_consensus_prompt(
        goal_description,
        response_text,
        dag_context=dag_context,
    )
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
        reasoning = (verdict.reasoning or "").strip() or f"Judgment decided {decision}"
        ops = tuple(verdict.dag_ops or ())

        logger.info(
            "Report-commit judgment: decision=%s dag_ops=%d reasoning=%s",
            decision,
            len(ops),
            preview_first(reasoning, 200),
        )
        return ConsensusResult(decision, reasoning, ops)
    except ConsensusEvaluationError:
        raise
    except Exception as exc:
        logger.exception("Report-commit LLM judgment failed")
        msg = f"Report-commit LLM judgment failed: {exc}"
        raise ConsensusEvaluationError(msg) from exc
