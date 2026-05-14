"""Loop Graph ``init_or_resume`` node (RFC-220).

Graph-entry intent classification runs here once per loop invocation.
"""

from __future__ import annotations

import logging
from typing import Any

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_init_or_resume(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Hydrate intent/routing and optionally terminate on fast-path intent."""
    intent = ctx.loop_state.intent
    if intent is None and ctx.intent_classifier is not None:
        observability_metadata = {
            "phase": "agent_loop_graph",
            "component": "agent_loop.intent_classification",
            "loop_id": ctx.state_manager.loop_id,
            "thread_id": ctx.loop_state.thread_id,
        }
        intent = await ctx.intent_classifier.classify_intent(
            ctx.loop_state.goal,
            recent_messages=ctx.recent_messages_for_intent,
            active_goal_id=ctx.active_goal_id_for_intent,
            active_goal_description=ctx.active_goal_description_for_intent,
            thread_id=ctx.loop_state.thread_id,
            observability_metadata=observability_metadata,
        )
        ctx.loop_state.intent = intent

    if intent is not None:
        await ctx.emit(
            "intent_classified",
            {
                "intent_type": getattr(intent, "intent_type", ""),
                "task_complexity": getattr(intent, "task_complexity", ""),
                "friendly_message": getattr(intent, "friendly_message", None),
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
