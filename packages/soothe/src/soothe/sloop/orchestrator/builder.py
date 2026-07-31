"""Compile the Strange Loop LangGraph (RFC-220, IG-663 stem stations).

The graph checkpoint key uses ``{loop_id}__strange_loop`` via
``configurable.thread_id`` (see ``checkpoint_keys``) when a checkpointer is
attached. Persistence for goals remains ``StrangeLoopStateManager``.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from soothe.sloop.stages.complete.finalize import node_goal_completion
from soothe.sloop.stages.execute.begin_iteration import node_iteration_start
from soothe.sloop.stages.execute.check_limits import node_iteration_gate
from soothe.sloop.stages.execute.commit_plan import node_resolve_decision
from soothe.sloop.stages.execute.execute import node_execute
from soothe.sloop.stages.execute.record_progress import node_record_iteration
from soothe.sloop.stages.execute.validate_plan import node_validate_evidence_bindings
from soothe.sloop.stages.plan.analyze_gaps import node_plan_gap_analysis
from soothe.sloop.stages.plan.assess import node_plan_assess
from soothe.sloop.stages.plan.gather_evidence import node_bounded_evidence_gather
from soothe.sloop.stages.plan.generate_plan import node_plan_generate
from soothe.sloop.stages.preprocess.enter_loop import node_init_or_resume
from soothe.sloop.stages.preprocess.intake import node_intent_classify
from soothe.sloop.stages.sidecars.await_user import node_await_clarification
from soothe.sloop.stages.sidecars.delegate import node_invoke_wired_subagent

from .checkpointer import core_agent_checkpointer
from .routing import (
    route_after_assess,
    route_after_clarification,
    route_after_evidence_gather,
    route_after_execute,
    route_after_gap_analysis,
    route_after_iteration_gate,
    route_after_plan,
    route_after_preprocess,
    route_after_record_iteration,
    route_after_resolve_decision,
    route_after_validate_evidence,
    route_after_wired_subagent,
)
from .runtime_context import LoopRuntimeContext
from .state import LoopGraphState
from .stations import (
    ANALYZE_GAPS,
    ASSESS,
    AWAIT_USER,
    BEGIN_ITERATION,
    CHECK_LIMITS,
    COMMIT_PLAN,
    DELEGATE,
    ENTER_LOOP,
    EXECUTE,
    FINALIZE,
    GATHER_EVIDENCE,
    GENERATE_PLAN,
    INTAKE,
    RECORD_PROGRESS,
    VALIDATE_PLAN,
)

logger = logging.getLogger(__name__)


def _is_real_checkpointer(obj: Any) -> bool:
    """``LangGraph.compile`` only accepts ``BaseCheckpointSaver`` instances or
    the bool/None sentinels — defensively reject mocks / duck-typed values so
    unit tests that hand CoreAgent an ``AsyncMock`` keep working.
    """
    if obj is None:
        return False
    try:
        from langgraph.checkpoint.base import BaseCheckpointSaver
    except Exception:  # noqa: BLE001
        return False
    return isinstance(obj, BaseCheckpointSaver)


def build_strange_loop_graph(ctx: LoopRuntimeContext):
    """Build and compile the Loop orchestrator graph (RFC-220 / IG-663 topology).

    The compiled graph is given the same checkpointer the CoreAgent uses.
    Without a checkpointer LangGraph's ``interrupt(...)`` cannot persist
    across ``ainvoke`` calls, so a clarification suspended in
    ``await_user`` could never be resumed via ``Command(resume=...)``
    on the next user input — the user's text would be classified as a new
    goal and the prior interrupt would dangle (RFC-622 / IG-462).
    """

    async def intake(state: dict[str, Any]) -> dict[str, Any]:
        return await node_intent_classify(ctx, state)

    async def enter_loop(state: dict[str, Any]) -> dict[str, Any]:
        return await node_init_or_resume(ctx, state)

    async def delegate(state: dict[str, Any]) -> dict[str, Any]:
        return await node_invoke_wired_subagent(ctx, state)

    async def check_limits(state: dict[str, Any]) -> dict[str, Any]:
        return await node_iteration_gate(ctx, state)

    async def begin_iteration(state: dict[str, Any]) -> dict[str, Any]:
        return await node_iteration_start(ctx, state)

    async def gather_evidence(state: dict[str, Any]) -> dict[str, Any]:
        return await node_bounded_evidence_gather(ctx, state)

    async def generate_plan(state: dict[str, Any]) -> dict[str, Any]:
        return await node_plan_generate(ctx, state)

    async def assess(state: dict[str, Any]) -> dict[str, Any]:
        return await node_plan_assess(ctx, state)

    async def analyze_gaps(state: dict[str, Any]) -> dict[str, Any]:
        return await node_plan_gap_analysis(ctx, state)

    async def finalize(state: dict[str, Any]) -> dict[str, Any]:
        return await node_goal_completion(ctx, state)

    async def commit_plan(state: dict[str, Any]) -> dict[str, Any]:
        return await node_resolve_decision(ctx, state)

    async def validate_plan(state: dict[str, Any]) -> dict[str, Any]:
        return await node_validate_evidence_bindings(ctx, state)

    async def execute(state: dict[str, Any]) -> dict[str, Any]:
        return await node_execute(ctx, state)

    async def record_progress(state: dict[str, Any]) -> dict[str, Any]:
        return await node_record_iteration(ctx, state)

    async def await_user(state: dict[str, Any]) -> dict[str, Any]:
        return await node_await_clarification(ctx, state)

    graph = StateGraph(LoopGraphState)
    graph.add_node(INTAKE, intake)
    graph.add_node(ENTER_LOOP, enter_loop)
    graph.add_node(DELEGATE, delegate)
    graph.add_node(CHECK_LIMITS, check_limits)
    graph.add_node(BEGIN_ITERATION, begin_iteration)
    graph.add_node(GATHER_EVIDENCE, gather_evidence)
    graph.add_node(ANALYZE_GAPS, analyze_gaps)
    graph.add_node(ASSESS, assess)
    graph.add_node(GENERATE_PLAN, generate_plan)
    graph.add_node(FINALIZE, finalize)
    graph.add_node(COMMIT_PLAN, commit_plan)
    graph.add_node(VALIDATE_PLAN, validate_plan)
    graph.add_node(EXECUTE, execute)
    graph.add_node(RECORD_PROGRESS, record_progress)
    graph.add_node(AWAIT_USER, await_user)

    graph.add_edge(START, INTAKE)
    graph.add_edge(INTAKE, ENTER_LOOP)
    graph.add_conditional_edges(
        ENTER_LOOP,
        route_after_preprocess,
        {
            CHECK_LIMITS: CHECK_LIMITS,
            GATHER_EVIDENCE: GATHER_EVIDENCE,
            GENERATE_PLAN: GENERATE_PLAN,
            ASSESS: ASSESS,
            COMMIT_PLAN: COMMIT_PLAN,
            DELEGATE: DELEGATE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        DELEGATE,
        route_after_wired_subagent,
        {
            FINALIZE: FINALIZE,
            AWAIT_USER: AWAIT_USER,
            GENERATE_PLAN: GENERATE_PLAN,
            END: END,
        },
    )
    graph.add_conditional_edges(
        CHECK_LIMITS,
        route_after_iteration_gate,
        {BEGIN_ITERATION: BEGIN_ITERATION, END: END},
    )
    graph.add_edge(BEGIN_ITERATION, GATHER_EVIDENCE)
    graph.add_conditional_edges(
        GATHER_EVIDENCE,
        route_after_evidence_gather,
        {
            ASSESS: ASSESS,
            ANALYZE_GAPS: ANALYZE_GAPS,
            GENERATE_PLAN: GENERATE_PLAN,
        },
    )
    graph.add_conditional_edges(
        ANALYZE_GAPS,
        route_after_gap_analysis,
        {ASSESS: ASSESS},
    )
    graph.add_conditional_edges(
        ASSESS,
        route_after_assess,
        {
            FINALIZE: FINALIZE,
            COMMIT_PLAN: COMMIT_PLAN,
            GENERATE_PLAN: GENERATE_PLAN,
            AWAIT_USER: AWAIT_USER,
        },
    )
    graph.add_conditional_edges(
        GENERATE_PLAN,
        route_after_plan,
        {
            FINALIZE: FINALIZE,
            COMMIT_PLAN: COMMIT_PLAN,
            GENERATE_PLAN: GENERATE_PLAN,
            AWAIT_USER: AWAIT_USER,
        },
    )
    graph.add_edge(FINALIZE, END)
    graph.add_conditional_edges(
        COMMIT_PLAN,
        route_after_resolve_decision,
        {VALIDATE_PLAN: VALIDATE_PLAN, END: END},
    )
    graph.add_conditional_edges(
        VALIDATE_PLAN,
        route_after_validate_evidence,
        {EXECUTE: EXECUTE, END: END},
    )
    graph.add_conditional_edges(
        EXECUTE,
        route_after_execute,
        {
            RECORD_PROGRESS: RECORD_PROGRESS,
            AWAIT_USER: AWAIT_USER,
            CHECK_LIMITS: CHECK_LIMITS,
            END: END,
        },
    )
    graph.add_conditional_edges(
        RECORD_PROGRESS,
        route_after_record_iteration,
        {
            CHECK_LIMITS: CHECK_LIMITS,
            FINALIZE: FINALIZE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        AWAIT_USER,
        route_after_clarification,
        {
            EXECUTE: EXECUTE,
            GENERATE_PLAN: GENERATE_PLAN,
            ASSESS: ASSESS,
            ANALYZE_GAPS: ANALYZE_GAPS,
            DELEGATE: DELEGATE,
            END: END,
        },
    )

    checkpointer = core_agent_checkpointer(ctx.strange_loop)
    if _is_real_checkpointer(checkpointer):
        return graph.compile(checkpointer=checkpointer)
    # Without a checkpointer LangGraph ``interrupt()`` ends the invoke but is
    # not durable — Approve / clarification resume cannot ``Command(resume=...)``.
    logger.warning(
        "[orchestrator] Compiling StrangeLoop graph without checkpointer; "
        "clarification interrupts will not resume across turns"
    )
    return graph.compile()
