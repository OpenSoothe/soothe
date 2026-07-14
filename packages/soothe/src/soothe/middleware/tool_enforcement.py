"""Tool enforcement middleware for request-time tool narrowing policies."""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)

_TASK_TOOL_NAME = "task"


def _configurable_goal_synthesis() -> bool:
    """Return True when CoreAgent is running goal-completion synthesis (read-only)."""
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return False
    if not isinstance(lg_cfg, dict):
        return False
    conf = lg_cfg.get("configurable")
    if not isinstance(conf, dict):
        return False
    return bool(conf.get("soothe_goal_synthesis"))


def _configurable_step_subagent() -> str | None:
    """Return per-step subagent hint from LangGraph RunnableConfig when set."""
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return None
    if not isinstance(lg_cfg, dict):
        return None
    conf = lg_cfg.get("configurable")
    if not isinstance(conf, dict):
        return None
    raw = conf.get("soothe_step_subagent")
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def _last_message_is_human(messages: list[Any] | None) -> bool:
    """True when the model is about to produce first reply to latest user turn."""
    if not messages:
        return False
    from langchain_core.messages import HumanMessage

    return isinstance(messages[-1], HumanMessage)


def _filter_tools_to_task_only(
    tools: list[Any],
) -> list[Any]:
    """Keep only the `task` tool so root agent cannot bypass delegation."""
    kept: list[Any] = []
    for tool in tools:
        name: str | None
        if isinstance(tool, dict):
            name = tool.get("name")
        else:
            name = getattr(tool, "name", None)
        if name == _TASK_TOOL_NAME:
            kept.append(tool)
    return kept


class ToolEnforcementMiddleware(AgentMiddleware):
    """Apply request-time tool availability policies.

    Policies:
    - Goal synthesis: disable all tools.
    - Explicit wire subagent routing on first hop: task-only tools.
    - Per-step configured subagent routing: task-only tools for full step.
    """

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Apply tool-narrowing policies and set routing directive state."""
        classification: Any = None
        if hasattr(request.state, "get"):
            classification = request.state.get("routing_classification")

        routing_hint: str | None = None
        preferred_subagent: str | None = None
        if classification:
            if isinstance(classification, dict):
                routing_hint = classification.get("routing_hint")
                preferred_subagent = classification.get("preferred_subagent")
            else:
                routing_hint = getattr(classification, "routing_hint", None)
                preferred_subagent = getattr(classification, "preferred_subagent", None)

        msgs_for_hop = getattr(request, "messages", None) or []
        first_after_user = _last_message_is_human(msgs_for_hop)
        explicit_subagent = routing_hint == "subagent" and bool(preferred_subagent)
        step_subagent = _configurable_step_subagent()
        # Wired step subagents stay task-only for the whole execute step so the
        # model cannot silently fall back to non-task tools.
        step_enforce = step_subagent is not None
        wire_enforce = explicit_subagent and first_after_user
        goal_synthesis = _configurable_goal_synthesis()

        overrides: dict[str, Any] = {}

        if goal_synthesis:
            logger.info("Goal synthesis read-only: disabling model tools")
            overrides["tools"] = []
            try:
                request.state.pop("_subagent_routing_directive", None)
            except (AttributeError, TypeError):
                pass
            return request.override(**overrides)

        if step_enforce:
            directive = step_subagent
            logger.info(
                "StrangeLoop step subagent hint (enforce): soothe_step_subagent=%s",
                step_subagent,
            )
            request.state["_subagent_routing_directive"] = directive
        elif wire_enforce:
            directive = (
                preferred_subagent.strip()
                if isinstance(preferred_subagent, str)
                else preferred_subagent
            )
            logger.info(
                "Explicit subagent routing (enforce): preferred_subagent=%s",
                directive,
            )
            request.state["_subagent_routing_directive"] = directive
        else:
            try:
                request.state.pop("_subagent_routing_directive", None)
            except (AttributeError, TypeError):
                pass
            return request

        tool_list = getattr(request, "tools", None) or []
        task_only = _filter_tools_to_task_only(tool_list)
        if task_only:
            overrides["tools"] = task_only
            logger.info(
                "Subagent delegation enforcement: model tools narrowed to '%s' only",
                _TASK_TOOL_NAME,
            )
        else:
            logger.warning(
                "Subagent delegation enforcement but '%s' tool not in request; leaving full tool set",
                _TASK_TOOL_NAME,
            )

        return request.override(**overrides) if overrides else request

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Any,
    ) -> ModelResponse[Any]:
        """Sync wrapper that applies enforcement before model invocation."""
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Any,
    ) -> ModelResponse[Any]:
        """Async wrapper that applies enforcement before model invocation."""
        return await handler(self.modify_request(request))
