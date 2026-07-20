"""WorkspaceContextMiddleware for thread-aware workspace (RFC-103, IG-405)."""

from __future__ import annotations

from contextvars import Token
from pathlib import Path
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
        → FrameworkFilesystem.clear_current_workspace(token) after execution
    """

    def __init__(self) -> None:
        self._workspace_token: Token[Path | None] | None = None

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
        from pathlib import Path

        from langgraph.config import get_config

        from soothe_nano.workspace import FrameworkFilesystem, set_virtual_mode_context
        from soothe_nano.workspace.workspace_api import (
            resolve_workspace_for_tool_execution,
        )

        config: dict[str, Any] = {}
        try:
            raw_config = get_config()
            if isinstance(raw_config, dict):
                config = raw_config
        except Exception:
            pass

        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        config_workspace = configurable.get("workspace") if isinstance(configurable, dict) else None
        state_workspace = state.get("workspace") if isinstance(state, dict) else None

        workspace_path = resolve_workspace_for_tool_execution(
            config=config or None,
            state=state,
            use_langgraph_config=True,
        )
        if workspace_path is None and config_workspace:
            workspace_path = Path(str(config_workspace)).expanduser().resolve()
        if workspace_path is None and state_workspace:
            workspace_path = Path(str(state_workspace)).expanduser().resolve()
        if workspace_path is None:
            return None

        soothe_config = configurable.get("soothe_config")
        if soothe_config is None and isinstance(state, dict):
            soothe_config = state.get("soothe_config")

        self._workspace_token = FrameworkFilesystem.set_current_workspace(workspace_path)

        virtual_mode = False
        if soothe_config is not None and hasattr(soothe_config, "security"):
            virtual_mode = not soothe_config.security.allow_paths_outside_workspace

        set_virtual_mode_context(virtual_mode, Path(workspace_path))

        if config_workspace is not None:
            return {"workspace": str(workspace_path)}
        if state_workspace is not None:
            return None
        return {"workspace": str(workspace_path)}

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
        from soothe_nano.workspace import FrameworkFilesystem, clear_virtual_mode_context

        FrameworkFilesystem.clear_current_workspace(self._workspace_token)
        self._workspace_token = None
        clear_virtual_mode_context()  # IG-405
        return None
