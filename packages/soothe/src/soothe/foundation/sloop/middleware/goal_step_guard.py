"""Apply host goal-synthesis and execute-step subagent policies to CoreAgent."""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest

from soothe.foundation.sloop.middleware.config_keys import (
    SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY,
    SOOTHE_STEP_SUBAGENT_CONFIG_KEY,
)

logger = logging.getLogger(__name__)

_TASK_TOOL_NAME = "task"


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


def _filter_tools_to_task_only(tools: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for tool in tools:
        if isinstance(tool, dict):
            name = tool.get("name")
        else:
            name = getattr(tool, "name", None)
        if name == _TASK_TOOL_NAME:
            kept.append(tool)
    return kept


class GoalStepGuardMiddleware(AgentMiddleware):
    """Host policies from LangGraph ``configurable`` for synthesis and step wire."""

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        conf = _langgraph_configurable()
        overrides: dict[str, Any] = {}

        if conf.get(SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY):
            logger.info("Goal synthesis read-only: disabling model tools")
            overrides["tools"] = []
            if hasattr(request.state, "pop"):
                try:
                    request.state.pop("_subagent_routing_directive", None)
                except (AttributeError, TypeError):
                    pass
            return request.override(**overrides)

        raw_step = conf.get(SOOTHE_STEP_SUBAGENT_CONFIG_KEY)
        step_subagent = raw_step.strip() if isinstance(raw_step, str) and raw_step.strip() else None
        if step_subagent is None:
            return request

        logger.info(
            "CoreAgent step subagent hint (enforce): %s=%s",
            SOOTHE_STEP_SUBAGENT_CONFIG_KEY,
            step_subagent,
        )
        if hasattr(request.state, "__setitem__"):
            request.state["_subagent_routing_directive"] = step_subagent

        tool_list = getattr(request, "tools", None) or []
        task_only = _filter_tools_to_task_only(list(tool_list))
        if task_only:
            overrides["tools"] = task_only
            logger.info(
                "Subagent delegation enforcement: model tools narrowed to '%s' only",
                _TASK_TOOL_NAME,
            )
        else:
            logger.warning(
                "Subagent delegation enforcement but '%s' tool not in request; "
                "leaving full tool set",
                _TASK_TOOL_NAME,
            )
        return request.override(**overrides) if overrides else request


__all__ = ["GoalStepGuardMiddleware"]
