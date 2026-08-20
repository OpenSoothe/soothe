"""Compile the Strange Loop LangGraph (RFC-904 decompose topology).

Live graph: INTAKE → ENTER_LOOP → DISPATCH ⇄ EXECUTE → RECORD_PROGRESS →
RECONCILE → ROOT_EVAL → FINALIZE (+ AWAIT_USER / DELEGATE). Legacy plan-spine
stations are deleted; clarification origins from old checkpoints resume at
DISPATCH.

The graph checkpoint key uses ``{loop_id}__strange_loop`` via
``configurable.thread_id`` (see ``checkpoint``) when a checkpointer is
attached. Persistence for goals remains ``StrangeLoopStateManager``.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from soothe.sloop.stations.completion.finalize import node_goal_completion
from soothe.sloop.stations.decompose.dispatch import node as dispatch_node
from soothe.sloop.stations.decompose.reconcile_node import node as reconcile_node
from soothe.sloop.stations.decompose.root_eval import node as root_eval_node
from soothe.sloop.stations.execute.execute import node_execute
from soothe.sloop.stations.execute.record_progress import node_record_iteration
from soothe.sloop.stations.preprocess.enter_loop import node_init_or_resume
from soothe.sloop.stations.preprocess.intake import node_intent_classify
from soothe.sloop.stations.sidecars.await_user import node_await_clarification
from soothe.sloop.stations.sidecars.delegate import node_invoke_wired_subagent

from .checkpoint import core_agent_checkpointer
from .node_base import wrap_node
from .routing import (
    route_after_clarification,
    route_after_dispatch,
    route_after_execute,
    route_after_preprocess,
    route_after_reconcile,
    route_after_record_iteration,
    route_after_root_eval,
    route_after_wired_subagent,
)
from .runtime_context import LoopRuntimeContext
from .stations import (
    AWAIT_USER,
    DELEGATE,
    DISPATCH,
    ENTER_LOOP,
    EXECUTE,
    FINALIZE,
    INTAKE,
    RECONCILE,
    RECORD_PROGRESS,
    ROOT_EVAL,
    LoopGraphState,
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
    """Build and compile the Loop orchestrator graph (RFC-904).

    The compiled graph is given the same checkpointer the CoreAgent uses.
    Without a checkpointer LangGraph's ``interrupt(...)`` cannot persist
    across ``ainvoke`` calls, so a clarification suspended in
    ``await_user`` could never be resumed via ``Command(resume=...)``
    on the next user input — the user's text would be classified as a new
    goal and the prior interrupt would dangle (RFC-622).
    """

    async def intake(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        return await node_intent_classify(ctx, state, config)

    async def enter_loop(state: dict[str, Any]) -> dict[str, Any]:
        return await node_init_or_resume(ctx, state)

    async def delegate(state: dict[str, Any]) -> dict[str, Any]:
        return await node_invoke_wired_subagent(ctx, state)

    async def finalize(state: dict[str, Any]) -> dict[str, Any]:
        return await node_goal_completion(ctx, state)

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
    graph.add_node(DISPATCH, wrap_node(DISPATCH, dispatch_node, ctx))
    graph.add_node(EXECUTE, execute)
    graph.add_node(RECORD_PROGRESS, record_progress)
    graph.add_node(RECONCILE, wrap_node(RECONCILE, reconcile_node, ctx))
    graph.add_node(ROOT_EVAL, wrap_node(ROOT_EVAL, root_eval_node, ctx))
    graph.add_node(FINALIZE, finalize)
    graph.add_node(AWAIT_USER, await_user)

    graph.add_edge(START, INTAKE)
    graph.add_edge(INTAKE, ENTER_LOOP)
    graph.add_conditional_edges(
        ENTER_LOOP,
        route_after_preprocess,
        {
            DISPATCH: DISPATCH,
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
            DISPATCH: DISPATCH,
            END: END,
        },
    )
    graph.add_conditional_edges(
        DISPATCH,
        route_after_dispatch,
        {
            EXECUTE: EXECUTE,
            ROOT_EVAL: ROOT_EVAL,
            END: END,
        },
    )
    graph.add_conditional_edges(
        EXECUTE,
        route_after_execute,
        {
            RECORD_PROGRESS: RECORD_PROGRESS,
            AWAIT_USER: AWAIT_USER,
            END: END,
        },
    )
    graph.add_conditional_edges(
        RECORD_PROGRESS,
        route_after_record_iteration,
        {
            RECONCILE: RECONCILE,
            FINALIZE: FINALIZE,
            END: END,
        },
    )
    graph.add_conditional_edges(
        RECONCILE,
        route_after_reconcile,
        {
            DISPATCH: DISPATCH,
            ROOT_EVAL: ROOT_EVAL,
        },
    )
    graph.add_conditional_edges(
        ROOT_EVAL,
        route_after_root_eval,
        {
            FINALIZE: FINALIZE,
            DISPATCH: DISPATCH,
            END: END,
        },
    )
    graph.add_edge(FINALIZE, END)
    graph.add_conditional_edges(
        AWAIT_USER,
        route_after_clarification,
        {
            EXECUTE: EXECUTE,
            DISPATCH: DISPATCH,
            DELEGATE: DELEGATE,
            END: END,
        },
    )

    checkpointer = core_agent_checkpointer(ctx.strange_loop)
    if _is_real_checkpointer(checkpointer):
        return graph.compile(checkpointer=checkpointer)
    logger.warning(
        "[orchestrator] Compiling StrangeLoop graph without checkpointer; "
        "clarification interrupts will not resume across turns"
    )
    return graph.compile()
