# IG-047: Unified Thread Management Implementation Guide

**Implementation Guide**: 047
**Title**: Unified Thread Management Implementation
**RFC**: RFC-402
**Status**: Draft
**Created**: 2026-03-22
**Estimated Effort**: 11-16 days

## Overview

This implementation guide provides concrete steps for implementing RFC-402: Unified Thread Management Architecture. The implementation consolidates thread lifecycle operations, adds multi-threading support, and provides consistent APIs across all transport layers.

## Prerequisites

- Read and understand RFC-402
- Familiarity with existing thread storage systems:
  - `DurabilityProtocol` (`src/soothe/protocols/durability.py`)
  - LangGraph checkpointer (`src/soothe/core/resolver/_resolver_infra.py`)
  - `ThreadLogger` (`src/soothe/daemon/thread_logger.py`)
  - `RunArtifactStore` (`src/soothe/core/artifact_store.py`)
- Understanding of daemon protocol (RFC-400)
- Understanding of HTTP REST API (RFC-101)

## Implementation Phases

### Phase 1: Core Infrastructure (2-3 days)

#### Step 1.1: Create Directory Structure

```bash
mkdir -p src/soothe/core/thread
touch src/soothe/core/thread/__init__.py
touch src/soothe/core/thread/manager.py
touch src/soothe/core/thread/executor.py
touch src/soothe/core/thread/models.py
touch src/soothe/core/thread/rate_limiter.py
```

#### Step 1.2: Implement Enhanced Metadata Models

**File**: `src/soothe/core/thread/models.py`

```python
"""Thread management models for RFC-402."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ThreadStats(BaseModel):
    """Thread execution statistics (calculated on demand)."""

    message_count: int = 0
    event_count: int = 0
    artifact_count: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0
    avg_response_time_ms: float = 0.0
    error_count: int = 0
    last_error: str | None = None


class ExecutionContext(BaseModel):
    """Current execution state for running threads."""

    current_goal: str | None = None
    current_step: str | None = None
    iteration: int = 0
    started_at: datetime
    estimated_completion: datetime | None = None


class EnhancedThreadInfo(BaseModel):
    """Complete thread information with statistics."""

    thread_id: str
    status: Literal["idle", "running", "suspended", "archived", "error"]
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    stats: ThreadStats = Field(default_factory=ThreadStats)
    execution_context: ExecutionContext | None = None


class ThreadFilter(BaseModel):
    """Thread filtering criteria."""

    status: Literal["idle", "running", "suspended", "archived", "error"] | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    priority: Literal["low", "normal", "high"] | None = None
    category: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


class ThreadMessage(BaseModel):
    """Single message in thread conversation."""

    timestamp: datetime
    kind: Literal["conversation", "event", "tool_call", "tool_result"]
    role: Literal["user", "assistant", "system"] | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactEntry(BaseModel):
    """Thread artifact metadata."""

    filename: str
    size_bytes: int
    created_at: datetime
    artifact_type: Literal["file", "report", "checkpoint", "other"]
    download_url: str
```

#### Step 1.3: Update DurabilityProtocol Metadata

**File**: `src/soothe/protocols/durability.py`

Add to existing `ThreadMetadata` class (around line 45):

```python
class ThreadMetadata(BaseModel):
    """Enhanced thread metadata with organization tools."""

    tags: list[str] = Field(default_factory=list)
    plan_summary: str | None = None
    policy_profile: str = "standard"

    # NEW FIELDS (RFC-402):
    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high"] = "normal"
    category: str | None = None
```

#### Step 1.4: Implement ThreadContextManager

**File**: `src/soothe/core/thread/manager.py`

