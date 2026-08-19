"""Apply host goal-synthesis policy to CoreAgent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
)

from soothe.sloop.utils.config_keys import SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY

logger = logging.getLogger(__name__)


def _langgraph_configurable() -> dict[str, Any]:
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return {}
    if not isinstance(lg_cfg, dict):
        return {}
    conf = lg_cfg.get("configurable")
    return conf if isinstance(conf, dict) else {}


class GoalStepGuardMiddleware(AgentMiddleware):
    """Host policy from LangGraph ``configurable`` for goal synthesis."""

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        conf = _langgraph_configurable()

        if not conf.get(SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY):
            return request

        logger.info("Goal synthesis read-only: disabling model tools")
        if hasattr(request.state, "pop"):
            try:
                request.state.pop("_subagent_routing_directive", None)
            except (AttributeError, TypeError):
                pass
        return request.override(tools=[])

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Apply goal-synthesis policy before the sync model call."""
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Apply goal-synthesis policy before the async model call."""
        return await handler(self.modify_request(request))


__all__ = ["GoalStepGuardMiddleware"]
