"""Return recoverable outbound network failures as tool messages instead of aborting the step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.utils.network_errors import format_tool_network_error, is_recoverable_tool_network_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)


class NetworkToolErrorsMiddleware(AgentMiddleware):
    """Catch TLS and connection-refused errors from tools and surface them to the model."""

    name = "NetworkToolErrorsMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Run the tool; on recoverable network errors, return a ToolMessage instead of raising."""
        try:
            return await handler(request)
        except Exception as exc:
            if not is_recoverable_tool_network_error(exc):
                raise
            tool_call = request.tool_call or {}
            tool_name = str(tool_call.get("name", "tool"))
            message = format_tool_network_error(exc)
            logger.warning(
                "Tool %s network error (returned to model): %s",
                tool_name,
                message,
            )
            return ToolMessage(
                content=f"Error: {message}",
                tool_call_id=tool_call.get("id"),
                name=tool_name,
            )