```python
"""Thread lifecycle manager for RFC-402."""

from __future__ import annotations

import asyncio
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
        initial_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ThreadInfo:
        """Create a new thread with optional initial message.

        Args:
            initial_message: Optional initial message to send
            metadata: Optional thread metadata

        Returns:
            ThreadInfo for the created thread
        """
        from soothe.protocols.durability import ThreadMetadata

        # Create thread metadata
        thread_metadata = ThreadMetadata(**metadata) if metadata else ThreadMetadata()

        # Create thread in durability protocol
        thread_info = await self._durability.create_thread(metadata=thread_metadata.model_dump())

        logger.info("Created thread %s", thread_info.thread_id)

        # Initialize ThreadLogger
        ThreadLogger(thread_id=thread_info.thread_id)

        # Note: LangGraph checkpointer will be initialized on first query

        return thread_info

    async def resume_thread(
        self,
        thread_id: str,
        load_history: bool = True,
    ) -> ThreadInfo:
        """Resume existing thread, loading history.

        Args:
            thread_id: Thread ID to resume
            load_history: Whether to load full history (always True for now)

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
            raise KeyError(f"Thread {thread_id} not found")

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
        filter: ThreadFilter | None = None,
        include_stats: bool = False,
    ) -> list[EnhancedThreadInfo]:
        """List threads with optional filtering and statistics.

        Args:
            filter: Optional filter criteria
            include_stats: Whether to calculate stats for each thread

        Returns:
            List of EnhancedThreadInfo
        """
        from datetime import datetime

        # Get all threads from durability protocol
        threads = await self._durability.list_threads()

        # Apply filter
        if filter:
            filtered = []
            for t in threads:
                if filter.status and t.get("status") != filter.status:
                    continue
                if filter.tags:
                    thread_tags = t.get("metadata", {}).get("tags", [])
                    if not any(tag in thread_tags for tag in filter.tags):
                        continue
                if filter.labels:
                    thread_labels = t.get("metadata", {}).get("labels", [])
                    if not any(label in thread_labels for label in filter.labels):
                        continue
                if filter.priority:
                    if t.get("metadata", {}).get("priority") != filter.priority:
                        continue
                if filter.category:
                    if t.get("metadata", {}).get("category") != filter.category:
                        continue
                # Date filtering
                if filter.created_after or filter.created_before:
                    created = datetime.fromisoformat(t["created_at"])
                    if filter.created_after and created < filter.created_after:
                        continue
                    if filter.created_before and created > filter.created_before:
                        continue
                if filter.updated_after or filter.updated_before:
                    updated = datetime.fromisoformat(t["updated_at"])
                    if filter.updated_after and updated < filter.updated_after:
                        continue
                    if filter.updated_before and updated > filter.updated_before:
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
        try:
            await self._durability.archive_thread(thread_id)
        except Exception:
            pass  # Thread may already be archived

        # Delete run directory
        run_dir = Path(SOOTHE_HOME).expanduser() / "runs" / thread_id
        if run_dir.exists():
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
        messages = []
        for record in records[offset : offset + limit]:
            if record.get("kind") == "conversation":
                messages.append(
                    ThreadMessage(
                        timestamp=record.get("timestamp"),
                        kind="conversation",
                        role=record.get("role"),
                        content=record.get("text", ""),
                        metadata=record,
                    )
                )

        return messages

    async def get_thread_artifacts(self, thread_id: str) -> list[ArtifactEntry]:
        """Get list of artifacts produced by thread.

        Args:
            thread_id: Thread ID

        Returns:
            List of ArtifactEntry
        """
        from datetime import datetime

        run_dir = Path(SOOTHE_HOME).expanduser() / "runs" / thread_id
        if not run_dir.exists():
            return []

        artifacts = []
        for file_path in run_dir.iterdir():
            if file_path.is_file() and not file_path.name.endswith(".jsonl"):
                stat = file_path.stat()
                artifacts.append(
                    ArtifactEntry(
                        filename=file_path.name,
                        size_bytes=stat.st_size,
                        created_at=datetime.fromtimestamp(stat.st_ctime),
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
```

#### Step 1.5: Implement API Rate Limiter

**File**: `src/soothe/core/thread/rate_limiter.py`

```python
"""API rate limiting for multi-threaded execution."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator


class APIRateLimiter:
    """Rate limiter for API calls across all threads."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 90000,
    ) -> None:
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum API requests per minute
            tokens_per_minute: Maximum tokens per minute
        """
        self._rpm_limit = requests_per_minute
        self._tpm_limit = tokens_per_minute
        # Semaphore for request limiting (simplified, not token-aware)
        self._request_semaphore = asyncio.Semaphore(requests_per_minute // 60)

    @asynccontextmanager
    async def acquire(self, estimated_tokens: int = 1000) -> AsyncGenerator[None]:
        """Acquire rate limit permit.

        Args:
            estimated_tokens: Estimated tokens for this request (not used in simplified version)

        Yields:
            None
        """
        async with self._request_semaphore:
            yield
```

#### Step 1.6: Implement ThreadExecutor

**File**: `src/soothe/core/thread/executor.py`

