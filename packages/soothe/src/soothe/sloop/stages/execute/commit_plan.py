"""Resolve executable ``AgentDecision`` from ``PlanResult`` (RFC-220 pre-execute path).

Implemented as a ``LoopNode`` subclass (RFC-903). The missing-``plan_result``
guard is in ``pre`` via ``GuardOutcome``; the fallback-decision logic and
evidence-binding validation (folded from the former ``validate_plan`` node)
are in ``process``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.cognition.plan_dag_normalizer import normalize_plan_dag
from soothe.sloop.orchestrator.node_base import GuardOutcome, LoopNode, NodeResult, RouteDecision
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    allocate_plan_id,
    assign_plan_step_ids,
    prepare_decision_for_plan_scoping,
)

logger = logging.getLogger(__name__)


def validate_plan_evidence(
    config: Any,
    state: LoopState,
    decision: AgentDecision,
) -> bool:
    """Return True when plan evidence validation passes.

    Per-step ``evidence_refs`` were removed from ``StepAction``; this hook remains
    for orchestrator topology and future ledger rules. When
    ``loop_orchestrator_evidence_validate`` is enabled, validation is currently a no-op.

    Args:
        config: Runtime configuration (toggle).
        state: Loop state including ledger and prior step results.
        decision: Scoped decision about to execute.

    Returns:
        True if valid or validation disabled.
    """
    del state, decision  # reserved for future ledger checks
    if not getattr(config.agent.loop, "loop_orchestrator_evidence_validate", True):
        return True
    return True


def _scope_decision_for_plan(
    decision: AgentDecision,
    state: LoopState,
    *,
    reuse_plan_id: str | None,
) -> AgentDecision:
    """Normalize, generate, and scope step ids for a new or bootstrapped plan."""
    decision = prepare_decision_for_plan_scoping(decision, known_plan_ids=state.known_plan_ids())
    plan_id = reuse_plan_id or allocate_plan_id()
    state.plan_id = plan_id
    decision = assign_plan_step_ids(decision, plan_id=plan_id)
    return normalize_plan_dag(decision, completed_ids=state.dependency_completion_ids())


class CommitPlanNode(LoopNode):
    """Generate plan ids, merge keep/new semantics, stash decision on scratch.

    Non-LLM node (``call_kind is None``). Missing-``plan_result`` guard and
    no-decision fatal guard are in ``pre``; the fallback-decision logic
    (iter=0 with no step results) stays in ``process``; ``post`` emits the
    ``plan_decision`` event.
    """

    station = "commit_plan"
    call_kind = None

    async def pre(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> GuardOutcome | None:
        plan_result = ctx.scratch.plan_result
        if plan_result is None:
            logger.error("[resolve_decision] missing scratch.plan_result")
            await ctx.emit(
                "fatal_error",
                {"error": "Resolve decision without plan result", "step_id": ""},
            )
            return GuardOutcome(kind="fatal")
        return None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        strange_loop = ctx.strange_loop
        loop_state = ctx.loop_state
        plan_result = ctx.scratch.plan_result

        decision = strange_loop._resolve_decision(plan_result, loop_state)
        if decision is None:
            # Guard: create fallback decision when LLM returned type="final" at
            # iteration 0
            if loop_state.iteration == 0 and len(loop_state.step_results) == 0:
                logger.warning("[Guard] No decision at iter=0; creating fallback execute plan")
                decision = AgentDecision(
                    type="execute_steps",
                    steps=[
                        StepAction(
                            id="01",
                            description=loop_state.goal or "Execute task",
                        )
                    ],
                    execution_mode="parallel",
                    reasoning="Initial execution to gather evidence for goal assessment",
                )
            else:
                logger.error("[Reason] No executable decision after reason phase; aborting loop")
                return NodeResult(
                    payload=None,
                    events=[
                        (
                            "fatal_error",
                            {"error": "Reason phase returned no executable plan", "step_id": ""},
                        )
                    ],
                )

        if plan_result.plan_action == "new":
            decision = _scope_decision_for_plan(decision, loop_state, reuse_plan_id=None)
        elif plan_result.plan_action == "keep" and loop_state.current_decision is None:
            decision = _scope_decision_for_plan(
                decision, loop_state, reuse_plan_id=loop_state.plan_id
            )

        if plan_result.plan_action == "new":
            loop_state.current_decision = decision

        ctx.scratch.decision = decision
        merged = plan_result.model_copy(update={"decision": decision})
        ctx.scratch.plan_result = merged
        ctx.plan_manager.ingest_plan(merged, loop_state.plan_id, loop_state.iteration)

        # RFC-624 Phase 4: persist CE state after plan ingestion
        if ctx.ce is not None:
            try:
                ctx.ce.defer_save()
            except Exception:
                logger.warning("[resolve_decision] CE save failed", exc_info=True)

        # RFC-903 P3: folded validate_plan into commit_plan.process().
        # Deterministic evidence-binding validation — reject plans whose steps
        # lack valid evidence refs when the ledger is non-empty. Previously
        # this was a separate VALIDATE_PLAN node with two routers
        # (route_after_resolve_decision, route_after_validate_evidence).
        if not validate_plan_evidence(strange_loop.config, loop_state, decision):
            logger.error("[Plan] Evidence validation failed for planned steps")
            return NodeResult(
                payload=None,
                events=[
                    (
                        "fatal_error",
                        {"error": "Plan evidence validation failed", "step_id": ""},
                    )
                ],
            )

        # Calculate cumulative step counts for TUI display
        done_count = sum(1 for r in loop_state.step_results if r.success)
        total_count = len(loop_state.step_results) + len(decision.steps)

        intake_raw = getattr(getattr(loop_state, "intent", None), "intake_label", None)
        intake_label = str(getattr(intake_raw, "value", intake_raw) or "")

        plan_decision_event: tuple[str, dict[str, Any]] = (
            "plan_decision",
            {
                "iteration": loop_state.iteration,
                "steps": [
                    {
                        "id": s.id,
                        "description": (s.description or "").strip().replace("\n", " "),
                        **({"dependencies": list(s.dependencies)} if s.dependencies else {}),
                    }
                    for s in decision.steps
                ],
                "execution_mode": decision.execution_mode,
                "intake_label": intake_label,
                "total_steps": total_count,
                "done_steps": done_count,
            },
        )

        return NodeResult(payload=decision, events=[plan_decision_event])

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        # If process returned fatal_error events, payload is None.
        if result.payload is None:
            return RouteDecision(kind="fatal")
        return RouteDecision(kind="proceed")


# Singleton instance for the graph builder.
node: CommitPlanNode = CommitPlanNode()
