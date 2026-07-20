"""Reject ``task`` invokes for intake-only specialists (host belt-and-suspenders)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage

from soothe.foundation.sloop.subagent_catalog import is_intake_only_wire_subagent

logger = logging.getLogger(__name__)

_TASK_TOOL_NAME = "task"


def _preferred_from_classification(classification: Any) -> str | None:
    if classification is None:
        return None
    if isinstance(classification, dict):
        raw = classification.get("preferred_subagent")
    else:
        raw = getattr(classification, "preferred_subagent", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _clear_preferred_subagent(classification: Any) -> Any:
    if classification is None:
        return None
    if isinstance(classification, dict):
        updated = dict(classification)
        updated["preferred_subagent"] = None
        return updated
    try:
        return classification.model_copy(update={"preferred_subagent": None})
    except Exception:
        try:
            object.__setattr__(classification, "preferred_subagent", None)
        except Exception:
            pass
        return classification


def _task_subagent_type(request: ToolCallRequest) -> str | None:
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


class IntakeOnlyTaskGuardMiddleware(AgentMiddleware):
    """Block ``task`` calls to intake-only specialists; scrub preferred routing."""

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Clear intake-only ``preferred_subagent`` so tool narrowing stays open."""
        if not hasattr(request.state, "get"):
            return request
        classification = request.state.get("routing_classification")
        preferred = _preferred_from_classification(classification)
        if preferred is None or not is_intake_only_wire_subagent(preferred):
            return request
        logger.info(
            "Clearing intake-only preferred_subagent=%s (not on CoreAgent task catalog)",
            preferred,
        )
        request.state["routing_classification"] = _clear_preferred_subagent(classification)
        try:
            request.state.pop("_subagent_routing_directive", None)
        except (AttributeError, TypeError):
            pass
        return request

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
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
                f"Subagent '{subagent_type}' is intake-only and not available via "
                f"`{_TASK_TOOL_NAME}`. It runs only through host wired routing."
            ),
            tool_call_id=tool_call_id,
            name=_TASK_TOOL_NAME,
            status="error",
        )


__all__ = ["IntakeOnlyTaskGuardMiddleware"]