```python
"""Thread executor for concurrent execution with isolation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator

from soothe.core.thread.rate_limiter import APIRateLimiter
from soothe.daemon.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe.core.runner import SootheRunner

logger = logging.getLogger(__name__)


class ThreadExecutor:
    """Manages concurrent thread execution with isolation."""

    def __init__(
        self,
        runner: SootheRunner,
        max_concurrent_threads: int = 4,
    ) -> None:
        """Initialize thread executor.

        Args:
            runner: SootheRunner instance
            max_concurrent_threads: Maximum concurrent threads
        """
        self._runner = runner
        self._max_concurrent = max_concurrent_threads
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._rate_limiter = APIRateLimiter()

    async def execute_thread(
        self,
        thread_id: str,
        user_input: str,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute query in isolated thread context.

        Args:
            thread_id: Thread ID to execute in
            user_input: User input text
            **kwargs: Additional arguments for runner.astream

        Yields:
            Stream chunks from runner
        """
        # Set thread context
        self._runner.set_current_thread_id(thread_id)

        # Create isolated logger
        thread_logger = ThreadLogger(thread_id=thread_id)

        logger.info("Executing query in thread %s", thread_id)

        # Acquire rate limit permit
        async with self._rate_limiter.acquire():
            try:
                # Execute in isolated context
                async for chunk in self._runner.astream(
                    user_input,
                    thread_id=thread_id,
                    **kwargs,
                ):
                    # Log to thread-specific logger
                    # ThreadLogger will handle the actual logging
                    yield chunk
            except Exception as e:
                logger.error("Error in thread %s: %s", thread_id, e)
                raise
```

#### Step 1.7: Export Thread Module

**File**: `src/soothe/core/thread/__init__.py`

```python
"""Thread management module for RFC-402."""

from soothe.core.thread.executor import ThreadExecutor
from soothe.core.thread.manager import ThreadContextManager
from soothe.core.thread.models import (
    ArtifactEntry,
    EnhancedThreadInfo,
    ExecutionContext,
    ThreadFilter,
    ThreadMessage,
    ThreadStats,
)
from soothe.core.thread.rate_limiter import APIRateLimiter

__all__ = [
    "ThreadContextManager",
    "ThreadExecutor",
    "APIRateLimiter",
    "EnhancedThreadInfo",
    "ThreadStats",
    "ExecutionContext",
    "ThreadFilter",
    "ThreadMessage",
    "ArtifactEntry",
]
```

**File**: `src/soothe/core/__init__.py`

Add to existing exports:

```python
from soothe.core.thread import (
    ThreadContextManager,
    ThreadExecutor,
)

__all__ = [
    # ... existing exports ...
    "ThreadContextManager",
    "ThreadExecutor",
]
```

### Phase 2: Daemon Protocol Extensions (2-3 days)

#### Step 2.1: Add Thread Message Types

**File**: `src/soothe/daemon/protocol_v2.py`

Add thread-specific message validation (around line 100, after existing message types):

```python
# Thread management messages (RFC-402)

def validate_thread_list(msg: dict[str, Any]) -> list[str]:
    """Validate thread_list message."""
    errors = []
    # filter is optional
    if "filter" in msg and not isinstance(msg["filter"], dict):
        errors.append("filter must be an object")
    # include_stats is optional boolean
    if "include_stats" in msg and not isinstance(msg["include_stats"], bool):
        errors.append("include_stats must be a boolean")
    return errors


def validate_thread_create(msg: dict[str, Any]) -> list[str]:
    """Validate thread_create message."""
    errors = []
    # initial_message is optional string
    if "initial_message" in msg and not isinstance(msg["initial_message"], str):
        errors.append("initial_message must be a string")
    # metadata is optional object
    if "metadata" in msg and not isinstance(msg["metadata"], dict):
        errors.append("metadata must be an object")
    return errors


def validate_thread_get(msg: dict[str, Any]) -> list[str]:
    """Validate thread_get message."""
    errors = []
    if "thread_id" not in msg:
        errors.append("thread_get message missing required field: thread_id")
    elif not isinstance(msg["thread_id"], str):
        errors.append("thread_id must be a string")
    return errors


def validate_thread_archive(msg: dict[str, Any]) -> list[str]:
    """Validate thread_archive message."""
    errors = []
    if "thread_id" not in msg:
        errors.append("thread_archive message missing required field: thread_id")
    elif not isinstance(msg["thread_id"], str):
        errors.append("thread_id must be a string")
    return errors


def validate_thread_delete(msg: dict[str, Any]) -> list[str]:
    """Validate thread_delete message."""
    errors = []
    if "thread_id" not in msg:
        errors.append("thread_delete message missing required field: thread_id")
    elif not isinstance(msg["thread_id"], str):
        errors.append("thread_id must be a string")
    return errors


def validate_thread_messages(msg: dict[str, Any]) -> list[str]:
    """Validate thread_messages message."""
    errors = []
    if "thread_id" not in msg:
        errors.append("thread_messages message missing required field: thread_id")
    elif not isinstance(msg["thread_id"], str):
        errors.append("thread_id must be a string")
    # limit and offset are optional integers
    if "limit" in msg and not isinstance(msg["limit"], int):
        errors.append("limit must be an integer")
    if "offset" in msg and not isinstance(msg["offset"], int):
        errors.append("offset must be an integer")
    return errors


def validate_thread_artifacts(msg: dict[str, Any]) -> list[str]:
    """Validate thread_artifacts message."""
    errors = []
    if "thread_id" not in msg:
        errors.append("thread_artifacts message missing required field: thread_id")
    elif not isinstance(msg["thread_id"], str):
        errors.append("thread_id must be a string")
    return errors


# Add to VALIDATORS dictionary
VALIDATORS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    # ... existing validators ...
    "thread_list": validate_thread_list,
    "thread_create": validate_thread_create,
    "thread_get": validate_thread_get,
    "thread_archive": validate_thread_archive,
    "thread_delete": validate_thread_delete,
    "thread_messages": validate_thread_messages,
    "thread_artifacts": validate_thread_artifacts,
}
```

