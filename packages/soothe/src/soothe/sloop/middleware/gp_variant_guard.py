"""Redirect `task` calls to the read-only GP variant on plan/ask steps."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ToolCallRequest,
)

from soothe.sloop.utils.config_keys import SOOTHE_INTERACTION_MODE_KEY

logger = logging.getLogger(__name__)

_TASK_TOOL_NAME = "task"
_GP_FULL = "general-purpose"
_GP_READONLY = "general-purpose-readonly"
_READONLY_MODES = frozenset({"plan", "ask"})


def _subagent_type(request: ToolCallRequest) -> str | None:
    """Extract the `subagent_type` arg from a `task` tool call."""
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


def _step_mode(request: ToolCallRequest) -> str | None:
    """Read the owning step's interaction mode from the graph configurable."""
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    mode = configurable.get(SOOTHE_INTERACTION_MODE_KEY)
    if isinstance(mode, str) and mode.strip():
        return mode.strip()
    return None


class GeneralPurposeVariantGuardMiddleware(AgentMiddleware):
    """Redirect `task` to the read-only GP variant on plan/ask steps.

    No-op when the step is in agent mode (the common case, including Eval):
    the call proceeds as `general-purpose` (full). On plan/ask steps the
    `subagent_type` is rewritten to `general-purpose-readonly` before the
    task tool resolves the subagent, so the read-only variant runs instead.

    If the read-only variant is not registered (per-step GP disabled), the
    rewrite is skipped and the call proceeds unchanged — this makes the
    middleware safe to install unconditionally; it only acts when both the
    step mode and the variant are in play.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        tool_call = getattr(request, "tool_call", None)
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
        if tool_name != _TASK_TOOL_NAME:
            return await handler(request)

        subagent_type = _subagent_type(request)
        if subagent_type != _GP_FULL:
            # Either not a GP call, or already targeting a specific variant.
            return await handler(request)

        mode = _step_mode(request)
        if mode not in _READONLY_MODES:
            # Agent mode (or unset) — full GP. Eval steps ride the agent mode
            # since the executor sets SOOTHE_EVAL_STEP_ID_KEY additively, not
            # as a mode override.
            return await handler(request)

        # Redirect to the read-only variant for this plan/ask step.
        new_args = {**tool_call["args"], "subagent_type": _GP_READONLY}
        redirected = request.override(tool_call={**tool_call, "args": new_args})
        logger.info(
            "Redirected task→general-purpose to readonly variant (step mode=%s)",
            mode,
        )
        return await handler(redirected)


__all__ = ["GeneralPurposeVariantGuardMiddleware"]
