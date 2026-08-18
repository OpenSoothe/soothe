"""Shared helpers for plan-stage station nodes."""

from __future__ import annotations

from typing import Any

from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext


def resolve_loop_planner(ctx: LoopRuntimeContext) -> Any:
    """Return the underlying LLMPlanner when available (for Langfuse pin)."""
    strange_loop = ctx.strange_loop
    planner = getattr(strange_loop, "loop_planner", None)
    if planner is not None:
        return planner
    phase = getattr(strange_loop, "plan_phase", None)
    return getattr(phase, "_loop_planner", None) if phase is not None else None


__all__ = ["resolve_loop_planner"]
