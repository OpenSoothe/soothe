"""Loop Graph ``init_or_resume`` node (RFC-220).

Hydrates intent/routing from the pre-classified intent passed by the runner.
The runner handles quiz detection and structural continue_thread/new_goal resolution;
this node just emits the classified intent for event streaming.
"""

from __future__ import annotations

import logging
from typing import Any

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_init_or_resume(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit pre-classified intent and check for fast-path quiz termination."""
    intent = ctx.loop_state.intent

    if intent is not None:
        await ctx.emit(
            "intent_classified",
            {
                "intent_type": getattr(intent, "intent_type", ""),
                "task_complexity": getattr(intent, "task_complexity", ""),
                "goal_description": getattr(intent, "goal_description", None),
            },
        )

    intent_type = getattr(intent, "intent_type", "")
    if intent_type == "quiz":
        logger.info("[Intent] Fast path in graph: %s", intent_type)
        await ctx.emit(
            "intent_fast_path",
            {
                "intent_type": intent_type,
                "classification": intent,
            },
        )
        return {"intent_route": "fast_path"}
    return {"intent_route": "continue_loop"}
