"""File Lock Middleware for Autopilot mode (RFC-222, IG-295).

This middleware enforces file lock conflicts across AgentLoop workers
in autopilot mode. Intercepts file operation tools (edit_file, write_file,
delete_file) and checks FileLockRegistry for conflicts.

Key Principle: Same loop editing same file → ALLOW.
Different loop editing locked file → BLOCK → raise FileConflictError.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.events.internal_bus import get_internal_bus
from soothe.core.events.internal_events import (
    InternalFileConflictEvent,
    InternalFileLockedEvent,
)
from soothe.core.goal_engine.file_lock_registry import FileConflictError, FileLockRegistry

logger = logging.getLogger(__name__)


class FileLockMiddleware:
    """Middleware for file lock conflict resolution in autopilot mode.

    Intercepts file operation tool calls and checks FileLockRegistry
    for conflicts with other AgentLoop workers.

    Usage:
        # In AutopilotService when creating AgentLoop
        middleware = FileLockMiddleware(
            file_registry=goal_engine._file_registry,
            loop_id=loop.loop_id,
            goal_id=goal.id,
        )
        agent_loop.add_middleware(middleware)

    Args:
        file_registry: FileLockRegistry from GoalEngine.
        loop_id: Current loop's ID.
        goal_id: Current goal's ID.
        internal_bus: Internal EventBus for lock events.
    """

    def __init__(
        self,
        file_registry: FileLockRegistry,
        loop_id: str,
        goal_id: str,
        internal_bus: Any | None = None,
    ) -> None:
        """Initialize FileLockMiddleware.

        Args:
            file_registry: FileLockRegistry from GoalEngine.
            loop_id: Current loop's ID.
            goal_id: Current goal's ID.
            internal_bus: Internal EventBus (uses singleton if None).
        """
        self._file_registry = file_registry
        self._loop_id = loop_id
        self._goal_id = goal_id
        self._internal_bus = internal_bus or get_internal_bus()

    async def intercept_tool_call(self, tool_name: str, tool_input: dict) -> dict:
        """Intercept tool call and check for file conflicts.

        Args:
            tool_name: Name of the tool being called.
            tool_input: Tool input arguments.

        Returns:
            Modified tool_input (unchanged if no conflict).

        Raises:
            FileConflictError: If file locked by different loop.
        """
        # Only intercept file operation tools
        if tool_name not in ("edit_file", "write_file", "delete_file", "read_file"):
            return tool_input

        # Extract file path from tool input
        path = self._extract_path(tool_name, tool_input)
        if not path:
            return tool_input

        # Read operations don't need locking (read-only)
        if tool_name == "read_file":
            return tool_input

        operation = self._map_operation(tool_name)

        # Check if file is locked by a different loop
        if self._file_registry.is_locked_by_other(path, self._loop_id):
            lock = self._file_registry.get_lock(path)
            if lock:
                # Emit conflict event
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
                    "File conflict: %s locked by goal %s (loop %s)",
                    path,
                    lock.goal_id,
                    lock.loop_id,
                )

                # Raise error for AgentLoop to handle (replan or wait)
                raise FileConflictError(
                    file_path=path,
                    goal_id=self._goal_id,
                    blocking_goal_id=lock.goal_id,
                    blocking_loop_id=lock.loop_id,
                )

        # No conflict - acquire lock and emit event
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

        # Track locked file in goal state
        self._track_locked_file(path)

        return tool_input

    def _extract_path(self, tool_name: str, tool_input: dict) -> str | None:
        """Extract file path from tool input.

        Args:
            tool_name: Tool name.
            tool_input: Tool input dict.

        Returns:
            File path if found, None otherwise.
        """
        # Standard path field names
        path_keys = ("path", "file_path", "filepath", "file")

        for key in path_keys:
            if key in tool_input:
                return str(tool_input[key])

        return None

    def _map_operation(self, tool_name: str) -> str:
        """Map tool name to operation type.

        Args:
            tool_name: Tool name.

        Returns:
            Operation type string.
        """
        if tool_name == "edit_file":
            return "edit"
        elif tool_name == "write_file":
            return "write"
        elif tool_name == "delete_file":
            return "delete"
        else:
            return "edit"

    def _track_locked_file(self, path: str) -> None:
        """Track locked file in goal state (for later release).

        This is called when lock is acquired. GoalEngine uses
        this to release locks on goal completion.

        Args:
            path: Locked file path.
        """
        # This hook exists for future integration with Goal model
        # Goal.locked_files will be updated by GoalEngine
        pass

    async def release_all_locks(self) -> list[str]:
        """Release all locks held by this goal.

        Called by AgentLoop when goal completes or fails.

        Returns:
            List of released file paths.
        """
        released = self._file_registry.release_all_for_goal(self._goal_id)

        for path in released:
            logger.debug("Released file lock: %s for goal %s", path, self._goal_id)

        return released


def create_file_lock_middleware(
    file_registry: FileLockRegistry,
    loop_id: str,
    goal_id: str,
) -> FileLockMiddleware:
    """Factory function for FileLockMiddleware.

    Args:
        file_registry: FileLockRegistry from GoalEngine.
        loop_id: Current loop's ID.
        goal_id: Current goal's ID.

    Returns:
        FileLockMiddleware instance.
    """
    return FileLockMiddleware(
        file_registry=file_registry,
        loop_id=loop_id,
        goal_id=goal_id,
    )
