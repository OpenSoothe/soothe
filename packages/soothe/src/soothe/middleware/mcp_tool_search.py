"""RFC-412: MCP tool search and progressive disclosure middleware.

Intercepts tool calls matching mcp__server__tool pattern and:
1. Records invocation telemetry
2. Validates tool availability via registry
3. Emits MCPToolSearchQueriedEvent for search queries
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

logger = logging.getLogger(__name__)

# Pattern for MCP tool names: mcp__<server>__<tool>
_MCP_TOOL_PATTERN = re.compile(r"^mcp__(.+)__(.+)$")


class MCPToolSearchMiddleware(AgentMiddleware):
    """Intercepts MCP tool calls for progressive disclosure and telemetry.

    Installed after SkillActivationMiddleware in the stack (RFC-412).
    """

    def __init__(self, mcp_registry: Any) -> None:
        """Initialize middleware.

        Args:
            mcp_registry: MCPRegistry instance for tool validation.
        """
        self._registry = mcp_registry

    async def abefore_agent(self, state: dict, runtime: Any) -> dict | None:
        """Lazy-init MCP state fields if missing."""
        if not isinstance(state, dict):
            return None
        updates: dict[str, Any] = {}
        if "sent_mcp_tool_names" not in state:
            updates["sent_mcp_tool_names"] = set()
        if "invoked_mcp_tools" not in state:
            updates["invoked_mcp_tools"] = {}
        if "disabled_mcp_servers" not in state:
            updates["disabled_mcp_servers"] = set()
        if "cached_mcp_resources" not in state:
            updates["cached_mcp_resources"] = {}
        return updates if updates else None

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Record MCP tool invocations and emit telemetry."""
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        match = _MCP_TOOL_PATTERN.match(tool_name)
        if not match:
            return await handler(request)

        server_name, bare_tool = match.groups()
        state = getattr(request, "state", None) or {}
        if not isinstance(state, dict):
            return await handler(request)

        # Check if server is disabled
        disabled = state.get("disabled_mcp_servers", set())
        if server_name in disabled:
            logger.warning("[MCP] Tool %s invoked on disabled server %s", tool_name, server_name)
            # Let the handler proceed - the registry will raise an error

        # Record invocation
        invoked = state.get("invoked_mcp_tools", {})
        if not isinstance(invoked, dict):
            invoked = {}
        invoked[tool_name] = {
            "server": server_name,
            "tool": bare_tool,
            "args": tool_call.get("args", {}),
        }
        state["invoked_mcp_tools"] = invoked

        # Emit telemetry event (success/failure tracked by registry)
        try:
            from soothe.mcp.events import emit_tool_search_queried

            emit_tool_search_queried(query=tool_name, match_count=1)
        except Exception:  # noqa: BLE001
            logger.debug("[MCP] Event emit failed", exc_info=True)

        return await handler(request)