#### Step 2.2: Implement Thread Message Handlers

**File**: `src/soothe/daemon/_handlers.py`

Add thread message handlers (around line 400, after existing handlers):

```python
# Thread management handlers (RFC-402)

async def _handle_thread_list(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_list message."""
    from soothe.core.thread import ThreadFilter

    filter_data = msg.get("filter")
    thread_filter = None
    if filter_data:
        thread_filter = ThreadFilter(**filter_data)

    include_stats = msg.get("include_stats", False)

    threads = await self._thread_manager.list_threads(
        filter=thread_filter,
        include_stats=include_stats,
    )

    await self._broadcast({
        "type": "thread_list_response",
        "threads": [t.model_dump(mode="json") for t in threads],
        "total": len(threads),
    })


async def _handle_thread_create(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_create message."""
    initial_message = msg.get("initial_message")
    metadata = msg.get("metadata")

    thread_info = await self._thread_manager.create_thread(
        initial_message=initial_message,
        metadata=metadata,
    )

    await self._broadcast({
        "type": "thread_created",
        "thread_id": thread_info.thread_id,
        "status": thread_info.status,
    })


async def _handle_thread_get(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_get message."""
    thread_id = msg["thread_id"]

    try:
        thread = await self._thread_manager.get_thread(thread_id)
        await self._broadcast({
            "type": "thread_get_response",
            "thread": thread.model_dump(mode="json"),
        })
    except KeyError:
        await self._broadcast({
            "type": "error",
            "code": "THREAD_NOT_FOUND",
            "message": f"Thread {thread_id} not found",
        })


async def _handle_thread_archive(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_archive message."""
    thread_id = msg["thread_id"]

    try:
        await self._thread_manager.archive_thread(thread_id)
        await self._broadcast({
            "type": "thread_operation_ack",
            "operation": "archive",
            "thread_id": thread_id,
            "success": True,
            "message": "Thread archived successfully",
        })
    except Exception as e:
        await self._broadcast({
            "type": "thread_operation_ack",
            "operation": "archive",
            "thread_id": thread_id,
            "success": False,
            "message": str(e),
        })


async def _handle_thread_delete(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_delete message."""
    thread_id = msg["thread_id"]

    try:
        await self._thread_manager.delete_thread(thread_id)
        await self._broadcast({
            "type": "thread_operation_ack",
            "operation": "delete",
            "thread_id": thread_id,
            "success": True,
            "message": "Thread deleted successfully",
        })
    except Exception as e:
        await self._broadcast({
            "type": "thread_operation_ack",
            "operation": "delete",
            "thread_id": thread_id,
            "success": False,
            "message": str(e),
        })


async def _handle_thread_messages(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_messages message."""
    thread_id = msg["thread_id"]
    limit = msg.get("limit", 100)
    offset = msg.get("offset", 0)

    try:
        messages = await self._thread_manager.get_thread_messages(
            thread_id,
            limit=limit,
            offset=offset,
        )
        await self._broadcast({
            "type": "thread_list_response",  # Reusing response type
            "thread_id": thread_id,
            "messages": [m.model_dump(mode="json") for m in messages],
            "limit": limit,
            "offset": offset,
        })
    except KeyError:
        await self._broadcast({
            "type": "error",
            "code": "THREAD_NOT_FOUND",
            "message": f"Thread {thread_id} not found",
        })


async def _handle_thread_artifacts(
    self,
    msg: dict[str, Any],
) -> None:
    """Handle thread_artifacts message."""
    thread_id = msg["thread_id"]

    try:
        artifacts = await self._thread_manager.get_thread_artifacts(thread_id)
        await self._broadcast({
            "type": "thread_list_response",  # Reusing response type
            "thread_id": thread_id,
            "artifacts": [a.model_dump(mode="json") for a in artifacts],
        })
    except KeyError:
        await self._broadcast({
            "type": "error",
            "code": "THREAD_NOT_FOUND",
            "message": f"Thread {thread_id} not found",
        })
```

Update `_handle_client_message` method to route new message types:

