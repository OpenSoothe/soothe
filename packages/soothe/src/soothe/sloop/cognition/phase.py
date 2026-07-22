"""Plan phase orchestration for StrangeLoop Plan-and-Execute execution (RFC-201)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_nano.utils.text_preview import log_preview

from soothe.sloop.state.schemas import LoopState, PlanResult, StatusAssessment
from soothe.sloop.utils.plan_action_text import resolve_plan_action_text

# Maximum evidence summary length before truncating model-supplied evidence
_EVIDENCE_SUMMARY_MAX_CHARS = 600

if TYPE_CHECKING:
    from soothe_sdk.protocols.planner import PlanContext

    from soothe.protocols.loop_planner import LoopPlannerProtocol

logger = logging.getLogger(__name__)


class PlanPhase:
    """Runs the Plan step via ``LoopPlannerProtocol`` (RFC-604: one or two LLM calls)."""

    def __init__(self, loop_planner: LoopPlannerProtocol) -> None:
        """Initialize with a `LoopPlannerProtocol` implementation."""
        self._loop_planner = loop_planner

    def _prepare_state_evidence(self, state: LoopState) -> None:
        """Refresh compact state evidence from step results."""
        evidence_lines = [result.to_evidence_string() for result in state.step_results]
        state.evidence_summary = "\n".join(evidence_lines)

    @staticmethod
    def _log_plan_pre_llm(goal: str, state: LoopState, context: PlanContext) -> None:
        """Emit compact pre-LLM snapshot for observability."""
        pre_llm = {
            "iter": state.iteration,
            "goal": log_preview(goal, 60),
            "steps": {
                "total": len(state.step_results),
                "done": len(state.dependency_completion_ids()),
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
        logger.debug("Plan pre-LLM: %s", pre_llm)

    def finalize_plan_result(
        self,
        *,
        state: LoopState,
        context: PlanContext,
        result: PlanResult,
    ) -> PlanResult:
        """Apply shared post-processing and action-history tracking."""
        if not result.evidence_summary and state.evidence_summary:
            result = result.model_copy(update={"evidence_summary": state.evidence_summary})

        _ev = (result.evidence_summary or "").strip()
        _compact = (state.evidence_summary or "").strip()
        if len(_ev) > _EVIDENCE_SUMMARY_MAX_CHARS:
            result = result.model_copy(
                update={"evidence_summary": _compact or f"{_ev[:400].rstrip()}…"},
            )

        # full_output is now populated by goal_completion from the ledger,
        # so we don't concatenate raw evidence strings here.

        state.add_action_to_history(resolve_plan_action_text(result))

        successes = sum(1 for r in state.step_results if r.success)
        failures = sum(1 for r in state.step_results if not r.success)
        logger.info(
            "[Plan] iter=%d done: status=%s progress=%s plan=%s (steps=%d ok=%d fail=%d)",
            state.iteration,
            result.status,
            result.goal_progress,
            result.plan_action,
            len(state.step_results),
            successes,
            failures,
        )
        return result

    async def assess_status(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        context_engine: Any | None = None,
        plan_gap: Any | None = None,
    ) -> StatusAssessment:
        """Run assess-only planner call for the current iteration."""
        self._prepare_state_evidence(state)
        self._log_plan_pre_llm(goal, state, context)
        logger.info(
            "[Plan] iter=%d calling assess (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )
        return await self._loop_planner.assess_status(
            goal=goal,
            state=state,
            context=context,
            context_engine=context_engine,
            plan_gap=plan_gap,
        )

    async def analyze_plan_gap(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        context_engine: Any | None = None,
    ) -> Any:
        """Run read-only gap analysis before assess on mid-goal paths."""
        self._prepare_state_evidence(state)
        logger.info(
            "[Plan] iter=%d calling gap analysis (results=%d)",
            state.iteration,
            len(state.step_results),
        )
        return await self._loop_planner.analyze_plan_gap(
            goal=goal,
            state=state,
            context=context,
            context_engine=context_engine,
        )

    async def generate_from_assessment(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: StatusAssessment,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        plan_gap: Any | None = None,
    ) -> PlanResult:
        """Run plan-generate call after assess determined work remains."""
        self._prepare_state_evidence(state)
        logger.info(
            "[Plan] iter=%d calling generate (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )
        result = await self._loop_planner.generate_from_assessment(
            goal=goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=context_engine,
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
            plan_gap=plan_gap,
        )
        return self.finalize_plan_result(state=state, context=context, result=result)

    async def generate_lightweight(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: StatusAssessment,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        plan_gap: Any | None = None,
    ) -> PlanResult:
        """Run a cheaper plan-generate call for the ``simple`` intake branch (RFC-630).

        Same ``PlanGeneration`` schema as ``generate_from_assessment``, but the
        planner reduces the context window (fewer history slots, no full
        evidence ledger). Falls back to ``generate_from_assessment`` when the
        planner does not implement the lightweight path.
        """
        self._prepare_state_evidence(state)
        logger.info(
            "[Plan] iter=%d calling lightweight generate (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )
        lightweight = getattr(self._loop_planner, "generate_lightweight", None)
        if lightweight is None:
            # Planner does not implement a lightweight path; use the full path.
            return await self.generate_from_assessment(
                goal=goal,
                state=state,
                context=context,
                assessment=assessment,
                plan_manager=plan_manager,
                context_engine=context_engine,
                checkpoint=checkpoint,
                exclude_goal_id=exclude_goal_id,
                plan_gap=plan_gap,
            )
        result = await lightweight(
            goal=goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=context_engine,
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
            plan_gap=plan_gap,
        )
        return self.finalize_plan_result(state=state, context=context, result=result)

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        """Single-call plan via the loop planner (RFC-604)."""
        self._prepare_state_evidence(state)
        self._log_plan_pre_llm(goal, state, context)
        logger.info(
            "[Plan] iter=%d calling one-shot plan (history=%d, results=%d)",
            state.iteration,
            len(state.action_history),
            len(state.step_results),
        )
        result = await self._loop_planner.plan(
            goal=goal, state=state, context=context, plan_manager=plan_manager
        )
        return self.finalize_plan_result(state=state, context=context, result=result)
