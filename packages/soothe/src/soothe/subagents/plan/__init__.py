"""Plan subagent package (RFC-618).

Structured planning delegate for markdown execution plans.
"""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .implementation import create_plan_subagent
from .schemas import (
    PlanRefinement,
    PlanSubagentConfig,
)

__all__ = [
    "PlanRefinement",
    "PlanSubagentConfig",
    "PlanPlugin",
    "create_plan_subagent",
]


@plugin(
    name="planner",
    version="1.0.0",
    description="Structured planning subagent",
    trust_level="built-in",
)
class PlanPlugin:
    """Built-in planner subagent plugin."""

    async def on_load(self, context: Any) -> None:
        """Record load."""
        context.logger.info("Loaded planner subagent v1.0.0")

    @subagent(
        name="planner",
        description=(
            "Agentic planning delegate: multi-round markdown plan refinement; one report back "
            "per task. Use for complex objectives needing a stable execution plan."
        ),
        triggers=["planner", "decompose", "roadmap", "break down"],
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
