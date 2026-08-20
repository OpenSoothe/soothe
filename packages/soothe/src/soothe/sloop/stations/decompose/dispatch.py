"""DISPATCH station: claim CE ready steps into an execute decision (RFC-904)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.context.models import StepNode
from soothe.sloop.orchestrator.node_base import (
    LoopNode,
    NodeResult,
    RouteDecision,
    _maybe_await,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import DISPATCH
from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    allocate_plan_id,
)
from soothe.sloop.utils.config_keys import positive_config_int
from soothe.sloop.utils.goal_text import resolve_user_request

logger = logging.getLogger(__name__)


def _intent_field(ctx: LoopRuntimeContext, name: str) -> str:
    """Read a wire-safe string from the classified intent, or empty."""
    raw = getattr(getattr(ctx.loop_state, "intent", None), name, None)
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _decompose_cfg(ctx: LoopRuntimeContext) -> Any:
    return getattr(ctx.strange_loop.config.agent.loop, "decompose", None)


def _step_action_from_node(node: StepNode) -> StepAction:
    hint = node.execution_hint if node.execution_hint is not None else "auto"
    kind = node.kind if node.kind in ("action", "ask_user", "eval") else "action"
    title = (node.description or "").strip() or node.id
    full = (node.full_description or node.description or "").strip() or node.id
    return StepAction(
        id=node.id,
        description=title,
        full_description=full,
        expected_output=node.expected_output or "Step completed successfully",
        dependencies=list(node.dependencies) or None,
        execution_hint=hint,
        kind=kind,  # type: ignore[arg-type]
        is_dag_root=node.parent_step_id is None,
    )


async def _ensure_root_step(ctx: LoopRuntimeContext) -> str | None:
    """Create a root StepNode when the goal StepDAG is empty. Returns root id."""
    ce = ctx.ce
    goal_id = ctx.ce_goal_id
    if ce is None or not goal_id:
        return None
    goal = await _maybe_await(ce.get_goal(goal_id))
    if goal is None:
        return None
    root_id: str | None = None
    if goal.steps.nodes:
        # Prefer an existing root (no parent).
        for node in goal.steps.nodes.values():
            if node.parent_step_id is None and node.status not in (
                "superseded",
                "skipped",
            ):
                root_id = node.id
                break
        if root_id is None:
            root_id = next(iter(goal.steps.nodes))
    else:
        goal_text = resolve_user_request(ctx.loop_state) or ctx.loop_state.goal or "Execute task"
        intent = getattr(ctx.loop_state, "intent", None)
        short_title = (getattr(intent, "task_short_description", None) or "").strip()
        plan_id = allocate_plan_id()
        root_id = f"{plan_id}-01"
        root = StepNode(
            id=root_id,
            description=short_title or goal_text,
            full_description=goal_text,
            status="pending",
            parent_step_id=None,
            plan_iteration=0,
        )
        await _maybe_await(ce.add_step(goal_id, root))
        logger.info("[dispatch] created root step %s for goal %s", root_id, goal_id)

    await _ground_root_with_approved_plan(ctx, root_id)
    return root_id


async def _ground_root_with_approved_plan(ctx: LoopRuntimeContext, root_id: str) -> None:
    """Stamp operator-approved intake plan onto the root THREAD description (RFC-904)."""
    from soothe.sloop.plans.grounding import (
        compose_root_full_description,
        consume_approved_plan_from_state,
        peek_approved_plan_from_state,
        root_already_grounded,
    )

    body, path = peek_approved_plan_from_state(ctx.loop_state)
    if not body:
        return
    ce = ctx.ce
    goal_id = ctx.ce_goal_id
    if ce is None or not goal_id:
        return
    goal = await _maybe_await(ce.get_goal(goal_id))
    if goal is None:
        return
    node = goal.steps.nodes.get(root_id)
    if node is None:
        return
    if root_already_grounded(node.full_description):
        consume_approved_plan_from_state(ctx.loop_state)
        return

    goal_text = (
        (node.description or "").strip()
        or resolve_user_request(ctx.loop_state)
        or ctx.loop_state.goal
        or "Execute task"
    )
    node.full_description = compose_root_full_description(
        goal_text,
        approved_plan_markdown=body,
        approved_plan_path=path,
    )
    consume_approved_plan_from_state(ctx.loop_state)
    logger.info(
        "[dispatch] grounded root %s with approved plan (%d chars%s)",
        root_id,
        len(body),
        f", path={path}" if path else "",
    )


class DispatchNode(LoopNode):
    """Claim ready StepDAG nodes and stage them for THREAD (execute)."""

    station = DISPATCH
    call_kind = None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        from soothe.sloop.stations.execute.loop_budget import enforce_loop_budget

        terminal = await enforce_loop_budget(ctx)
        if terminal is not None:
            return NodeResult(payload={"dispatch_route": "fatal", "budget_terminal": terminal})

        # Grace budget applies once; subsequent DISPATCH waves re-check hard.
        if getattr(ctx, "recovery_valid_resume", False):
            ctx.recovery_valid_resume = False

        cfg = _decompose_cfg(ctx)
        max_waves = positive_config_int(getattr(cfg, "max_waves", 10) if cfg else 10, 10)
        wave = positive_config_int(getattr(ctx.loop_state, "iteration", 0), 0, minimum=0)
        waves_exhausted = wave >= max_waves

        await _ensure_root_step(ctx)

        ce = ctx.ce
        goal_id = ctx.ce_goal_id
        if ce is None or not goal_id:
            if waves_exhausted:
                return NodeResult(payload={"dispatch_route": "root_eval", "max_waves": True})
            # No CE: single-step fallback from goal text (tests / degraded).
            goal_text = (
                resolve_user_request(ctx.loop_state) or ctx.loop_state.goal or "Execute task"
            )
            intent = getattr(ctx.loop_state, "intent", None)
            short_title = (getattr(intent, "task_short_description", None) or "").strip()
            plan_id = allocate_plan_id()
            step = StepAction(
                id=f"{plan_id}-01",
                description=short_title or goal_text,
                full_description=goal_text,
                is_dag_root=True,
            )
            decision = AgentDecision(
                type="execute_steps",
                execution_mode="parallel",
                reasoning="Decompose dispatch fallback (no CE)",
                steps=[step],
            )
            plan_result = PlanResult(
                status="continue",
                goal_progress="none",
                assessment_reasoning="",
                plan_action="new",
                require_goal_completion=False,
                terminal_after_execute=True,
                decision=decision,
                next_action=goal_text[:300],
            )
            ctx.scratch.decision = decision
            ctx.scratch.plan_result = plan_result
            ctx.loop_state.current_decision = decision
            ctx.loop_state.plan_id = plan_id
            return NodeResult(payload={"dispatch_route": "execute", "claimed": [step.id]})

        goal = await _maybe_await(ce.get_goal(goal_id))
        if goal is None:
            return NodeResult(payload={"dispatch_route": "fatal"})

        ready = sorted(goal.steps.ready_steps())
        if waves_exhausted:
            ready = [
                sid for sid in ready if getattr(goal.steps.nodes.get(sid), "kind", None) == "eval"
            ]
            if not ready:
                logger.warning(
                    "[dispatch] max_waves=%d reached; routing to root_eval",
                    max_waves,
                )
                return NodeResult(payload={"dispatch_route": "root_eval", "max_waves": True})

        if not ready:
            if goal.steps.tree_green():
                return NodeResult(payload={"dispatch_route": "root_eval"})
            # Active steps still running should not happen in sync graph; treat as idle.
            pending_or_active = [
                n.id
                for n in goal.steps.nodes.values()
                if n.status in ("pending", "active", "decomposed")
            ]
            if any(goal.steps.nodes[s].status == "active" for s in goal.steps.nodes):
                logger.warning("[dispatch] no ready steps but active remain; root_eval")
            if not pending_or_active or goal.steps.tree_green():
                return NodeResult(payload={"dispatch_route": "root_eval"})
            logger.info("[dispatch] no claimable ready steps; root_eval")
            return NodeResult(payload={"dispatch_route": "root_eval"})

        claimed: list[StepAction] = []
        for sid in ready:
            await _maybe_await(ce.activate_step(goal_id, sid))
            node = goal.steps.nodes[sid]
            claimed.append(_step_action_from_node(node))

        decision = AgentDecision(
            type="execute_steps",
            execution_mode="parallel",
            reasoning="Decompose DISPATCH claim set",
            steps=claimed,
        )
        # Merge into loop decision history for dependency completion across waves.
        prior = ctx.loop_state.current_decision
        if prior is not None and prior.steps:
            known = {s.id for s in prior.steps}
            merged_steps = list(prior.steps)
            for s in claimed:
                if s.id not in known:
                    merged_steps.append(s)
            decision = decision.model_copy(update={"steps": merged_steps})

        plan_result = PlanResult(
            status="continue",
            goal_progress="none",
            assessment_reasoning="",
            plan_action="new" if prior is None else "keep",
            require_goal_completion=False,
            terminal_after_execute=False,
            decision=decision,
            next_action=(claimed[0].description[:300] if claimed else ""),
        )
        ctx.scratch.decision = decision
        ctx.scratch.plan_result = plan_result
        ctx.loop_state.current_decision = decision
        if ctx.loop_state.plan_id is None and claimed:
            # Prefer plan prefix from first claimed id.
            rid = claimed[0].id
            if "-" in rid:
                ctx.loop_state.plan_id = rid.split("-", 1)[0]

        logger.info(
            "[dispatch] claimed %d step(s) for goal %s: %s",
            len(claimed),
            goal_id,
            [s.id for s in claimed],
        )
        return NodeResult(
            payload={"dispatch_route": "execute", "claimed": [s.id for s in claimed]},
            events=[
                (
                    "plan_decision",
                    {
                        "iteration": ctx.loop_state.iteration,
                        "steps": [
                            {
                                "id": s.id,
                                "description": (s.description or "").strip().replace("\n", " "),
                                **(
                                    {"dependencies": list(s.dependencies)} if s.dependencies else {}
                                ),
                            }
                            for s in claimed
                        ],
                        "execution_mode": "parallel",
                        "intake_label": _intent_field(ctx, "intake_label"),
                        "task_complexity": _intent_field(ctx, "task_complexity"),
                        "total_steps": len(decision.steps),
                        "done_steps": len(ctx.loop_state.step_results),
                    },
                )
            ],
        )

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        payload = result.payload if isinstance(result.payload, dict) else {}
        if payload.get("budget_terminal"):
            return RouteDecision(
                kind="terminal",
                state_patch={
                    "dispatch_route": "fatal",
                    "last_outcome": str(payload["budget_terminal"]),
                },
            )
        route = str(payload.get("dispatch_route") or "execute")
        patch: dict[str, Any] = {"dispatch_route": route}
        # One-shot Approve handoff ends on first DISPATCH (cleared even if no body).
        if getattr(ctx.scratch, "planner_implement_handoff", False):
            ctx.scratch.planner_implement_handoff = False
            patch["planner_implement_handoff"] = False
        return RouteDecision(kind="proceed", state_patch=patch)


node = DispatchNode()
