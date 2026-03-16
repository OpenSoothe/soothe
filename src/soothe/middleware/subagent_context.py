"""Subagent context projection middleware."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe.protocols.context import ContextProtocol

_DEFAULT_SUBAGENT_TOKEN_BUDGET = 1200


class SubagentContextMiddleware(AgentMiddleware):
    """Inject `project_for_subagent` briefings into `task` delegations."""

    def __init__(self, context: ContextProtocol, token_budget: int = _DEFAULT_SUBAGENT_TOKEN_BUDGET) -> None:
        self._context = context
        self._token_budget = token_budget

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        tool_call = request.tool_call or {}
        if tool_call.get("name") != "task":
            return await handler(request)

        tool_args = tool_call.get("args", {})
        if not isinstance(tool_args, dict):
            return await handler(request)

        goal = str(tool_args.get("prompt") or tool_args.get("description") or "").strip()
        if not goal:
            return await handler(request)

        try:
            projection = await self._context.project_for_subagent(goal=goal, token_budget=self._token_budget)
        except Exception:
            return await handler(request)

        if not projection.entries:
            return await handler(request)

        brief_lines = [f"- [{entry.source}] {entry.content[:220]}" for entry in projection.entries[:8]]
        briefing = (
            "<subagent_context>\n"
            "Use this scoped context briefing while solving the task:\n"
            + "\n".join(brief_lines)
            + "\n</subagent_context>\n\n"
        )

        prompt = str(tool_args.get("prompt") or "")
        if "<subagent_context>" not in prompt:
            tool_args["prompt"] = briefing + (prompt or goal)
            tool_call["args"] = tool_args
            request.tool_call = tool_call

        return await handler(request)
