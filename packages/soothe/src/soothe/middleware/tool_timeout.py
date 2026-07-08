"""Tool timeout middleware for CoreAgent (IG-511).

Wraps tool invocations with configurable timeouts, preventing indefinite hangs
from tools that lack internal timeout guards. This middleware complements
tool-level timeouts (run_command, execute, MCP) with a uniform wrapper.

Architecture:
    Position: Last in middleware stack (innermost wrapper around tool call)
    Pattern: Similar to LLMRateLimitMiddleware for model calls

Default timeouts:
    - Standard tools: 60s
    - Subagent tools: 1800s (30 minutes for exploration/browser)
    - Task tool: 86400s (24 hours for autonomous subagent work)
    - Filesystem tools: 30s (read, glob, grep)
    - Execution tools: 120s (run_command already has timeout)

Configuration:
    config.agent.tool_timeout.default_seconds: 60.0
    config.agent.tool_timeout.per_tool: {grep: 30.0, task: 86400.0}
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.types import Command

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ToolCallRequest

from soothe.foundation.core.filesystem.discovery_hints import (
    format_glob_timeout_error,
)

logger = logging.getLogger(__name__)


def _emit_subagent_timeout_completion_event(
    subagent_type: str,
    tool_call_id: str,
    timeout_s: float,
) -> None:
    """Emit completion event for subagent cancelled due to timeout (IG-516).

    When the task tool times out, the subagent graph execution is cancelled
    and its after_agent hook never runs. This leaves the TUI subagent card
    in "running" state. Emit a completion event to properly close the card.

    Args:
        subagent_type: The subagent being invoked (explore, browser_use, etc).
        tool_call_id: The tool call ID for correlation.
        timeout_s: The timeout duration in seconds.
    """
    # Import lazily to avoid circular imports at module load
    from soothe.utils.subagent_emit import emit_subagent_wire_event

    if subagent_type == "browser_use":
        from soothe.subagents.browser_use.events import BrowserUseCompletedEvent

        emit_subagent_wire_event(
            BrowserUseCompletedEvent(
                success=False,
                duration_ms=0,
                summary=f"Subagent timed out after {timeout_s:.1f}s",
            ).to_dict(),
            logger,
        )
        # For other subagent types (planner, deep_research), no specific completion event exists
    # The timeout error ToolMessage will still mark the step as failed in executor
    logger.debug(
        "Subagent %s timeout completion event emitted (tool_call_id=%s)",
        subagent_type,
        tool_call_id,
    )


# Default timeout values
DEFAULT_TOOL_TIMEOUT_SECONDS: float = 60.0
DEFAULT_SUBAGENT_TIMEOUT_SECONDS: float = 1800.0  # Subagent exploration/browser (30 minutes)
DEFAULT_TASK_TIMEOUT_SECONDS: float = 86400.0  # Task tool for autonomous subagent work (24 hours)
DEFAULT_FILESYSTEM_TIMEOUT_SECONDS: float = 30.0
DEFAULT_EXECUTION_TIMEOUT_SECONDS: float = 120.0

# Tool name patterns for timeout categories
FILESYSTEM_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
        "glob",
        "grep",
        "search_files",
        "file_search",
    }
)

EXECUTION_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_command",
        "execute",
        "run_python",
        "run_background",
    }
)

SUBAGENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "browser_use",
        "planner",
        "deep_research",
        "delegate",
        "task",  # Deepagents task tool invokes subagents dynamically
    }
)

# Tools that already have robust internal timeouts - skip wrapping
TOOLS_WITH_INTERNAL_TIMEOUT: frozenset[str] = frozenset(
    {
        "run_command",  # subprocess.run(timeout=...) already enforced
        "execute",  # deepagents execute has timeout parameter
    }
)


class ToolTimeoutState(AgentState[Any]):
    """State schema for ToolTimeoutMiddleware."""

    tool_timeout_count: int = 0
    tool_timeout_last_tool: str | None = None


class ToolTimeoutMiddleware(AgentMiddleware[ToolTimeoutState, None, Any]):
    """Wrap tool invocations with configurable timeouts.

    IG-511: Prevents indefinite hangs from tools lacking internal timeout guards.
    Returns ToolMessage with error status on timeout, allowing agent to adapt.

    Args:
        default_timeout_seconds: Default timeout for tools without specific override.
        per_tool_timeout: Dict mapping tool names to custom timeouts.
        skip_tools_with_internal_timeout: When True, don't wrap tools that already
            have robust internal timeout mechanisms (run_command, execute).

    Example:
        ```python
        middleware = ToolTimeoutMiddleware(
            default_timeout_seconds=60.0,
            per_tool_timeout={
                "grep": 30.0,
                "deep_research": 180.0,
            },
        )
        ```
    """

    def __init__(
        self,
        *,
        default_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
        per_tool_timeout: dict[str, float] | None = None,
        skip_tools_with_internal_timeout: bool = True,
    ) -> None:
        """Initialize tool timeout middleware.

        Args:
            default_timeout_seconds: Default timeout for all tools.
            per_tool_timeout: Per-tool timeout overrides.
            skip_tools_with_internal_timeout: Skip wrapping tools with internal timeout.
        """
        self._default_timeout = default_timeout_seconds
        self._per_tool_timeout = per_tool_timeout or {}
        self._skip_internal = skip_tools_with_internal_timeout
        self._timeout_count = 0

    def _get_timeout_for_tool(self, tool_name: str) -> float:
        """Get timeout value for a specific tool.

        Priority:
        1. per_tool_timeout explicit override
        2. Category-based defaults (filesystem, execution, subagent)
        3. default_timeout_seconds

        Args:
            tool_name: Name of the tool being invoked.

        Returns:
            Timeout in seconds for this tool.
        """
        # Check explicit override first
        if tool_name in self._per_tool_timeout:
            return self._per_tool_timeout[tool_name]

        # Check category defaults
        if tool_name in FILESYSTEM_TOOL_NAMES:
            return DEFAULT_FILESYSTEM_TIMEOUT_SECONDS
        if tool_name in EXECUTION_TOOL_NAMES:
            return DEFAULT_EXECUTION_TIMEOUT_SECONDS

        # Check task tool first (24h timeout for autonomous subagent work)
        if tool_name == "task":
            return DEFAULT_TASK_TIMEOUT_SECONDS

        # Check subagent pattern (ends with _subagent or matches known names)
        if tool_name in SUBAGENT_TOOL_NAMES or tool_name.endswith("_subagent"):
            return DEFAULT_SUBAGENT_TIMEOUT_SECONDS

        return self._default_timeout

    def _should_skip_timeout(self, tool_name: str) -> bool:
        """Check if tool should skip timeout wrapping.

        Tools with robust internal timeouts (run_command, execute) don't need
        middleware wrapping - their internal timeout is more precise.

        Args:
            tool_name: Name of the tool being invoked.

        Returns:
            True if middleware should skip wrapping this tool.
        """
        if not self._skip_internal:
            return False
        return tool_name in TOOLS_WITH_INTERNAL_TIMEOUT

    def _timeout_error_message(self, tool_name: str, timeout_s: float) -> str:
        """Build a timeout error message, with tool-specific recovery hints."""
        if tool_name == "glob":
            return format_glob_timeout_error(timeout_s)
        return (
            f"Error: Tool '{tool_name}' timed out after {timeout_s:.1f}s. "
            f"Consider narrowing the scope or using a more specific query."
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Synchronous tool call wrapper with timeout.

        Note: Most soothe execution is async, so awrap_tool_call is primary.
        This implementation is for synchronous invoke() calls.

        IG-517: Skip timeout for batched operations (fast path).

        Args:
            request: Tool call request with tool name, args, state, runtime.
            handler: The handler to execute the tool call.

        Returns:
            ToolMessage with result or error on timeout.
        """
        # Fast path: skip timeout for batched operations (IG-517)
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return handler(request)

        tool_name = request.tool_call.get("name", "")
        tool_call_id = request.tool_call.get("id", "")

        if self._should_skip_timeout(tool_name):
            return handler(request)

        timeout_s = self._get_timeout_for_tool(tool_name)

        # Sync timeout using asyncio in thread
        import concurrent.futures

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, request)
                result = future.result(timeout=timeout_s)
                return result
        except TimeoutError:
            logger.warning(
                "Tool %s timed out after %.1fs (sync path)",
                tool_name,
                timeout_s,
            )
            self._timeout_count += 1
            return ToolMessage(
                content=self._timeout_error_message(tool_name, timeout_s),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
            )
        except Exception:
            raise

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Async tool call wrapper with timeout.

        Wraps the handler with asyncio.timeout, returning a ToolMessage error
        on timeout instead of raising. This allows the agent to adapt its
        strategy rather than crashing the entire request.

        IG-516: When task tool times out, emit subagent completion event to
        close the TUI subagent card (deep_research, browser_use, etc).

        IG-517: Skip timeout for batched operations (fast path).

        Args:
            request: Tool call request with tool name, args, state, runtime.
            handler: The async handler to execute the tool call.

        Returns:
            ToolMessage with result or error on timeout.
        """
        # Fast path: skip timeout for batched operations (IG-517)
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        tool_name = request.tool_call.get("name", "")
        tool_call_id = request.tool_call.get("id", "")

        if self._should_skip_timeout(tool_name):
            return await handler(request)

        timeout_s = self._get_timeout_for_tool(tool_name)

        try:
            async with asyncio.timeout(timeout_s):
                result = await handler(request)
                return result
        except TimeoutError:
            logger.warning(
                "Tool %s timed out after %.1fs (async path)",
                tool_name,
                timeout_s,
            )
            self._timeout_count += 1

            # IG-516: Emit completion event for subagent timeout
            if tool_name == "task":
                # Extract subagent_type from tool args
                tool_args = request.tool_call.get("args", {})
                if isinstance(tool_args, dict):
                    subagent_type = tool_args.get("subagent_type", "")
                    if subagent_type:
                        _emit_subagent_timeout_completion_event(
                            subagent_type,
                            tool_call_id,
                            timeout_s,
                        )

            return ToolMessage(
                content=self._timeout_error_message(tool_name, timeout_s),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
            )

    def get_timeout_stats(self) -> dict[str, Any]:
        """Return timeout statistics for observability.

        Returns:
            Dict with timeout_count and last timeout info.
        """
        return {
            "timeout_count": self._timeout_count,
        }


__all__ = [
    "DEFAULT_EXECUTION_TIMEOUT_SECONDS",
    "DEFAULT_FILESYSTEM_TIMEOUT_SECONDS",
    "DEFAULT_SUBAGENT_TIMEOUT_SECONDS",
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "DEFAULT_TOOL_TIMEOUT_SECONDS",
    "EXECUTION_TOOL_NAMES",
    "FILESYSTEM_TOOL_NAMES",
    "SUBAGENT_TOOL_NAMES",
    "TOOLS_WITH_INTERNAL_TIMEOUT",
    "ToolTimeoutMiddleware",
    "ToolTimeoutState",
]