```python
async def _handle_client_message(
    self,
    client: _ClientConn | None,
    msg: dict[str, Any],
) -> None:
    """Handle client message."""
    msg_type = msg.get("type", "")

    # ... existing handlers ...

    # Thread management handlers (RFC-402)
    elif msg_type == "thread_list":
        await self._handle_thread_list(msg)
    elif msg_type == "thread_create":
        await self._handle_thread_create(msg)
    elif msg_type == "thread_get":
        await self._handle_thread_get(msg)
    elif msg_type == "thread_archive":
        await self._handle_thread_archive(msg)
    elif msg_type == "thread_delete":
        await self._handle_thread_delete(msg)
    elif msg_type == "thread_messages":
        await self._handle_thread_messages(msg)
    elif msg_type == "thread_artifacts":
        await self._handle_thread_artifacts(msg)
    # ... rest of existing handlers ...
```

#### Step 2.3: Initialize ThreadContextManager in Daemon

**File**: `src/soothe/daemon/server.py`

Add ThreadContextManager initialization (around line 150, in `__init__` method):

```python
from soothe.core.thread import ThreadContextManager

class SootheDaemon:
    def __init__(self, config: SootheConfig) -> None:
        # ... existing initialization ...

        # Initialize ThreadContextManager
        self._thread_manager = ThreadContextManager(
            durability=self._durability,
            config=config,
        )
```

Pass ThreadContextManager to handlers mixin.

### Phase 3: HTTP REST API Implementation (2 days)

**File**: `src/soothe/daemon/transports/http_rest.py`

Replace all placeholder thread endpoints with working implementations. This is a large file modification, so I'll provide the complete endpoint implementations:

```python
# Add at the top with other imports
from soothe.core.thread import ThreadFilter, ThreadContextManager
from soothe.protocols.durability import ThreadMetadata


class HttpRestTransport(TransportServer):
    def __init__(
        self,
        config: SootheConfig,
        thread_manager: ThreadContextManager,
        message_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        # ... existing initialization ...
        self._thread_manager = thread_manager

    def _setup_routes(self) -> None:
        # ... existing routes ...

        # THREAD MANAGEMENT ENDPOINTS (RFC-402)

        @self._app.get("/api/v1/threads")
        async def list_threads(
            status: str | None = None,
            tags: str | None = None,
            labels: str | None = None,
            priority: str | None = None,
            category: str | None = None,
            created_after: str | None = None,
            created_before: str | None = None,
            updated_after: str | None = None,
            updated_before: str | None = None,
            limit: int = 50,
            offset: int = 0,
            include_stats: bool = False,
        ) -> dict[str, Any]:
            """List threads with filtering.

            Query params:
            - status: Filter by status (idle|running|suspended|archived|error)
            - tags: Comma-separated tags
            - labels: Comma-separated labels
            - priority: Filter by priority (low|normal|high)
            - category: Filter by category
            - created_after: ISO 8601 datetime
            - created_before: ISO 8601 datetime
            - updated_after: ISO 8601 datetime
            - updated_before: ISO 8601 datetime
            - limit: Max results (default: 50)
            - offset: Pagination offset
            - include_stats: Include execution stats
            """
            from datetime import datetime

            thread_filter = None
            if any([status, tags, labels, priority, category, created_after, created_before, updated_after, updated_before]):
                thread_filter = ThreadFilter(
                    status=status,
                    tags=tags.split(",") if tags else None,
                    labels=labels.split(",") if labels else None,
                    priority=priority,
                    category=category,
                    created_after=datetime.fromisoformat(created_after) if created_after else None,
                    created_before=datetime.fromisoformat(created_before) if created_before else None,
                    updated_after=datetime.fromisoformat(updated_after) if updated_after else None,
                    updated_before=datetime.fromisoformat(updated_before) if updated_before else None,
                )

            threads = await self._thread_manager.list_threads(
                filter=thread_filter,
                include_stats=include_stats,
            )

            # Apply pagination
            paginated = threads[offset : offset + limit]

            return {
                "threads": [t.model_dump(mode="json") for t in paginated],
                "total": len(threads),
                "limit": limit,
                "offset": offset,
            }

        @self._app.get("/api/v1/threads/{thread_id}")
        async def get_thread(thread_id: str) -> dict[str, Any]:
            """Get thread details."""
            try:
                thread = await self._thread_manager.get_thread(thread_id)
                return {"thread": thread.model_dump(mode="json")}
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found")

        @self._app.post("/api/v1/threads")
        async def create_thread(request: dict[str, Any]) -> dict[str, Any]:
            """Create new thread with optional initial message.

            Request body:
            {
              "initial_message": "Analyze code",  // optional
              "metadata": {                       // optional
                "tags": ["research"],
                "priority": "high",
                "category": "code-review"
              }
            }
            """
            initial_message = request.get("initial_message")
            metadata = request.get("metadata")

            thread = await self._thread_manager.create_thread(
                initial_message=initial_message,
                metadata=metadata,
            )

            return {
                "thread_id": thread.thread_id,
                "status": thread.status,
                "created_at": thread.created_at.isoformat(),
            }

        @self._app.delete("/api/v1/threads/{thread_id}")
        async def delete_thread(
            thread_id: str,
            archive: bool = True,
        ) -> dict[str, Any]:
            """Delete or archive thread.

            Query params:
            - archive: If true, archive; if false, permanently delete (default: true)
            """
            try:
                if archive:
                    await self._thread_manager.archive_thread(thread_id)
                    action = "archived"
                else:
                    await self._thread_manager.delete_thread(thread_id)
                    action = "deleted"

                return {"thread_id": thread_id, "status": action}
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found")

        @self._app.post("/api/v1/threads/{thread_id}/resume")
        async def resume_thread(
            thread_id: str,
            request: dict[str, Any],
        ) -> dict[str, Any]:
            """Resume thread with new message.

            Request body:
            {
              "message": "Continue analysis"  // required
            }
            """
            message = request.get("message")
            if not message:
                raise HTTPException(status_code=400, detail="message field required")

            # Resume thread context
            await self._thread_manager.resume_thread(thread_id)

            # Send message to daemon for execution
            if self._message_handler:
                self._message_handler({
                    "type": "resume_thread",
                    "thread_id": thread_id,
                })
                self._message_handler({
                    "type": "input",
                    "text": message,
                })

            return {
                "thread_id": thread_id,
                "status": "resumed",
                "message": "Thread resumed and processing message",
            }

        @self._app.get("/api/v1/threads/{thread_id}/messages")
        async def get_thread_messages(
            thread_id: str,
            limit: int = 100,
            offset: int = 0,
        ) -> dict[str, Any]:
            """Get thread conversation messages."""
            try:
                messages = await self._thread_manager.get_thread_messages(
                    thread_id,
                    limit=limit,
                    offset=offset,
                )
                return {
                    "thread_id": thread_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "limit": limit,
                    "offset": offset,
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found")

        @self._app.get("/api/v1/threads/{thread_id}/artifacts")
        async def get_thread_artifacts(thread_id: str) -> dict[str, Any]:
            """Get thread artifacts."""
            try:
                artifacts = await self._thread_manager.get_thread_artifacts(thread_id)
                return {
                    "thread_id": thread_id,
                    "artifacts": [a.model_dump(mode="json") for a in artifacts],
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found")

        @self._app.get("/api/v1/threads/{thread_id}/stats")
        async def get_thread_stats(thread_id: str) -> dict[str, Any]:
            """Get thread execution statistics."""
            try:
                stats = await self._thread_manager.get_thread_stats(thread_id)
                return {
                    "thread_id": thread_id,
                    "stats": stats.model_dump(mode="json"),
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found")
```

