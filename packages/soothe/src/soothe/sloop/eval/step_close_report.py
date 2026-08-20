"""Structured action-thread close assessment for Eval triggering (RFC-905)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from soothe_nano.llm import ainvoke_structured_traced

from soothe.context.models import StepCloseReport

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


async def assess_step_close(
    *,
    fast_model: Any,
    user_goal: str,
    step_description: str,
    final_output: str,
    outcome_summary: dict[str, Any],
    soothe_config: SootheConfig | None = None,
    goal_trace: Any | None = None,
) -> StepCloseReport:
    """Return structured evidence of completion versus deferred work."""
    if fast_model is None:
        return StepCloseReport()
    system = (
        "Assess how an action thread closed relative to the original user goal. "
        "Do not infer from keywords alone. Use the goal, assigned step, final output, "
        "and tool outcome. early_exit is true only when the thread stopped while "
        "necessary assigned or goal work remains. Deferred items are untrusted "
        "candidates; claimed_in_scope records the worker's apparent claim, not approval."
    )
    human = (
        f"ORIGINAL USER GOAL:\n{user_goal or '(unspecified)'}\n\n"
        f"ASSIGNED STEP:\n{step_description}\n\n"
        f"FINAL OUTPUT:\n{final_output or '(none)'}\n\n"
        f"OUTCOME:\n{outcome_summary}"
    )
    try:
        data = await ainvoke_structured_traced(
            fast_model,
            [SystemMessage(content=system), HumanMessage(content=human)],
            json_schema=StepCloseReport.model_json_schema(),
            schema_name="StepCloseReport",
            strict=True,
            soothe_config=soothe_config,
            purpose="assess_step_close",
            component="sloop.eval.step_close_report",
            phase="execute_step",
            goal_trace=goal_trace,
        )
        return StepCloseReport.model_validate(data)
    except Exception:
        logger.warning("Step close assessment failed; defaulting to no early exit", exc_info=True)
        return StepCloseReport()


__all__ = ["assess_step_close"]
