"""DurabilityProtocol -- thread lifecycle management."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


class ThreadMetadata(BaseModel):
    """Metadata associated with a thread.

    Args:
        tags: Categorical tags for filtering.
        plan_summary: Brief summary of the thread's plan (if any).
        policy_profile: Name of the active policy profile.
        labels: User-defined labels for organization.
        priority: Thread priority level.
        category: User-defined category.
    """

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_claude_sessions(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.pop("claude_sessions", None)
        return data

    tags: list[str] = Field(default_factory=list)
    plan_summary: str | None = None
    policy_profile: str = "standard"
    # Enhanced metadata
    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high"] = "normal"
    category: str | None = None


class ThreadInfo(BaseModel):
    """Full information about a thread.

    Args:
        thread_id: Unique thread identifier.
        status: Current lifecycle status.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        metadata: Associated metadata.
    """

    thread_id: str
    status: Literal["active", "suspended", "archived"]
    created_at: datetime
    updated_at: datetime
    metadata: ThreadMetadata = Field(default_factory=ThreadMetadata)


class ThreadFilter(BaseModel):
    """Filter criteria for listing threads.

    Supports both protocol-level filtering (durability backend) and
    manager-level in-memory filtering (ThreadContextManager).

    Protocol-level fields (used by durability backend):
        status, tags, created_after, created_before

    Manager-level fields (used by ThreadContextManager in-memory):
        labels, priority, category, updated_after, updated_before

    Args:
        status: Filter by status.
        tags: Filter by tags (items must have all specified tags).
        labels: Filter by user-defined labels.
        priority: Filter by priority level.
        category: Filter by category.
        created_after: Filter by creation time lower bound.
        created_before: Filter by creation time upper bound.
        updated_after: Filter by update time lower bound.
        updated_before: Filter by update time upper bound.
    """

    status: Literal["active", "suspended", "archived", "idle", "running", "error"] | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    priority: Literal["low", "normal", "high"] | None = None
    category: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


@runtime_checkable
class DurabilityProtocol(Protocol):
    """Protocol for thread lifecycle management.

    State persistence (checkpoints, artifacts) is handled by
    ``RunArtifactStore``.
    """

    async def create_thread(
        self,
        metadata: ThreadMetadata,
        thread_id: str | None = None,
    ) -> ThreadInfo:
        """Create a new thread.

        Args:
            metadata: Initial metadata for the thread.
            thread_id: Optional thread ID. If not provided, a new UUID is generated.
                       Use this to persist a draft thread with its existing ID.

        Returns:
            Information about the created thread.
        """
        ...

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread.

        Args:
            thread_id: The thread to resume.

        Returns:
            Updated thread information.

        Raises:
            KeyError: If the thread does not exist.
        """
        ...

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend an active thread, persisting its state.

        Args:
            thread_id: The thread to suspend.
        """
        ...

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread. Triggers memory consolidation.

        Args:
            thread_id: The thread to archive.
        """
        ...

    async def update_thread_metadata(
        self,
        thread_id: str,
        metadata: dict[str, Any] | ThreadMetadata,
    ) -> None:
        """Update thread metadata (partial update).

        Merges the provided metadata with existing metadata.
        Only updates fields that are present in the new metadata.

        Args:
            thread_id: Thread ID to update.
            metadata: New metadata to merge. Can be dict or ThreadMetadata.

        Raises:
            KeyError: If thread not found.
        """
        ...

    async def get_thread(self, thread_id: str) -> ThreadInfo | None:
        """Load thread information without changing lifecycle status.

        Args:
            thread_id: Thread ID to load.

        Returns:
            ThreadInfo if found, else ``None``.
        """
        ...

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching a filter.

        Args:
            thread_filter: Optional filter criteria.

        Returns:
            Matching threads.
        """
        ...
