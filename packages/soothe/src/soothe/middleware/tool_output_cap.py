"""Cap tool result payloads before they enter graph state and model context."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from soothe_sdk.utils import get_outcome_type

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_TRUNCATION_SUFFIX = "\n...[truncated for model context]"


def _cap_for_tool(tool_name: str, config: SootheConfig) -> int:
    limits = config.agent.loop.limits
    if get_outcome_type(tool_name) == "code_exec":
        return int(limits.code_exec_max_output_chars)
    return int(limits.tool_output_max_chars)


def _truncate_content(content: Any, max_chars: int) -> Any:
    if isinstance(content, str):
        text = content
    else:
        text = str(content)
    if len(text) <= max_chars:
        return content
    if max_chars <= len(_TRUNCATION_SUFFIX):
        return text[:max_chars]
    return text[: max_chars - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX


def _truncate_tool_message(msg: ToolMessage, max_chars: int) -> ToolMessage:
    capped = _truncate_content(msg.content, max_chars)
    if capped is msg.content:
        return msg
    return ToolMessage(
        content=capped, tool_call_id=msg.tool_call_id, name=getattr(msg, "name", None)
    )


class ToolOutputCapMiddleware(AgentMiddleware):
    """Truncate large tool outputs in graph state and before model calls."""

    name = "ToolOutputCapMiddleware"

    def __init__(self, config: SootheConfig) -> None:
        super().__init__()
        self._config = config

    def _cap_messages(self, messages: list[Any]) -> list[Any]:
        out: list[Any] = []
        changed = False
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", None) or ""
                max_chars = _cap_for_tool(str(tool_name), self._config)
                capped = _truncate_tool_message(msg, max_chars)
                if capped is not msg:
                    changed = True
                out.append(capped)
            else:
                out.append(msg)
        return out if changed else messages

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        max_chars = _cap_for_tool(tool_name, self._config)

        if isinstance(result, ToolMessage):
            capped = _truncate_tool_message(result, max_chars)
            if capped is not result:
                logger.debug(
                    "[ToolOutputCap] Truncated %s output to %d chars",
                    tool_name,
                    max_chars,
                )
            return capped

        if isinstance(result, Command):
            update = getattr(result, "update", None)
            if isinstance(update, dict):
                msgs = update.get("messages")
                if isinstance(msgs, list):
                    new_msgs = []
                    for msg in msgs:
                        if isinstance(msg, ToolMessage):
                            tn = getattr(msg, "name", None) or tool_name
                            new_msgs.append(
                                _truncate_tool_message(msg, _cap_for_tool(str(tn), self._config))
                            )
                        else:
                            new_msgs.append(msg)
                    return Command(update={**update, "messages": new_msgs})
        return result

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        messages = getattr(request, "messages", None) or []
        capped = self._cap_messages(list(messages))
        if capped is not messages:
            request = request.override(messages=capped)
        return await handler(request)
