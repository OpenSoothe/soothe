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

from soothe.autopilot.verify.dag_ops import DagOp

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
    evidence_summary: str = "",
    model: BaseChatModel | None = None,
    *,
    dag_context: str = "",
) -> ConsensusResult:
    """RFC-204 §1.3 / IG-726: Holistic evaluation via structured LLM.

    Args:
        goal_description: The original goal text.
        response_text: CE GoalReport projection text.
        evidence_summary: Extra report context (usually empty).
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

    prompt = _build_consensus_prompt(
        goal_description,
        response_text,
        evidence_summary,
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


def _build_consensus_prompt(
    goal: str,
    response: str,
    evidence: str,
    *,
    dag_context: str = "",
) -> str:
    """Build prompt for structured report-commit judgment.

    Pass full response/evidence into the judge prompt (IG-690). Do not clip
    with ``preview_first`` here — truncation caused false ``fail`` when the
    model mistook the preview for incomplete work.
    """
    parts = [
        "You are evaluating whether an AI agent has successfully completed a goal.",
        f"\nGoal: {goal}",
        f"\nGoal Report (from ContextEngine):\n{response}",
    ]
    if evidence:
        parts.append(f"\nAdditional report context:\n{evidence}")
    if dag_context.strip():
        parts.append(f"\n{dag_context.strip()}")

    parts.append(
        "\nChoose one decision:\n"
        "- accept: StrangeLoop Plan-Execute-Eval finished and the Goal Report "
        "indicates the goal work was done satisfactorily — prefer accept "
        "when the agent completed its plan unless product work is clearly "
        "incomplete or wrong\n"
        "- send_back: the approach or product deliverable must be reworked "
        "(not a request for more git/file proof narrative)\n"
        "- fail: the goal appears fundamentally blocked or unrecoverable by "
        "further agent retries (host recovery will decide next steps)\n"
        "Judge from the Goal and Goal Report only. Do not reject solely "
        "because the report omits branch names, git logs, or file-path "
        "lists — AutopilotMonitor and LoopRail own post-completion DAG "
        "structure, not a second proof mission. Prefer fail only when work "
        "is fundamentally blocked.\n"
        "Optionally propose bounded dag_ops (wire_depends, unwire_depends, "
        "set_priority, update_pending_brief on pending goals). Leave dag_ops "
        "empty unless a clear pending-plan fix is needed. Do not invent "
        "spawn_goal/cancel_goal. Provide a brief reasoning string."
    )
    return "\n".join(parts)
