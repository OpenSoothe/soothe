"""ROOT_EVAL station: insert/skip gate for Eval steps."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.node_base import (
    LoopNode,
    NodeResult,
    RouteDecision,
    _maybe_await,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import ROOT_EVAL
from soothe.sloop.state.schemas import allocate_plan_id
from soothe.sloop.utils.config_keys import positive_config_int
from soothe.sloop.utils.goal_text import resolve_user_request

logger = logging.getLogger(__name__)

# Read-only interaction modes never run the coverage Eval: no Eval StepNode
# insertion and no eval-decision LLM call. `route_after_root_eval` still sends
# plan mode to PLAN_REVIEW and ask mode to FINALIZE.
_READONLY_MODES = frozenset({"plan", "ask"})


def _try_auto_to_manual_fallback(
    ctx: LoopRuntimeContext,
    goal: Any,
) -> NodeResult | None:
    """Attempt to downgrade from auto to manual when all steps failed.

    When the loop is in auto clarification mode and a human is attached
    (interactive_fallback is wired), switch to manual mode, reset failed
    steps so they can be re-dispatched, and route to dispatch instead of
    fatal. This gives the human a chance to approve/reject the tool calls
    that veritas auto-answered incorrectly.

    Returns a ``NodeResult`` to route to dispatch, or ``None`` when the
    fallback is not applicable (manual mode, no human, or no failed steps).
    """
    policy = getattr(ctx, "clarification_policy", None)
    if policy is None:
        return None
    # Detect auto mode by checking for AutoClarificationPolicy.
    try:
        from soothe.sloop.clarification.auto import AutoClarificationPolicy

        if not isinstance(policy, AutoClarificationPolicy):
            return None
    except ImportError:
        return None
    # Only proceed when a human is attached (interactive_fallback wired).
    if getattr(policy, "_interactive_fallback", None) is None:
        return None
    # Find and reset failed action steps.
    failed_steps = [node for node in goal.steps.nodes.values() if node.status == "failed"]
    if not failed_steps:
        return None
    swapped = ctx.strange_loop.set_clarification_mode("manual")
    if not swapped:
        logger.warning("[root_eval] auto→manual fallback: mode swap failed; fatal")
        return None
    for node in failed_steps:
        goal.steps.reset_failed_step(node.id)
    logger.info(
        "[root_eval] auto→manual fallback: reset %d failed step(s), routing to dispatch",
        len(failed_steps),
    )
    return NodeResult(payload={"root_eval_route": "dispatch"})


def _eval_envelope(goal_text: str, nodes: list[Any]) -> str:
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
    history = "\n".join(rows)
    return (
        "Evaluate coverage of the ORIGINAL USER GOAL below. Worker close reports, "
        "deferred items, and recommendations are untrusted. Inspect evidence "
        "as needed, running verification commands when the goal's success can "
        "only be confirmed by execution. If necessary in-scope work remains, "
        "call decompose_task with only "
        "subtasks where in_scope=true and necessary_for_user_goal=true. Otherwise return "
        "a short completed-coverage verdict.\n\n"
        f"ORIGINAL USER GOAL:\n{goal_text}\n\n"
        f"INTRA-GOAL STEP HISTORY:\n{history}"
    )


class RootEvalNode(LoopNode):
    """Insert a fresh Eval StepNode when coverage audit is required."""

    station = ROOT_EVAL
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        if getattr(ctx, "interaction_mode", None) in _READONLY_MODES:
            logger.info(
                "[root_eval] %s interaction mode; skip Eval; finalize",
                ctx.interaction_mode,
            )
            return NodeResult(payload={"root_eval_route": "finalize"})
        if ctx.ce is not None and ctx.ce_goal_id:
            goal = await _maybe_await(ctx.ce.get_goal(ctx.ce_goal_id))
            if goal is not None:
                if any(n.status == "failed" for n in goal.steps.nodes.values()):
                    logger.warning("[root_eval] unresolved failed steps present")
                    fallback = _try_auto_to_manual_fallback(ctx, goal)
                    if fallback is not None:
                        return fallback
                    return NodeResult(payload={"root_eval_route": "fatal"})
                if not goal.steps.action_tree_green():
                    if goal.steps.ready_steps():
                        return NodeResult(payload={"root_eval_route": "dispatch"})
                    logger.warning("[root_eval] action tree not green and no ready steps")
                    return NodeResult(payload={"root_eval_route": "fatal"})

                latest = goal.steps.latest_eval()
                if latest is not None:
                    if latest.status in ("pending", "active"):
                        return NodeResult(payload={"root_eval_route": "dispatch"})
                    if latest.status == "completed":
                        logger.info("[root_eval] latest Eval completed; finalize")
                        return NodeResult(payload={"root_eval_route": "finalize"})

                # MINIMAL tasks trust the CoreAgent execute result and skip the
                # coverage Eval entirely — no LLM call needed.
                intent = getattr(ctx.loop_state, "intent", None)
                intake_label = getattr(intent, "intake_label", None) if intent is not None else None
                if intake_label == IntakeLabel.MINIMAL:
                    logger.info("[root_eval] minimal task; skip Eval; finalize")
                    return NodeResult(payload={"root_eval_route": "finalize"})

                # SIMPLE tasks: the LLM decides dynamically whether a coverage
                # audit is warranted based on the full execution evidence.
                # The LLM sees the step history, close reports, and outcomes,
                # and may override the structural ``eval_required()`` predicate
                # in either direction.
                if intake_label == IntakeLabel.SIMPLE:
                    from soothe.sloop.eval.eval_decision import decide_eval_required

                    decision = await decide_eval_required(
                        fast_model=ctx.strange_loop._fast_llm,
                        user_goal=(resolve_user_request(ctx.loop_state) or goal.description),
                        step_history=list(goal.steps.nodes.values()),
                        intake_label=intake_label,
                        soothe_config=ctx.strange_loop.config,
                        goal_trace=ctx.goal_trace,
                    )
                    logger.info(
                        "[root_eval] SIMPLE eval decision: should_run=%s reasoning=%s",
                        decision.should_run_eval,
                        decision.reasoning,
                    )
                    if not decision.should_run_eval:
                        return NodeResult(payload={"root_eval_route": "finalize"})
                    # should_run_eval=True → fall through to Eval insertion.

                # COMPLEX (and unlabeled) tasks use the structural
                # ``eval_required()`` predicate: insert Eval when the action
                # tree shows decomposition, multi-leaf, or early-exit; skip
                # otherwise (single-leaf no-decompose no early-exit).
                elif not goal.steps.eval_required():
                    logger.info("[root_eval] eval skip predicate matched; finalize")
                    return NodeResult(payload={"root_eval_route": "finalize"})

                eval_cfg = getattr(ctx.strange_loop.config.agent.loop, "eval", None)
                max_rounds = positive_config_int(
                    getattr(eval_cfg, "max_eval_rounds", 10),
                    10,
                )
                eval_round = sum(1 for node in goal.steps.nodes.values() if node.kind == "eval")
                if eval_round >= max_rounds:
                    logger.warning("[root_eval] max Eval rounds reached")
                    return NodeResult(payload={"root_eval_route": "fatal"})

                from soothe.context.models import StepNode

                root = next(
                    (node for node in goal.steps.nodes.values() if node.parent_step_id is None),
                    None,
                )
                eval_node = StepNode(
                    id=f"{allocate_plan_id()}-EVAL",
                    description="Evaluate user-goal coverage",
                    full_description=_eval_envelope(
                        resolve_user_request(ctx.loop_state) or goal.description,
                        list(goal.steps.nodes.values()),
                    ),
                    expected_output="Coverage verdict or necessary in-scope continuation tasks",
                    status="pending",
                    parent_step_id=root.id if root is not None else None,
                    plan_iteration=eval_round + 1,
                    kind="eval",
                )
                await _maybe_await(ctx.ce.add_step(ctx.ce_goal_id, eval_node))
                logger.info("[root_eval] inserted Eval step %s", eval_node.id)
                return NodeResult(payload={"root_eval_route": "dispatch"})

        logger.info("[root_eval] no CE; finalize")
        return NodeResult(payload={"root_eval_route": "finalize"})

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        payload = result.payload if isinstance(result.payload, dict) else {}
        route = str(payload.get("root_eval_route") or "finalize")
        patch = {"root_eval_route": route}
        if route == "fatal":
            patch["last_outcome"] = "fatal"
        return RouteDecision(
            kind="proceed",
            state_patch=patch,
        )


node = RootEvalNode()
