"""Shared ``plan_phase_status`` status-card emission for loop stations.

The event predates the RFC-904 DISPATCH cutover (it covered the old
gather/assess/gap/generate plan spine, removed in IG-752); it now carries
phase labels for intake, wired-subagent delegation, and goal finalize.
"""

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
