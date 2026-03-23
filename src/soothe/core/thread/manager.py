"""Thread lifecycle manager for RFC-0017."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import SOOTHE_HOME
from soothe.core.thread.models import (
    ArtifactEntry,
    EnhancedThreadInfo,
    ThreadFilter,
    ThreadMessage,
    ThreadStats,
)
from soothe.daemon.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.protocols.durability import DurabilityProtocol, ThreadInfo

logger = logging.getLogger(__name__)


class ThreadContextManager:
    """Centralized thread lifecycle management.

    Coordinates:
    - DurabilityProtocol (metadata)
    - LangGraph checkpointer (chat history)
    - ThreadLogger (conversation logs)
    - RunArtifactStore (artifacts)
    """

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
        **_kwargs: Any,
    ) -> ThreadInfo:
        """Create a new thread with optional initial message.

        Args:
            metadata: Optional thread metadata
            **_kwargs: Additional arguments (ignored, for compatibility)

        Returns:
            ThreadInfo for the created thread
        """
        from soothe.protocols.durability import ThreadMetadata

        # Convert dict to ThreadMetadata if needed
        thread_metadata = ThreadMetadata(**metadata) if metadata else ThreadMetadata()

        # Create thread in durability protocol
        thread_info = await self._durability.create_thread(metadata=thread_metadata)

        logger.info("Created thread %s", thread_info.thread_id)

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
        # Resume thread in durability protocol
        thread_info = await self._durability.resume_thread(thread_id)

        logger.info("Resumed thread %s", thread_id)

        # LangGraph checkpointer automatically loads history via thread_id config
        # ThreadLogger will continue appending to existing log

        return thread_info

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
            if t.get("thread_id") == thread_id:
                thread_data = t
                break

        if not thread_data:
            error_msg = f"Thread {thread_id} not found"
            raise KeyError(error_msg)

        # Calculate stats
        stats = await self.get_thread_stats(thread_id)

        # Build enhanced info
        from datetime import datetime

        return EnhancedThreadInfo(
            thread_id=thread_id,
            status=thread_data.get("status", "idle"),
            created_at=datetime.fromisoformat(thread_data["created_at"]),
            updated_at=datetime.fromisoformat(thread_data["updated_at"]),
            last_activity_at=datetime.fromisoformat(thread_data["updated_at"]),
            metadata=thread_data.get("metadata", {}),
            stats=stats,
        )

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
        *,
        include_stats: bool = False,
    ) -> list[EnhancedThreadInfo]:
        """List threads with optional filtering and statistics.

        Args:
            thread_filter: Optional filter criteria
            include_stats: Whether to calculate stats for each thread

        Returns:
            List of EnhancedThreadInfo
        """
        from datetime import datetime

        # Get all threads from durability protocol
        threads = await self._durability.list_threads()

        # Apply filter
        if thread_filter:
            filtered = []
            for t in threads:
                if thread_filter.status and t.get("status") != thread_filter.status:
                    continue
                if thread_filter.tags:
                    thread_tags = t.get("metadata", {}).get("tags", [])
                    if not any(tag in thread_tags for tag in thread_filter.tags):
                        continue
                if thread_filter.labels:
                    thread_labels = t.get("metadata", {}).get("labels", [])
                    if not any(label in thread_labels for label in thread_filter.labels):
                        continue
                if thread_filter.priority and t.get("metadata", {}).get("priority") != thread_filter.priority:
                    continue
                if thread_filter.category and t.get("metadata", {}).get("category") != thread_filter.category:
                    continue
                # Date filtering
                if thread_filter.created_after or thread_filter.created_before:
                    created = datetime.fromisoformat(t["created_at"])
                    if thread_filter.created_after and created < thread_filter.created_after:
                        continue
                    if thread_filter.created_before and created > thread_filter.created_before:
                        continue
                if thread_filter.updated_after or thread_filter.updated_before:
                    updated = datetime.fromisoformat(t["updated_at"])
                    if thread_filter.updated_after and updated < thread_filter.updated_after:
                        continue
                    if thread_filter.updated_before and updated > thread_filter.updated_before:
                        continue
                filtered.append(t)
            threads = filtered

        # Build enhanced info list
        enhanced_threads = []
        for t in threads:
            stats = ThreadStats()
            if include_stats:
                stats = await self.get_thread_stats(t["thread_id"])

            enhanced_threads.append(
                EnhancedThreadInfo(
                    thread_id=t["thread_id"],
                    status=t.get("status", "idle"),
                    created_at=datetime.fromisoformat(t["created_at"]),
                    updated_at=datetime.fromisoformat(t["updated_at"]),
                    last_activity_at=datetime.fromisoformat(t["updated_at"]),
                    metadata=t.get("metadata", {}),
                    stats=stats,
                )
            )

        return enhanced_threads

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread, making it read-only.

        Args:
            thread_id: Thread ID to archive

        Raises:
            KeyError: If thread not found
        """
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

        # Archive first (soft delete in durability)
        with contextlib.suppress(Exception):
            await self._durability.archive_thread(thread_id)

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
        error_count = sum(1 for r in records if r.get("kind") == "event" and "error" in str(r.get("data", {})).lower())

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
