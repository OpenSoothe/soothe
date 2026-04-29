"""Policy middleware for tool and subagent delegation checks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.core.events import PolicyCheckedEvent, PolicyDeniedEvent
from soothe.protocols.policy import (
    ActionRequest,
    PermissionSet,
    PolicyContext,
    PolicyProtocol,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langgraph.types import Command


class SoothePolicyMiddleware(AgentMiddleware):
    """Enforce PolicyProtocol on tool calls and subagent delegations."""

    def __init__(self, policy: PolicyProtocol, profile_name: str = "standard") -> None:
        """Initialize the policy middleware.

        Args:
            policy: Policy implementation for checking actions.
            profile_name: Name of the policy profile to use.
        """
        self._policy = policy
        self._profile_name = profile_name

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        """Check policy before allowing a tool call to proceed.

        Args:
            request: The tool call request containing tool name and arguments.
            handler: The next handler in the middleware chain.

        Returns:
            A ToolMessage with denial reason if policy denies the action,
            otherwise the result from the handler.
        """
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", ""))
        tool_args = tool_call.get("args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        action_type = "subagent_spawn" if tool_name == "task" else "tool_call"
        action_name = tool_name
        if tool_name == "task":
            action_name = str(
                tool_args.get("subagent_type") or tool_args.get("description") or "task"
            )

        workspace = self._workspace_from_request(request)
        ctx = PolicyContext(
            active_permissions=self._resolve_permissions(),
            thread_id=self._thread_id_from_request(request),
            workspace=workspace,
        )
        decision = self._policy.check(
            ActionRequest(action_type=action_type, tool_name=action_name, tool_args=tool_args),
            ctx,
        )
        self._emit_policy_event(
            request,
            PolicyCheckedEvent(
                action=action_type,
                verdict=decision.verdict,
                profile=self._profile_name,
            ).to_dict(),
        )

        if decision.verdict == "deny":
            self._emit_policy_event(
                request,
                PolicyDeniedEvent(
                    action=action_type,
                    reason=decision.reason,
                    profile=self._profile_name,
                ).to_dict(),
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
    def _workspace_from_request(request: ToolCallRequest) -> str | None:
        """Absolute workspace string from LangGraph configurable, if present."""
        config = getattr(request.runtime, "config", None)
        if not isinstance(config, dict):
            return None
        configurable = config.get("configurable", {})
        if not isinstance(configurable, dict):
            return None
        raw = configurable.get("workspace")
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            return str(Path(raw).expanduser().resolve())
        except (OSError, ValueError):
            return raw.strip()

    @staticmethod
    def _emit_policy_event(request: ToolCallRequest, event_dict: dict[str, Any]) -> None:
        """Emit a policy event via the stream writer."""
        stream_writer = getattr(request.runtime, "stream_writer", None)
        if not callable(stream_writer):
            return
        try:
            stream_writer(event_dict)
        except Exception:
            # Policy checks must not fail tool execution due to telemetry.
            return