### Phase 4: CLI Simplification (1 day)

#### Step 4.1: Remove server attach

**File**: `src/soothe/ux/cli/commands/server_cmd.py`

Delete the `server_attach()` function (lines 113-152).

Update the CLI app registration.

#### Step 4.2: Enhance thread continue

**File**: `src/soothe/ux/cli/commands/thread_cmd.py`

Update `thread_continue` function to support `--daemon` and `--new` flags:

```python
def thread_continue(
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID to continue. Omit to continue last active thread."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    daemon: Annotated[
        bool,
        typer.Option("--daemon", help="Attach to running daemon instead of standalone."),
    ] = False,
    new: Annotated[
        bool,
        typer.Option("--new", help="Create a new thread instead of continuing."),
    ] = False,
) -> None:
    """Continue a conversation thread in the TUI.

    Works in two modes:
    1. Standalone (default): Runs agent directly
    2. Daemon mode (--daemon): Connects to running daemon

    Examples:
        soothe thread continue abc123          # Continue thread standalone
        soothe thread continue --daemon abc123 # Continue via daemon
        soothe thread continue --new           # Start new thread
        soothe thread continue                 # Continue last active thread
    """
    from soothe.ux.cli.execution import run_tui
    from soothe.ux.core import load_config
    from soothe.daemon import SootheDaemon

    cfg = load_config(config)

    # Handle --new flag
    if new:
        thread_id = None
    elif not thread_id:
        # Find last active thread
        from soothe.core.runner import SootheRunner

        runner = SootheRunner(cfg)

        async def get_last_thread() -> str | None:
            threads = await runner.list_threads()
            active_threads = [t for t in threads if t.get("status") in ("active", "idle")]
            if not active_threads:
                typer.echo("No active threads found.", err=True)
                sys.exit(1)
            active_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return active_threads[0].get("thread_id")

        thread_id = asyncio.run(get_last_thread())

    # Handle --daemon flag
    if daemon:
        if not SootheDaemon.is_running():
            typer.echo("Error: No daemon running. Start with 'soothe-daemon start'.", err=True)
            sys.exit(1)

        # Connect to daemon and resume thread
        # This will trigger TUI to connect to daemon
        run_tui(cfg, thread_id=thread_id, config_path=config, daemon_mode=True)
    else:
        # Standalone mode (existing behavior)
        run_tui(cfg, thread_id=thread_id, config_path=config, daemon_mode=False)
```

