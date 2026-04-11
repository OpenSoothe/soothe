"""Reason phase for AgentLoop ReAct execution (RFC-201)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.schemas import LoopState, ReasonResult
from soothe.utils.text_preview import log_preview

# Maximum evidence summary length before truncating model-supplied evidence
_EVIDENCE_SUMMARY_MAX_CHARS = 600

if TYPE_CHECKING:
    from soothe.protocols.loop_reasoner import LoopReasonerProtocol
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)


class ReasonPhase:
    """Single LLM call: assess progress and produce the next plan fragment."""

    def __init__(self, loop_reasoner: LoopReasonerProtocol) -> None:
        """Initialize with a ``LoopReasonerProtocol`` implementation."""
        self._loop_reasoner = loop_reasoner

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> ReasonResult:
        """Run Reason and enrich result with evidence and final output when done."""
        evidence_lines = [result.to_evidence_string() for result in state.step_results]
        state.evidence_summary = "\n".join(evidence_lines)

        # --- Debug: compact pre-LLM snapshot in dict format ---
        pre_llm = {
            "iter": state.iteration,
            "goal": log_preview(goal, 60),
            "steps": {
                "total": len(state.step_results),
                "done": len(state.completed_step_ids),
            },
            "wave": {
                "calls": state.last_wave_tool_call_count,
                "sub": state.last_wave_subagent_task_count,
                "cap": state.last_wave_hit_subagent_cap,
                "out": state.last_wave_output_length,
                "err": state.last_wave_error_count,
            },
            "ctx": {
                "caps": len(context.available_capabilities),
                "msgs": len(context.recent_messages),
                "done": len(context.completed_steps),
            },
        }
        if context.available_capabilities:
            pre_llm["caps"] = context.available_capabilities[:5]
        if context.completed_steps:
            pre_llm["done_steps"] = [s.step_id for s in context.completed_steps[:5]]
        if state.action_history:
            pre_llm["actions"] = state.get_recent_actions(3)
        logger.debug("[Reason] pre-LLM: %s", pre_llm)

        logger.info(
            "[Reason] iter=%d calling LLM (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )

        result = await self._loop_reasoner.reason(goal=goal, state=state, context=context)
        if not result.evidence_summary and state.evidence_summary:
            result = result.model_copy(update={"evidence_summary": state.evidence_summary})

        # Model-supplied evidence can repeat the full assistant answer; that duplicates streamed
        # output and blows the loop.completed one-liner. Prefer compact step-derived evidence.
        _ev = (result.evidence_summary or "").strip()
        _compact = (state.evidence_summary or "").strip()
        if len(_ev) > _EVIDENCE_SUMMARY_MAX_CHARS:
            result = result.model_copy(
                update={"evidence_summary": _compact or f"{_ev[:400].rstrip()}…"},
            )

        if result.is_done():
            full_outputs = [r.to_evidence_string(truncate=False) for r in state.step_results if r.success]
            if full_outputs:
                result = result.model_copy(
                    update={"full_output": "\n\n".join(full_outputs)},
                )

        # Track action in history (full reasoning chain for progression detection)
        state.add_action_to_history(result.next_action or "")

        successes = sum(1 for r in state.step_results if r.success)
        failures = sum(1 for r in state.step_results if not r.success)
        logger.info(
            "[Reason] iter=%d done: status=%s progress=%.0f%% plan=%s (steps=%d ok=%d fail=%d)",
            state.iteration,
            result.status,
            result.goal_progress * 100,
            result.plan_action,
            len(state.step_results),
            successes,
            failures,
        )

        return result
