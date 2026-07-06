"""Append actionable hints when the model invokes a non-existent tool."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.middleware.tool_name_hints import (
    append_hint_to_tool_result,
    extract_tool_message_content,
    is_invalid_tool_error,
    suggest_invalid_tool_hint,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)


class InvalidToolHintsMiddleware(AgentMiddleware):
    """Enrich LangGraph invalid-tool errors with targeted recovery hints."""

    name = "InvalidToolHintsMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Run the tool and append a hint when the model picked a bad tool name."""
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", ""))
        args = tool_call.get("args", {})

        result = await handler(request)
        content = extract_tool_message_content(result)
        if not content or not is_invalid_tool_error(content):
            return result

        hint = suggest_invalid_tool_hint(tool_name, args)
        if not hint:
            return result

        logger.debug(
            "[InvalidToolHints] Appended hint for hallucinated tool %r",
            tool_name,
        )
        return append_hint_to_tool_result(result, hint=hint)
