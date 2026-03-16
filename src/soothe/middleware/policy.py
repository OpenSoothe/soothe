"""Policy middleware for tool and subagent delegation checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe.protocols.policy import ActionRequest, PermissionSet, PolicyContext, PolicyProtocol


class SoothePolicyMiddleware(AgentMiddleware):
    """Enforce PolicyProtocol on tool calls and subagent delegations."""

    def __init__(self, policy: PolicyProtocol, profile_name: str = "standard") -> None:
        self._policy = policy
        self._profile_name = profile_name

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", ""))
        tool_args = tool_call.get("args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        action_type = "subagent_spawn" if tool_name == "task" else "tool_call"
        action_name = tool_name
        if tool_name == "task":
            action_name = str(tool_args.get("subagent_type") or tool_args.get("description") or "task")

        ctx = PolicyContext(
            active_permissions=self._resolve_permissions(),
            thread_id=self._thread_id_from_request(request),
        )
        decision = self._policy.check(
            ActionRequest(action_type=action_type, tool_name=action_name, tool_args=tool_args),
            ctx,
        )
        self._emit_policy_event(
            request,
            event_type="soothe.policy.checked",
            payload={
                "action": action_type,
                "tool": action_name,
                "verdict": decision.verdict,
                "profile": self._profile_name,
            },
        )

        if decision.verdict == "deny":
            self._emit_policy_event(
                request,
                event_type="soothe.policy.denied",
                payload={
                    "action": action_type,
                    "tool": action_name,
                    "reason": decision.reason,
                    "profile": self._profile_name,
                },
            )
            return ToolMessage(
                content=f"Policy denied action '{action_name}': {decision.reason}",
                tool_call_id=tool_call.get("id"),
                name=tool_name or "policy",
            )

        return await handler(request)

    def _resolve_permissions(self) -> PermissionSet:
        get_profile = getattr(self._policy, "get_profile", None)
        if callable(get_profile):
            profile = get_profile(self._profile_name)
            if profile is not None:
                return profile.permissions
        return PermissionSet(frozenset())

    @staticmethod
    def _thread_id_from_request(request: ToolCallRequest) -> str | None:
        config = getattr(request.runtime, "config", None)
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
                if isinstance(thread_id, str):
                    return thread_id
        return None

    @staticmethod
    def _emit_policy_event(request: ToolCallRequest, event_type: str, payload: dict[str, Any]) -> None:
        stream_writer = getattr(request.runtime, "stream_writer", None)
        if not callable(stream_writer):
            return
        try:
            stream_writer({"type": event_type, **payload})
        except Exception:
            # Policy checks must not fail tool execution due to telemetry.
            return
