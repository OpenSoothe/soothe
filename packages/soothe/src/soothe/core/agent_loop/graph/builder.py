"""Compile the Agent Loop LangGraph (RFC-220).

The graph checkpoint namespace uses ``loop_id`` via ``configurable.thread_id`` when a
checkpointer is attached. Persistence for goals remains ``AgentLoopStateManager``.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes.bounded_evidence_gather import node_bounded_evidence_gather
from .nodes.execute_steps import node_execute
from .nodes.goal_completion import node_goal_completion
from .nodes.init_or_resume import node_init_or_resume
from .nodes.iteration_gate import node_iteration_gate
from .nodes.iteration_start import node_iteration_start
from .nodes.plan_generate import node_plan_generate
from .nodes.record_iteration import node_record_iteration
from .nodes.resolve_decision import node_resolve_decision
from .nodes.validate_evidence_bindings import node_validate_evidence_bindings
from .routing import (
    route_after_execute,
    route_after_iteration_gate,
    route_after_plan,
    route_after_record_iteration,
    route_after_resolve_decision,
    route_after_validate_evidence,
)
from .runtime_context import LoopRuntimeContext
from .state import LoopGraphState


def build_agent_loop_graph(ctx: LoopRuntimeContext):
    """Build and compile the Loop orchestrator graph (RFC-220 topology)."""

    async def init_or_resume(state: dict[str, Any]) -> dict[str, Any]:
        return await node_init_or_resume(ctx, state)

    async def iteration_gate(state: dict[str, Any]) -> dict[str, Any]:
        return await node_iteration_gate(ctx, state)

    async def iteration_start(state: dict[str, Any]) -> dict[str, Any]:
        return await node_iteration_start(ctx, state)

    async def bounded_evidence_gather(state: dict[str, Any]) -> dict[str, Any]:
        return await node_bounded_evidence_gather(ctx, state)

    async def plan_generate(state: dict[str, Any]) -> dict[str, Any]:
        return await node_plan_generate(ctx, state)

    async def goal_completion(state: dict[str, Any]) -> dict[str, Any]:
        return await node_goal_completion(ctx, state)

    async def resolve_decision(state: dict[str, Any]) -> dict[str, Any]:
        return await node_resolve_decision(ctx, state)

    async def validate_evidence_bindings(state: dict[str, Any]) -> dict[str, Any]:
        return await node_validate_evidence_bindings(ctx, state)

    async def execute(state: dict[str, Any]) -> dict[str, Any]:
        return await node_execute(ctx, state)

    async def record_iteration(state: dict[str, Any]) -> dict[str, Any]:
        return await node_record_iteration(ctx, state)

    graph = StateGraph(LoopGraphState)
    graph.add_node("init_or_resume", init_or_resume)
    graph.add_node("iteration_gate", iteration_gate)
    graph.add_node("iteration_start", iteration_start)
    graph.add_node("bounded_evidence_gather", bounded_evidence_gather)
    graph.add_node("plan_generate", plan_generate)
    graph.add_node("goal_completion", goal_completion)
    graph.add_node("resolve_decision", resolve_decision)
    graph.add_node("validate_evidence_bindings", validate_evidence_bindings)
    graph.add_node("execute", execute)
    graph.add_node("record_iteration", record_iteration)

    graph.add_edge(START, "init_or_resume")
    graph.add_edge("init_or_resume", "iteration_gate")
    graph.add_conditional_edges(
        "iteration_gate",
        route_after_iteration_gate,
        {"iteration_start": "iteration_start", END: END},
    )
    graph.add_edge("iteration_start", "bounded_evidence_gather")
    graph.add_edge("bounded_evidence_gather", "plan_generate")
    graph.add_conditional_edges(
        "plan_generate",
        route_after_plan,
        {"goal_completion": "goal_completion", "resolve_decision": "resolve_decision"},
    )
    graph.add_edge("goal_completion", END)
    graph.add_conditional_edges(
        "resolve_decision",
        route_after_resolve_decision,
        {"validate_evidence_bindings": "validate_evidence_bindings", END: END},
    )
    graph.add_conditional_edges(
        "validate_evidence_bindings",
        route_after_validate_evidence,
        {"execute": "execute", END: END},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {"record_iteration": "record_iteration", END: END},
    )
    graph.add_conditional_edges(
        "record_iteration",
        route_after_record_iteration,
        {"iteration_gate": "iteration_gate", END: END},
    )

    return graph.compile()