#### Step 4.3: Add new thread commands

**File**: `src/soothe/ux/cli/commands/thread_cmd.py`

Add new functions:

```python
def thread_stats(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread execution statistics.

    Example:
        soothe thread stats abc123
    """
    from soothe.core.runner import SootheRunner
    from soothe.core.thread import ThreadContextManager
    from soothe.ux.core import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _show_stats() -> None:
        manager = ThreadContextManager(runner._durability, cfg)
        stats = await manager.get_thread_stats(thread_id)

        typer.echo(f"Thread: {thread_id}")
        typer.echo(f"Messages: {stats.message_count}")
        typer.echo(f"Events: {stats.event_count}")
        typer.echo(f"Artifacts: {stats.artifact_count}")
        typer.echo(f"Errors: {stats.error_count}")
        if stats.last_error:
            typer.echo(f"Last Error: {stats.last_error}")

    asyncio.run(_show_stats())


def thread_tag(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    tags: Annotated[
        list[str],
        typer.Argument(help="Tags to add/remove."),
    ],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    remove: Annotated[
        bool,
        typer.Option("--remove", help="Remove tags instead of adding."),
    ] = False,
) -> None:
    """Add or remove tags from a thread.

    Examples:
        soothe thread tag abc123 research analysis
        soothe thread tag abc123 research --remove
    """
    from soothe.core.runner import SootheRunner
    from soothe.core.thread import ThreadContextManager
    from soothe.ux.core import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _tag() -> None:
        manager = ThreadContextManager(runner._durability, cfg)
        thread = await manager.get_thread(thread_id)

        # Get current metadata
        metadata = thread.metadata.copy()
        current_tags = set(metadata.get("tags", []))

        if remove:
            current_tags -= set(tags)
        else:
            current_tags |= set(tags)

        metadata["tags"] = list(current_tags)

        # Update metadata via durability protocol
        await runner._durability.update_thread_metadata(thread_id, metadata)

        typer.echo(f"Tags: {', '.join(metadata['tags'])}")

    asyncio.run(_tag())
```

### Phase 5: Multi-Threading Support (3-4 days)

**Note**: This phase involves modifying concurrent execution logic and requires careful testing. Implementation is provided in Step 1.6 (ThreadExecutor).

Key modifications needed:

1. **Thread-safe SootheRunner**: Ensure `set_current_thread_id()` is thread-safe
2. **Concurrent request handling**: Update daemon handlers to support parallel execution
3. **Resource management**: Implement proper cleanup and resource limits

### Phase 6: Testing and Documentation (2-3 days)

#### Unit Tests

**File**: `tests/core/test_thread_manager.py`

```python
"""Tests for ThreadContextManager."""

import pytest
from soothe.core.thread import ThreadContextManager, ThreadFilter
from soothe.protocols.durability import DurabilityProtocol


@pytest.fixture
async def thread_manager(test_config):
    """Create ThreadContextManager for testing."""
    durability = DurabilityProtocol.create(test_config)
    await durability.initialize()
    return ThreadContextManager(durability, test_config)


async def test_create_thread(thread_manager):
    """Test thread creation."""
    thread_info = await thread_manager.create_thread()

    assert thread_info.thread_id
    assert thread_info.status == "idle"


async def test_create_thread_with_metadata(thread_manager):
    """Test thread creation with metadata."""
    metadata = {"tags": ["research"], "priority": "high"}
    thread_info = await thread_manager.create_thread(metadata=metadata)

    assert thread_info.thread_id
    # Metadata should be stored


async def test_resume_thread(thread_manager):
    """Test thread resume loads history."""
    # Create thread
    thread_info = await thread_manager.create_thread()

    # Resume thread
    resumed = await thread_manager.resume_thread(thread_info.thread_id)

    assert resumed.thread_id == thread_info.thread_id


async def test_list_threads_with_filter(thread_manager):
    """Test thread filtering."""
    # Create threads with different tags
    await thread_manager.create_thread(metadata={"tags": ["research"]})
    await thread_manager.create_thread(metadata={"tags": ["analysis"]})

    # Filter by tag
    filter = ThreadFilter(tags=["research"])
    threads = await thread_manager.list_threads(filter=filter)

    assert len(threads) == 1
    assert "research" in threads[0].metadata.get("tags", [])


async def test_get_thread_stats(thread_manager):
    """Test statistics calculation."""
    thread_info = await thread_manager.create_thread()

    stats = await thread_manager.get_thread_stats(thread_info.thread_id)

    assert stats.message_count == 0
    assert stats.artifact_count == 0


async def test_delete_thread(thread_manager):
    """Test thread deletion cleans up all data."""
    thread_info = await thread_manager.create_thread()

    await thread_manager.delete_thread(thread_info.thread_id)

    # Thread should no longer exist
    with pytest.raises(KeyError):
        await thread_manager.get_thread(thread_info.thread_id)
```

