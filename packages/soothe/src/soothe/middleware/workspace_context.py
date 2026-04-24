"""WorkspaceContextMiddleware for thread-aware workspace (RFC-103)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime


class WorkspaceContextMiddleware(AgentMiddleware):
    """Set workspace context for tool execution.

    Reads workspace from config.configurable and sets ContextVar for FrameworkFilesystem.
    Ensures ContextVar is available during tool execution for path resolution.

    Thread Safety:
        Python's contextvars.ContextVar provides async-safe context isolation.
        Each async task (thread execution) has its own context, preventing
        cross-thread contamination even with concurrent execution.

    Example:
        config.configurable = {
            "thread_id": "thread-123",
            "workspace": "/home/user/project-a"
        }

        → FrameworkFilesystem.set_current_workspace("/home/user/project-a")
        → Tools resolve paths against /home/user/project-a
        → FrameworkFilesystem.clear_current_workspace() after execution
    """

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Set workspace context before agent execution.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            State updates (workspace mirrored in state).
        """
        from langgraph.config import get_config

        from soothe.core import FrameworkFilesystem

        # Get config from langgraph context
        try:
            config = get_config()
            configurable = config.get("configurable", {})
        except Exception:
            configurable = {}

        workspace = configurable.get("workspace")

        if workspace:
            FrameworkFilesystem.set_current_workspace(workspace)
            # Mirror in state for explicit access
            return {"workspace": workspace}
        # Try to get workspace from state if available
        if "workspace" in state:
            ws = state["workspace"]
            FrameworkFilesystem.set_current_workspace(ws)
            return None

        return None

    async def aafter_agent(
        self,
        state: AgentState,  # noqa: ARG002
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Clear workspace context after agent execution.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            None.
        """
        from soothe.core import FrameworkFilesystem

        FrameworkFilesystem.clear_current_workspace()
        return None
