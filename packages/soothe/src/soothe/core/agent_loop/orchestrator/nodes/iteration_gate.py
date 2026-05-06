"""Iteration cap check before per-iteration work (RFC-220 ``iteration_gate``)."""

from __future__ import annotations

from typing import Any

from ..runtime_context import LoopRuntimeContext
from .max_iterations_terminal import emit_max_iterations_terminal


async def node_iteration_gate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Stop with terminal completion when the iteration budget is exhausted."""
    if ctx.loop_state.iteration >= ctx.loop_state.max_iterations:
        await emit_max_iterations_terminal(ctx)
        return {"last_outcome": "max_iterations"}
    return {}