#### Integration Tests

**File**: `tests/integration/test_thread_lifecycle.py`

```python
"""Integration tests for thread lifecycle."""

import pytest
from soothe.daemon import DaemonClient


async def test_thread_lifecycle_via_daemon(running_daemon):
    """Test create -> resume -> archive via daemon protocol."""
    client = DaemonClient()
    await client.connect()

    # Create thread
    await client.send_message({
        "type": "thread_create",
        "metadata": {"tags": ["test"]},
    })

    response = await client.read_event()
    assert response["type"] == "thread_created"
    thread_id = response["thread_id"]

    # Get thread
    await client.send_message({
        "type": "thread_get",
        "thread_id": thread_id,
    })

    response = await client.read_event()
    assert response["type"] == "thread_get_response"
    assert response["thread"]["thread_id"] == thread_id

    # Archive thread
    await client.send_message({
        "type": "thread_archive",
        "thread_id": thread_id,
    })

    response = await client.read_event()
    assert response["type"] == "thread_operation_ack"
    assert response["success"] is True

    await client.close()


async def test_thread_continuation_cli(test_config):
    """Test thread continue CLI command."""
    # This would be tested via subprocess or CLI testing framework
    pass
```

## Verification Steps

### 1. CLI Verification

```bash
# Start daemon
soothe-daemon start

# Create and continue thread
soothe thread continue --new
# (interact with agent, then exit)

# List threads
soothe thread list

# Continue last thread
soothe thread continue

# Continue via daemon
soothe thread continue --daemon

# Show thread stats
soothe thread stats <thread_id>

# Add tags
soothe thread tag <thread_id> research analysis
```

### 2. HTTP REST Verification

```bash
# List threads
curl http://localhost:8766/api/v1/threads

# Get specific thread
curl http://localhost:8766/api/v1/threads/<thread_id>

# Create thread
curl -X POST http://localhost:8766/api/v1/threads \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"tags": ["test"]}}'

# Get thread stats
curl http://localhost:8766/api/v1/threads/<thread_id>/stats

# Archive thread
curl -X DELETE http://localhost:8766/api/v1/threads/<thread_id>
```

### 3. Protocol Verification

Connect via Unix socket or WebSocket and send thread messages:

```json
{"type": "thread_list"}
{"type": "thread_create", "metadata": {"tags": ["test"]}}
{"type": "thread_get", "thread_id": "abc123"}
```

### 4. Multi-Threading Verification

Execute multiple threads concurrently and verify:
- No state leakage between threads
- API rate limiting works
- Thread isolation maintained

## Success Criteria

1. ✅ All HTTP REST endpoints functional (not placeholders)
2. ✅ `soothe thread continue --daemon` replaces `soothe thread continue`
3. ✅ Thread statistics calculate correctly
4. ✅ Thread filtering works by status, tags, labels
5. ✅ Multi-threading support with isolation
6. ✅ All existing workflows continue working
7. ✅ Test coverage >80% for new code
8. ✅ Documentation updated

## Rollback Plan

If issues arise:

1. **Phase 1 issues**: Revert core/thread module additions, no impact on existing code
2. **Phase 2 issues**: Disable thread message handlers, existing protocol messages unaffected
3. **Phase 3 issues**: HTTP REST endpoints return to placeholder state
4. **Phase 4 issues**: Restore `server attach` command, `thread continue` works in standalone mode
5. **Phase 5 issues**: Disable concurrent execution, revert to single-threaded mode

## Performance Targets

- Thread list without stats: <100ms
- Thread list with stats: <500ms for 50 threads
- Thread creation: <50ms
- Thread resume: <100ms
- Statistics calculation: <500ms for 1000 messages

## Post-Implementation Tasks

1. Update user guide with new thread commands
2. Create API documentation for HTTP REST endpoints
3. Document multi-threading behavior and limitations
4. Add monitoring/metrics for thread operations
5. Consider thread templates for future RFC