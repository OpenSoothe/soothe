"""Tool call args recording middleware (IG-519).

Lightweight middleware that captures tool-call kwargs for display purposes.
Optimization logic (reuse/dedup/search policy) is owned by
``ToolOptimizationMiddleware``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.middleware.tool_call_args_registry import record_tool_call_args_from_request

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command


class ToolCallArgsMiddleware(AgentMiddleware):
    """Middleware that records tool call args for display purposes.

    Captures kwargs from ToolCallRequest at invocation time so downstream
    stream code can attach them to unified wire ids (subagent display).

    This is a lightweight replacement for ToolConcurrencyMiddleware's
    registry functionality, without the ineffective semaphore (IG-519).
    """

    name = "ToolCallArgsMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Record tool call args before execution.

        Args:
            request: The tool call request.
            handler: The next handler (actual tool execution).

        Returns:
            Tool execution result.
        """
        # Fast path: skip recording for batched operations (IG-517)
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        record_tool_call_args_from_request(request)
        return await handler(request)


__all__ = ["ToolCallArgsMiddleware"]
