"""Apply host goal-synthesis policy to CoreAgent."""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest

from soothe.sloop.config_keys import SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY

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


__all__ = ["GoalStepGuardMiddleware"]
