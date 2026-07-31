"""Shared plan-phase status card emission for gather/assess/gap/generate."""

from __future__ import annotations

from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext


async def emit_plan_phase_status(
    ctx: LoopRuntimeContext,
    *,
    label: str,
) -> None:
    """Emit ``plan_phase_status`` with the current token total from loop state."""
    await ctx.emit(
        "plan_phase_status",
        {
            "label": label,
            "total_tokens_used": ctx.loop_state.total_tokens_used,
        },
    )
