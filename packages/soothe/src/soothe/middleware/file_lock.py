"""File Lock Middleware for Autopilot mode (RFC-222).

Enforces file lock conflicts across AgentLoop workers in autopilot mode.
Intercepts file-mutating tools (``edit_file``, ``write_file``,
``delete_file``) via langchain's ``awrap_tool_call`` hook and checks
``FileLockRegistry`` for conflicts with other AgentLoops.

Behavior:
- Same loop edits same file → ALLOW (lock holder)
- Different loop edits locked file → RETURN ToolMessage with error status
  (the agent reads the message and can choose another file or replan)
- No existing lock → ACQUIRE + ALLOW + emit ``InternalFileLockedEvent``

This middleware is only meaningful in autopilot mode where multiple ALs
may operate concurrently. Solo mode does not need it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe.core.events.internal_bus import get_internal_bus
from soothe.core.events.internal_events import (
    InternalFileConflictEvent,
    InternalFileLockedEvent,
)
from soothe.core.goal_engine.file_lock_registry import FileLockRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)

_FILE_OP_TOOLS = {"edit_file", "write_file", "delete_file"}
_PATH_KEYS: tuple[str, ...] = ("file_path", "path", "filepath", "file")
_OP_MAP: dict[str, str] = {
    "edit_file": "edit",
    "write_file": "write",
    "delete_file": "delete",
}


class FileLockMiddleware(AgentMiddleware):
    """Langchain middleware for file lock conflict resolution (RFC-222).

    RFC-222 Q1 (preserved-unwired): the daemon-owned ``WorkspaceReservation``
    gate supersedes per-path file locking for v1. This middleware is
    intentionally not installed by any code path. It remains here as a
    tested implementation that can be revived if/when fine-grained per-path
    conflicts within a single workspace become a real production concern.

    Construct one per (loop_id, goal_id) pair so the middleware can
    attribute lock ownership correctly. ``AutopilotService`` is the
    expected constructor; solo mode never instantiates this.
    """

    name = "FileLockMiddleware"

    def __init__(
        self,
        file_registry: FileLockRegistry,
        loop_id: str,
        goal_id: str,
        internal_bus: Any | None = None,
    ) -> None:
        """Initialize FileLockMiddleware.

        Args:
            file_registry: Shared FileLockRegistry from GoalEngine.
            loop_id: Current AgentLoop's ID.
            goal_id: Current goal's ID.
            internal_bus: Optional InternalEventBus override (singleton by default).
        """
        self._file_registry = file_registry
        self._loop_id = loop_id
        self._goal_id = goal_id
        self._internal_bus = internal_bus or get_internal_bus()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Check file-lock conflict before letting the tool run.

        Args:
            request: ToolCallRequest from langchain's middleware chain.
            handler: Next handler in the chain (actual tool execution).

        Returns:
            ToolMessage with error status on conflict; otherwise the
            handler's result.
        """
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", ""))
        if tool_name not in _FILE_OP_TOOLS:
            return await handler(request)

        args = tool_call.get("args") or {}
        if not isinstance(args, dict):
            return await handler(request)

        path = next((str(args[k]) for k in _PATH_KEYS if k in args and args[k]), None)
        if not path:
            return await handler(request)

        operation = _OP_MAP[tool_name]

        if self._file_registry.is_locked_by_other(path, self._loop_id):
            lock = self._file_registry.get_lock(path)
            if lock:
                await self._internal_bus.emit(
                    InternalFileConflictEvent(
                        goal_id=self._goal_id,
                        file_path=path,
                        blocking_goal_id=lock.goal_id,
                        blocking_loop_id=lock.loop_id,
                        operation_attempted=operation,
                    )
                )
                logger.warning(
                    "File conflict: %s locked by goal %s (loop %s); blocking %s by goal %s",
                    path,
                    lock.goal_id,
                    lock.loop_id,
                    operation,
                    self._goal_id,
                )
                return ToolMessage(
                    content=(
                        f"file_conflict: {path} is locked by goal "
                        f"{lock.goal_id} (loop {lock.loop_id}); "
                        f"choose a different file or retry later"
                    ),
                    tool_call_id=tool_call.get("id"),
                    name=tool_name,
                    status="error",
                )

        # No conflict — acquire lock, emit event, run the tool.
        self._file_registry.acquire_lock(
            path=path,
            goal_id=self._goal_id,
            loop_id=self._loop_id,
            operation=operation,
        )
        await self._internal_bus.emit(
            InternalFileLockedEvent(
                goal_id=self._goal_id,
                loop_id=self._loop_id,
                file_path=path,
                operation=operation,
            )
        )
        logger.debug("Acquired file lock: %s for goal %s", path, self._goal_id)
        return await handler(request)

    async def release_all_locks(self) -> list[str]:
        """Release every lock held by this goal.

        Called explicitly by ``AutopilotService`` when a goal completes or
        fails. Note: ``GoalEngine.complete_goal`` / ``fail_goal`` already
        release locks via ``_release_locks_and_emit``; this helper is here
        for cases where the middleware outlives its goal (cleanup path).
        """
        released = self._file_registry.release_all_for_goal(self._goal_id)
        for path in released:
            logger.debug("Released file lock: %s for goal %s", path, self._goal_id)
        return released
