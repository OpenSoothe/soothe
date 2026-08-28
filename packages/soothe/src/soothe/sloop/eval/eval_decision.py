"""LLM-structured decision on whether a coverage Eval step is needed.

For SIMPLE tasks where the structural ``eval_required()`` predicate returns
False, a fast-model call decides whether the execution evidence still warrants
a coverage audit. MINIMAL tasks short-circuit (never call the LLM). COMPLEX
tasks rely on the structural predicate (always insert Eval when required).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from soothe_nano.llm import ainvoke_structured_traced

from soothe.context.models import StepNode
from soothe.sloop.intention.models import IntakeLabel

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.utils.observability.langfuse import GoalLoopTrace

logger = logging.getLogger(__name__)


class EvalDecision(BaseModel):
    """LLM structured decision on whether a coverage Eval step is needed."""

    should_run_eval: bool = Field(
        description=(
            "True if a coverage Eval step should run to audit whether the "
            "original user goal was achieved completely."
        )
    )
    reasoning: str = Field(
        description="Brief first-person reasoning (I'll … / Let me …).",
    )


def _fail_safe_decision(reason: str = "eval decision unavailable") -> EvalDecision:
    """Fail-safe: when the LLM call fails, require Eval (never skip silently)."""
    return EvalDecision(should_run_eval=True, reasoning=reason)


def _step_history_table(nodes: list[StepNode]) -> str:
    """Render a compact step history table for the decision prompt."""
    rows: list[str] = []
    for node in nodes:
        close = node.close_report.model_dump() if node.close_report is not None else None
        outcome = node.execution.outcome if node.execution is not None else None
        rows.append(
            f"- {node.id} kind={node.kind} status={node.status}: {node.description}\n"
            f"  expected={node.expected_output or '(unspecified)'}\n"
            f"  close_report={close or '(none)'}\n"
            f"  outcome={outcome or '(none)'}"
        )
    return "\n".join(rows)


async def decide_eval_required(
    *,
    fast_model: Any,
    user_goal: str,
    step_history: list[StepNode],
    intake_label: IntakeLabel,
    soothe_config: SootheConfig | None = None,
    goal_trace: GoalLoopTrace | None = None,
) -> EvalDecision:
    """Return an LLM decision on whether a coverage Eval step should run.

    MINIMAL tasks short-circuit to ``should_run_eval=False`` without calling
    the LLM. When ``fast_model`` is None or the call fails, fail-safe to
    ``should_run_eval=True`` (run Eval rather than silently skip).

    Args:
        fast_model: Resolved fast chat model (or None → fail-safe).
        user_goal: Original user goal text.
        step_history: All StepNodes in the goal DAG (for the prompt envelope).
        intake_label: 4-class intake label from intent classification.
        soothe_config: Optional config for tracing.
        goal_trace: Optional Langfuse goal trace.

    Returns:
        EvalDecision with ``should_run_eval`` and ``reasoning``.
    """
    # MINIMAL never needs Eval — skip the LLM call entirely.
    if intake_label == IntakeLabel.MINIMAL:
        return EvalDecision(
            should_run_eval=False,
            reasoning="Minimal task; no coverage audit needed.",
        )

    if fast_model is None:
        return _fail_safe_decision("No fast model available; requiring Eval")

    from soothe.prompts import EVAL_DECISION_SYSTEM

    system = EVAL_DECISION_SYSTEM
    human = (
        f"ORIGINAL USER GOAL:\n{user_goal or '(unspecified)'}\n\n"
        f"TASK COMPLEXITY: {intake_label.value}\n\n"
        f"INTRA-GOAL STEP HISTORY:\n{_step_history_table(step_history)}"
    )
    try:
        data = await ainvoke_structured_traced(
            fast_model,
            [SystemMessage(content=system), HumanMessage(content=human)],
            json_schema=EvalDecision.model_json_schema(),
            schema_name="EvalDecision",
            strict=True,
            soothe_config=soothe_config,
            purpose="decide_eval_required",
            component="sloop.eval.eval_decision",
            phase="root_eval",
            goal_trace=goal_trace,
        )
        return EvalDecision.model_validate(data)
    except Exception:
        logger.warning(
            "Eval decision LLM call failed; requiring Eval (fail-safe)",
            exc_info=True,
        )
        return _fail_safe_decision("LLM call failed; requiring Eval")


__all__ = ["EvalDecision", "decide_eval_required"]
