"""Thread lifecycle manager for RFC-402."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from soothe.config import SOOTHE_HOME
from soothe.logging import ThreadLogger

from soothe.core.thread.models import (
    ArtifactEntry,
    EnhancedThreadInfo,
    ThreadFilter,
    ThreadMessage,
    ThreadStats,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.mcp.loader import MCPSessionManager

    from soothe.protocols.durability import DurabilityProtocol, ThreadInfo

logger = logging.getLogger(__name__)


class ThreadContextManager:
    """Centralized thread lifecycle management.

    Coordinates:
    - DurabilityProtocol (metadata)
    - MCP session lifecycle
    - LangGraph checkpointer (chat history)
    - ThreadLogger (conversation logs)
    - RunArtifactStore (artifacts)
    """

    _mcp_managers: ClassVar[dict[str, MCPSessionManager]] = {}

    def __init__(
        self,
        durability: DurabilityProtocol,
        config: SootheConfig,
    ) -> None:
        """Initialize thread manager.

        Args:
            durability: Durability protocol instance for metadata
            config: Soothe configuration
        """
        self._durability = durability
        self._config = config

    async def create_thread(
        self,
        metadata: dict[str, Any] | None = None,
        thread_id: str | None = None,
        **_kwargs: Any,
    ) -> ThreadInfo:
        """Create a new thread with optional initial message.

        Args:
            metadata: Optional thread metadata
            thread_id: Optional thread ID. If not provided, a new UUID is generated.
                       Use this to persist a draft thread with its existing ID.
            **_kwargs: Additional arguments (ignored, for compatibility)

        Returns:
            ThreadInfo for the created thread
        """
        from soothe.protocols.durability import ThreadMetadata

        # Convert dict to ThreadMetadata if needed
        thread_metadata = ThreadMetadata(**metadata) if metadata else ThreadMetadata()

        # Create thread in durability protocol
        thread_info = await self._durability.create_thread(
            metadata=thread_metadata,
            thread_id=thread_id,
        )

        logger.info("Created thread %s", thread_info.thread_id)

        await self._ensure_mcp_session(thread_info.thread_id)

        # Initialize ThreadLogger
        ThreadLogger(thread_id=thread_info.thread_id)

        # Note: LangGraph checkpointer will be initialized on first query

        return thread_info

    async def resume_thread(
        self,
        thread_id: str,
        *,
        _load_history: bool = True,
    ) -> ThreadInfo:
        """Resume existing thread, loading history.

        Args:
            thread_id: Thread ID to resume
            _load_history: Whether to load full history (always True for now)

        Returns:
            ThreadInfo for the resumed thread

        Raises:
            KeyError: If thread not found
        """
        try:
            # Resume thread in durability protocol
            thread_info = await self._durability.resume_thread(thread_id)
        except KeyError:
            # Graceful degradation: recover missing metadata when run artifacts exist.
            thread_info = await self._recover_missing_thread_metadata(thread_id)

        logger.info("Resumed thread %s", thread_id)

        await self._ensure_mcp_session(thread_info.thread_id)

        # LangGraph checkpointer automatically loads history via thread_id config
        # ThreadLogger will continue appending to existing log

        return thread_info

    async def _recover_missing_thread_metadata(self, thread_id: str) -> ThreadInfo:
        """Recover thread metadata when durability entry is missing but run data exists.

        Supports prefix matching - if the provided thread_id is a prefix,
        finds the matching thread from the runs directory.

        Args:
            thread_id: Requested thread ID (full or prefix).

        Returns:
            Recovered ThreadInfo.

        Raises:
            KeyError: If no durable metadata and no run artifacts exist.
        """
        from soothe.protocols.durability import ThreadInfo, ThreadMetadata

        def _find_matching_thread() -> str | None:
            """Find a thread ID matching the provided ID or prefix."""
            runs_dir = Path(SOOTHE_HOME).expanduser() / "runs"
            if not runs_dir.exists():
                return None

            # First try exact match
            exact_dir = runs_dir / thread_id
            if exact_dir.exists() and exact_dir.is_dir():
                return thread_id

            # Try prefix matching
            matching = [
                subdir.name
                for subdir in runs_dir.iterdir()
                if subdir.is_dir() and subdir.name.startswith(thread_id)
            ]

            if not matching:
                return None

            # Sort by modification time (most recent first) and return first match
            matching.sort(
                key=lambda x: (runs_dir / x).stat().st_mtime,
                reverse=True,
            )
            return matching[0]

        matched_thread_id = await asyncio.to_thread(_find_matching_thread)
        if not matched_thread_id:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)

        recovered = ThreadInfo(
            thread_id=matched_thread_id,
            status="active",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
            metadata=ThreadMetadata(),
        )

        # Persist recovered metadata when durability implementation exposes internal store/index helpers.
        store = getattr(self._durability, "_store", None)
        update_index = getattr(self._durability, "_update_thread_index", None)
        if store and callable(getattr(store, "save", None)):
            store.save(f"thread:{matched_thread_id}", recovered.model_dump(mode="json"))
            if callable(update_index):
                update_index(matched_thread_id, action="add")

        logger.info(
            "Recovered missing durability metadata for thread %s from run artifacts",
            matched_thread_id,
        )
        return recovered

    async def get_thread(self, thread_id: str) -> EnhancedThreadInfo:
        """Get enhanced thread information with statistics.

        Args:
            thread_id: Thread ID to get

        Returns:
            EnhancedThreadInfo with stats

        Raises:
            KeyError: If thread not found
        """
        # Get basic thread info
        threads = await self._durability.list_threads()
        thread_data = None
        for t in threads:
            if t.thread_id == thread_id:
                thread_data = t
                break

        if not thread_data:
            error_msg = f"Thread {thread_id} not found"
            raise KeyError(error_msg)

        # Calculate stats
        stats = await self.get_thread_stats(thread_id)

        # Map status from ThreadInfo to EnhancedThreadInfo
        status_mapping = {
            "active": "idle",
            "suspended": "suspended",
            "archived": "archived",
        }
        mapped_status = status_mapping.get(thread_data.status, "idle")

        return EnhancedThreadInfo(
            thread_id=thread_id,
            status=mapped_status,
            created_at=thread_data.created_at,
            updated_at=thread_data.updated_at,
            last_activity_at=thread_data.updated_at,
            metadata=thread_data.metadata.model_dump() if thread_data.metadata else {},
            stats=stats,
        )

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
        *,
        include_stats: bool = False,
        include_last_message: bool = False,
    ) -> list[EnhancedThreadInfo]:
        """List threads with optional filtering and statistics.

        Args:
            thread_filter: Optional filter criteria
            include_stats: Whether to calculate stats for each thread
            include_last_message: Whether to include the last human message

        Returns:
            List of EnhancedThreadInfo
        """
        # Get all threads from durability protocol
        threads = await self._durability.list_threads()

        # Apply filter
        if thread_filter:
            # Map EnhancedThreadInfo status to ThreadInfo status for filtering
            # EnhancedThreadInfo: idle, running, suspended, archived, error
            # ThreadInfo: active, suspended, archived
            status_reverse_mapping = {
                "idle": "active",
                "running": "active",
                "suspended": "suspended",
                "archived": "archived",
                "error": "active",  # error state is tracked in metadata, not status
            }
            filter_status = (
                status_reverse_mapping.get(thread_filter.status) if thread_filter.status else None
            )

            filtered = []
            for t in threads:
                if filter_status and t.status != filter_status:
                    continue
                if thread_filter.tags:
                    thread_tags = t.metadata.tags if t.metadata else []
                    if not any(tag in thread_tags for tag in thread_filter.tags):
                        continue
                if thread_filter.labels:
                    thread_labels = t.metadata.labels if t.metadata else []
                    if not any(label in thread_labels for label in thread_filter.labels):
                        continue
                if thread_filter.priority:
                    thread_priority = t.metadata.priority if t.metadata else "normal"
                    if thread_priority != thread_filter.priority:
                        continue
                if thread_filter.category:
                    thread_category = t.metadata.category if t.metadata else None
                    if thread_category != thread_filter.category:
                        continue
                # Date filtering
                if thread_filter.created_after or thread_filter.created_before:
                    if thread_filter.created_after and t.created_at < thread_filter.created_after:
                        continue
                    if thread_filter.created_before and t.created_at > thread_filter.created_before:
                        continue
                if thread_filter.updated_after or thread_filter.updated_before:
                    if thread_filter.updated_after and t.updated_at < thread_filter.updated_after:
                        continue
                    if thread_filter.updated_before and t.updated_at > thread_filter.updated_before:
                        continue
                filtered.append(t)
            threads = filtered

        # Build enhanced info list
        enhanced_threads = []
        for t in threads:
            stats = ThreadStats()
            if include_stats:
                stats = await self.get_thread_stats(t.thread_id)

            # Get last human message if requested
            last_human_message = None
            if include_last_message:
                last_human_message = await self._get_last_human_message(t.thread_id)

            # Map status from ThreadInfo to EnhancedThreadInfo
            # ThreadInfo has: active, suspended, archived
            # EnhancedThreadInfo has: idle, running, suspended, archived, error
            status_mapping = {
                "active": "idle",
                "suspended": "suspended",
                "archived": "archived",
            }
            mapped_status = status_mapping.get(t.status, "idle")

            enhanced_threads.append(
                EnhancedThreadInfo(
                    thread_id=t.thread_id,
                    status=mapped_status,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    last_activity_at=t.updated_at,
                    metadata=t.metadata.model_dump() if t.metadata else {},
                    stats=stats,
                    last_human_message=last_human_message,
                )
            )

        return enhanced_threads

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend a thread after cleaning up MCP sessions.

        Args:
            thread_id: Thread ID to suspend
        """
        await self._cleanup_mcp_session(thread_id)
        await self._durability.suspend_thread(thread_id)
        logger.info("Suspended thread %s", thread_id)

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread, making it read-only.

        Args:
            thread_id: Thread ID to archive

        Raises:
            KeyError: If thread not found
        """
        await self._cleanup_mcp_session(thread_id)
        await self._durability.archive_thread(thread_id)
        logger.info("Archived thread %s", thread_id)

    async def delete_thread(self, thread_id: str) -> None:
        """Permanently delete thread and all associated data.

        Args:
            thread_id: Thread ID to delete

        Raises:
            KeyError: If thread not found
        """
        import shutil

        thread_key = f"thread:{thread_id}"
        store = getattr(self._durability, "_store", None)
        if store is None:
            msg = f"Thread {thread_id} not found"
            raise KeyError(msg)

        thread_data = await asyncio.to_thread(store.load, thread_key)
        if thread_data is None:
            msg = f"Thread {thread_id} not found"
            raise KeyError(msg)

        # Remove durability metadata/state and index entries
        await asyncio.to_thread(store.delete, thread_key)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(store.delete, f"state:{thread_id}")
        update_index = getattr(self._durability, "_update_thread_index", None)
        if callable(update_index):
            update_index(thread_id, action="remove")

        # Delete run directory
        def get_run_dir() -> Path:
            return Path(SOOTHE_HOME).expanduser() / "runs" / thread_id

        run_dir = await asyncio.to_thread(get_run_dir)
        run_dir_exists = await asyncio.to_thread(run_dir.exists)
        if run_dir_exists:
            await asyncio.to_thread(shutil.rmtree, run_dir)

        logger.info("Deleted thread %s", thread_id)

    async def get_thread_messages(
        self,
        thread_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ThreadMessage]:
        """Get thread conversation history.

        Args:
            thread_id: Thread ID
            limit: Maximum messages to return
            offset: Pagination offset

        Returns:
            List of ThreadMessage
        """
        logger_instance = ThreadLogger(thread_id=thread_id)
        records = logger_instance.read_recent_records(limit=limit + offset)

        # Convert to ThreadMessage format
        return [
            ThreadMessage(
                timestamp=record.get("timestamp"),
                kind="conversation",
                role=record.get("role"),
                content=record.get("text", ""),
                metadata=record,
            )
            for record in records[offset : offset + limit]
            if record.get("kind") == "conversation"
        ]

    async def get_thread_artifacts(self, thread_id: str) -> list[ArtifactEntry]:
        """Get list of artifacts produced by thread.

        Args:
            thread_id: Thread ID

        Returns:
            List of ArtifactEntry
        """
        from datetime import UTC, datetime

        def get_run_dir() -> Path:
            return Path(SOOTHE_HOME).expanduser() / "runs" / thread_id

        run_dir = await asyncio.to_thread(get_run_dir)
        run_dir_exists = await asyncio.to_thread(run_dir.exists)
        if not run_dir_exists:
            return []

        artifacts = []
        for file_path in await asyncio.to_thread(list, run_dir.iterdir()):
            is_file = await asyncio.to_thread(file_path.is_file)
            if is_file and not file_path.name.endswith(".jsonl"):
                stat = await asyncio.to_thread(file_path.stat)
                artifacts.append(
                    ArtifactEntry(
                        filename=file_path.name,
                        size_bytes=stat.st_size,
                        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                        artifact_type="file",  # Could be enhanced to detect type
                        download_url=f"/api/v1/files/{file_path.name}",
                    )
                )

        return artifacts

    async def get_thread_stats(self, thread_id: str) -> ThreadStats:
        """Get thread execution statistics.

        Args:
            thread_id: Thread ID

        Returns:
            ThreadStats with calculated values
        """
        logger_instance = ThreadLogger(thread_id=thread_id)
        records = logger_instance.read_recent_records(limit=10000)  # Large limit for accuracy

        # Count messages and events
        message_count = sum(1 for r in records if r.get("kind") == "conversation")
        event_count = sum(1 for r in records if r.get("kind") == "event")

        # Count artifacts
        artifacts = await self.get_thread_artifacts(thread_id)
        artifact_count = len(artifacts)

        # Count errors
        error_count = sum(
            1
            for r in records
            if r.get("kind") == "event" and "error" in str(r.get("data", {})).lower()
        )

        last_error = None
        if error_count > 0:
            # Find last error
            for r in reversed(records):
                if r.get("kind") == "event" and "error" in str(r.get("data", {})).lower():
                    last_error = str(r.get("data", {}).get("message", "Unknown error"))
                    break

        return ThreadStats(
            message_count=message_count,
            event_count=event_count,
            artifact_count=artifact_count,
            error_count=error_count,
            last_error=last_error,
        )

    async def _ensure_mcp_session(self, thread_id: str) -> None:
        """Ensure MCP sessions are loaded for a thread when configured."""
        if thread_id in self._mcp_managers or not self._config.mcp_servers:
            return

        try:
            from soothe.mcp.loader import load_mcp_tools

            _, manager = await load_mcp_tools(self._config.mcp_servers)
            self._mcp_managers[thread_id] = manager
            logger.info("Loaded MCP sessions for thread %s", thread_id)
        except Exception:
            logger.warning("Failed to load MCP sessions for thread %s", thread_id, exc_info=True)

    async def _cleanup_mcp_session(self, thread_id: str) -> None:
        """Clean up MCP sessions associated with a thread."""
        manager = self._mcp_managers.pop(thread_id, None)
        if manager is None:
            return

        try:
            await manager.cleanup()
            logger.info("Cleaned up MCP sessions for thread %s", thread_id)
        except Exception:
            logger.warning(
                "Failed to clean up MCP sessions for thread %s", thread_id, exc_info=True
            )

    async def _get_last_human_message(self, thread_id: str) -> str | None:
        """Get the last human message from thread conversation history.

        Args:
            thread_id: Thread ID

        Returns:
            Last human message text or None if not found
        """
        logger_instance = ThreadLogger(thread_id=thread_id)
        records = logger_instance.read_recent_records(limit=100)

        # Find last human message in reverse order
        for record in reversed(records):
            if record.get("kind") == "conversation" and record.get("role") == "user":
                return record.get("text", "")

        return None
