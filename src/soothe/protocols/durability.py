"""DurabilityProtocol -- thread lifecycle management (RFC-0002 Module 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ThreadMetadata(BaseModel):
    """Metadata associated with a thread.

    Args:
        tags: Categorical tags for filtering.
        plan_summary: Brief summary of the thread's plan (if any).
        policy_profile: Name of the active policy profile.
        labels: User-defined labels for organization (RFC-402).
        priority: Thread priority level (RFC-402).
        category: User-defined category (RFC-402).
    """

    tags: list[str] = Field(default_factory=list)
    plan_summary: str | None = None
    policy_profile: str = "standard"
    # RFC-402: Enhanced metadata
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

    Args:
        status: Filter by status.
        tags: Filter by tags (items must have all specified tags).
        created_after: Filter by creation time lower bound.
        created_before: Filter by creation time upper bound.
    """

    status: Literal["active", "suspended", "archived"] | None = None
    tags: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@runtime_checkable
class DurabilityProtocol(Protocol):
    """Protocol for thread lifecycle management.

    State persistence (checkpoints, artifacts) is handled by
    ``RunArtifactStore`` (RFC-0010).
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
