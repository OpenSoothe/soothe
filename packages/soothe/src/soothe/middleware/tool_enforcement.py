"""Tool enforcement middleware for request-time tool narrowing policies."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage

from soothe.foundation.sloop.state.schemas import is_intake_only_wire_subagent

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
    """Return per-step catalog subagent hint from LangGraph RunnableConfig when set."""
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
    if not stripped or is_intake_only_wire_subagent(stripped):
        return None
    return stripped


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


def _task_subagent_type(request: ToolCallRequest) -> str | None:
    """Extract ``subagent_type`` from a ``task`` tool call."""
    tool_call = getattr(request, "tool_call", None)
    if not isinstance(tool_call, dict):
        return None
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None
    raw = args.get("subagent_type")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


class ToolEnforcementMiddleware(AgentMiddleware):
    """Apply request-time tool availability policies.

    Policies:
    - Goal synthesis: disable all tools.
    - Explicit wire subagent routing on first hop: task-only tools (catalog only).
    - Per-step configured subagent routing: task-only tools for full step.
    - Intake-only specialists (IG-601): always reject ``task`` invokes — they are
      not on the CoreAgent graph and run only via wired direct invoke.
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

        if isinstance(preferred_subagent, str) and is_intake_only_wire_subagent(preferred_subagent):
            # IG-601: intake-only never rides CoreAgent task enforcement.
            preferred_subagent = None

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

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        """Reject ``task`` calls to intake-only specialists (IG-601 belt-and-suspenders)."""
        tool_call = getattr(request, "tool_call", None)
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
        if tool_name != _TASK_TOOL_NAME:
            return await handler(request)

        subagent_type = _task_subagent_type(request)
        if subagent_type is None or not is_intake_only_wire_subagent(subagent_type):
            return await handler(request)

        tool_call_id = ""
        if isinstance(tool_call, dict):
            raw_id = tool_call.get("id")
            if isinstance(raw_id, str):
                tool_call_id = raw_id
        logger.info(
            "Blocked task invoke for intake-only subagent=%s (not on CoreAgent graph)",
            subagent_type,
        )
        return ToolMessage(
            content=(
                f"Subagent '{subagent_type}' is intake-only and is not available via "
                f"`{_TASK_TOOL_NAME}`. It runs only through intake / slash wired routing."
            ),
            tool_call_id=tool_call_id,
            name=_TASK_TOOL_NAME,
            status="error",
        )
