"""Plan subagent package (RFC-618).

Structured planning with optional direct invokes of the explore subagent runnable.
"""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .implementation import create_plan_subagent
from .schemas import (
    CollectorDecision,
    PlanDecomposition,
    PlanRefinement,
    PlanStepDraft,
    PlanSubagentConfig,
)

__all__ = [
    "CollectorDecision",
    "PlanDecomposition",
    "PlanRefinement",
    "PlanStepDraft",
    "PlanSubagentConfig",
    "PlanPlugin",
    "create_plan_subagent",
]


@plugin(
    name="plan",
    version="1.0.0",
    description="Structured planning subagent with optional explore delegation",
    trust_level="built-in",
)
class PlanPlugin:
    """Built-in plan subagent plugin."""

    async def on_load(self, context: Any) -> None:
        """Record load."""
        context.logger.info("Loaded plan subagent v1.0.0")

    @subagent(
        name="plan",
        description=(
            "Agentic planning delegate: multi-round readonly explore collection (several searches "
            "per round), then multi-round markdown plan refinement; one report back per task. "
            "Use for complex objectives needing evidence before a stable plan."
        ),
        triggers=["plan", "decompose", "roadmap", "break down"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create plan subagent runnable."""
        ctx = {
            "work_dir": getattr(context, "work_dir", ""),
        }
        return create_plan_subagent(model, config, ctx)
