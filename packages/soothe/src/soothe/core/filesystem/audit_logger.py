"""Audit logging for filesystem operations.

This module provides comprehensive audit logging capabilities for tracking
all filesystem operations, with async support and multiple output backends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AuditLevel(Enum):
    """Audit logging levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEventType(Enum):
    """Types of filesystem audit events."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EDIT = "edit"
    GLOB = "glob"
    GREP = "grep"
    LS = "ls"
    INFO = "info"
    MKDIR = "mkdir"
    MOVE = "move"
    COPY = "copy"
    PERMISSION_DENIED = "permission_denied"
    PATH_TRAVERSAL = "path_traversal"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


@dataclass(frozen=True)
class AuditContext:
    """Context information for audit events.

    Attributes:
        session_id: Unique session identifier.
        user_id: User identifier if available.
        thread_id: Thread/conversation identifier.
        request_id: Request identifier for tracing.
        client_ip: Client IP address if available.
        user_agent: Client user agent if available.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str | None = None
    thread_id: str | None = None
    request_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "request_id": self.request_id,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
        }


@dataclass(frozen=True)
class AuditEvent:
    """Represents a single filesystem audit event.

    Attributes:
        event_id: Unique event identifier.
        timestamp: Event timestamp (ISO 8601 format).
        event_type: Type of filesystem event.
        level: Audit severity level.
        path: Path involved in the operation.
        operation: Operation name.
        success: Whether the operation succeeded.
        duration_ms: Operation duration in milliseconds.
        context: Audit context information.
        details: Additional event details.
        error: Error information if operation failed.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    event_type: AuditEventType = AuditEventType.READ
    level: AuditLevel = AuditLevel.INFO
    path: str | None = None
    operation: str = ""
    success: bool = True
    duration_ms: float = 0.0
    context: AuditContext = field(default_factory=AuditContext)
    details: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "level": self.level.value,
            "path": self.path,
            "operation": self.operation,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "context": self.context.to_dict(),
            "details": self.details,
        }
        if self.error:
            result["error"] = self.error
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


@dataclass
class AuditLoggerConfig:
    """Configuration for audit logging.

    Attributes:
        enabled: Whether audit logging is enabled.
        log_file: Path to audit log file (None for stdout only).
        log_level: Minimum level to log.
        buffer_size: Number of events to buffer before flushing.
        flush_interval_seconds: Seconds between automatic flushes.
        max_file_size_mb: Maximum audit log file size.
        max_backup_files: Number of backup files to keep.
        include_stacktrace: Whether to include stack traces for errors.
        sensitive_patterns: Patterns to redact from logs.
        async_queue_size: Maximum size of async event queue.
    """

    enabled: bool = True
    log_file: Path | None = None
    log_level: AuditLevel = AuditLevel.INFO
    buffer_size: int = 100
    flush_interval_seconds: float = 5.0
    max_file_size_mb: int = 100
    max_backup_files: int = 10
    include_stacktrace: bool = False
    sensitive_patterns: tuple[str, ...] = field(default_factory=tuple)
    async_queue_size: int = 1000

    def should_log(self, level: AuditLevel) -> bool:
        """Check if a level should be logged."""
        level_order = [
            AuditLevel.DEBUG,
            AuditLevel.INFO,
            AuditLevel.WARNING,
            AuditLevel.ERROR,
            AuditLevel.CRITICAL,
        ]
        return level_order.index(level) >= level_order.index(self.log_level)


class AuditLogBackend:
    """Abstract base class for audit log backends."""

    async def write(self, event: AuditEvent) -> None:
        """Write a single event to the backend.

        Args:
            event: Audit event to write.
        """
        raise NotImplementedError

    async def flush(self) -> None:
        """Flush any buffered events."""
        pass

    async def close(self) -> None:
        """Close the backend."""
        pass


class FileBackend(AuditLogBackend):
    """File-based audit log backend."""

    def __init__(self, log_file: Path, max_size_mb: int = 100, max_backups: int = 10) -> None:
        """Initialize file backend.

        Args:
            log_file: Path to log file.
            max_size_mb: Maximum file size in MB before rotation.
            max_backups: Number of backup files to keep.
        """
        self._log_file = Path(log_file)
        self._max_size = max_size_mb * 1024 * 1024
        self._max_backups = max_backups
        self._lock = asyncio.Lock()
        self._buffer: list[str] = []

    async def write(self, event: AuditEvent) -> None:
        """Write event to file."""
        async with self._lock:
            self._buffer.append(event.to_json())
            await self._maybe_flush()

    async def flush(self) -> None:
        """Flush buffered events to file."""
        async with self._lock:
            if not self._buffer:
                return

            await self._rotate_if_needed()

            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    for line in self._buffer:
                        f.write(line + "\n")
                self._buffer.clear()
            except OSError as e:
                logger.error(f"Failed to write audit log: {e}")

    async def _maybe_flush(self) -> None:
        """Flush if buffer is large enough."""
        if len(self._buffer) >= 100:
            await self.flush()

    async def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        try:
            if self._log_file.exists() and self._log_file.stat().st_size > self._max_size:
                # Rotate existing backups
                for i in range(self._max_backups - 1, 0, -1):
                    src = self._log_file.parent / f"{self._log_file.name}.{i}"
                    dst = self._log_file.parent / f"{self._log_file.name}.{i + 1}"
                    if src.exists():
                        src.rename(dst)

                # Rotate current file
                backup = self._log_file.parent / f"{self._log_file.name}.1"
                self._log_file.rename(backup)
        except OSError as e:
            logger.error(f"Failed to rotate audit log: {e}")

    async def close(self) -> None:
        """Close the backend and flush remaining events."""
        await self.flush()


class StructuredLoggingBackend(AuditLogBackend):
    """Backend that writes to Python's structured logging."""

    def __init__(self, logger_name: str = "soothe.audit") -> None:
        """Initialize structured logging backend.

        Args:
            logger_name: Logger name to use.
        """
        self._logger = logging.getLogger(logger_name)

    async def write(self, event: AuditEvent) -> None:
        """Write event via structured logging."""
        log_data = event.to_dict()
        level_map = {
            AuditLevel.DEBUG: self._logger.debug,
            AuditLevel.INFO: self._logger.info,
            AuditLevel.WARNING: self._logger.warning,
            AuditLevel.ERROR: self._logger.error,
            AuditLevel.CRITICAL: self._logger.critical,
        }
        log_func = level_map.get(event.level, self._logger.info)
        log_func(f"AUDIT: {event.event_type.value}", extra={"audit_event": log_data})


class CallbackBackend(AuditLogBackend):
    """Backend that calls a user-provided callback."""

    def __init__(self, callback: Callable[[AuditEvent], None]) -> None:
        """Initialize callback backend.

        Args:
            callback: Function to call with each event.
        """
        self._callback = callback

    async def write(self, event: AuditEvent) -> None:
        """Call the callback with the event."""
        self._callback(event)


class AuditLogger:
    """Async audit logger for filesystem operations.

    This class provides comprehensive audit logging with async support,
    multiple backends, and configurable buffering.

    Example:
        >>> config = AuditLoggerConfig(log_file=Path("audit.log"))
        >>> async with AuditLogger(config) as audit:
        ...     await audit.log_read("/file.txt", success=True)
    """

    def __init__(self, config: AuditLoggerConfig | None = None) -> None:
        """Initialize audit logger.

        Args:
            config: Audit logger configuration.
        """
        self._config = config or AuditLoggerConfig()
        self._backends: list[AuditLogBackend] = []
        self._queue: asyncio.Queue[AuditEvent] | None = None
        self._worker_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._shutdown = False
        self._context: AuditContext = AuditContext()

    async def start(self) -> None:
        """Start the audit logger and initialize backends."""
        if not self._config.enabled:
            return

        # Initialize backends
        if self._config.log_file:
            self._backends.append(
                FileBackend(
                    self._config.log_file,
                    self._config.max_file_size_mb,
                    self._config.max_backup_files,
                )
            )

        # Always add structured logging backend
        self._backends.append(StructuredLoggingBackend())

        # Start async processing
        self._queue = asyncio.Queue(maxsize=self._config.async_queue_size)
        self._worker_task = asyncio.create_task(self._process_queue())
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self) -> None:
        """Stop the audit logger and flush remaining events."""
        if not self._config.enabled:
            return

        self._shutdown = True

        # Signal worker to finish
        if self._queue:
            await self._queue.put(None)  # Sentinel value

        # Wait for worker to finish
        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except TimeoutError:
                self._worker_task.cancel()

        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush all backends
        for backend in self._backends:
            await backend.flush()
            await backend.close()

    def set_context(self, context: AuditContext) -> None:
        """Set the default audit context.

        Args:
            context: Context to use for subsequent events.
        """
        self._context = context

    async def _process_queue(self) -> None:
        """Process events from the async queue."""
        try:
            while not self._shutdown:
                event = await self._queue.get()
                if event is None:  # Sentinel value for shutdown
                    break

                await self._write_to_backends(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Audit queue processing error: {e}")

    async def _periodic_flush(self) -> None:
        """Periodically flush backends."""
        try:
            while not self._shutdown:
                await asyncio.sleep(self._config.flush_interval_seconds)
                for backend in self._backends:
                    await backend.flush()
        except asyncio.CancelledError:
            pass

    async def _write_to_backends(self, event: AuditEvent) -> None:
        """Write event to all backends."""
        for backend in self._backends:
            try:
                await backend.write(event)
            except Exception as e:
                logger.error(f"Failed to write to audit backend: {e}")

    async def _log_event(
        self,
        event_type: AuditEventType,
        level: AuditLevel,
        path: str | None,
        operation: str,
        success: bool,
        duration_ms: float,
        details: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Log an audit event.

        Args:
            event_type: Type of event.
            level: Audit level.
            path: Path involved.
            operation: Operation name.
            success: Whether operation succeeded.
            duration_ms: Operation duration.
            details: Additional details.
            error: Error if operation failed.
        """
        if not self._config.enabled:
            return

        if not self._config.should_log(level):
            return

        error_dict = None
        if error:
            error_dict = {
                "type": type(error).__name__,
                "message": str(error),
            }
            if self._config.include_stacktrace:
                import traceback

                error_dict["stacktrace"] = traceback.format_exc()

        event = AuditEvent(
            event_type=event_type,
            level=level,
            path=path,
            operation=operation,
            success=success,
            duration_ms=duration_ms,
            context=self._context,
            details=details or {},
            error=error_dict,
        )

        if self._queue:
            try:
                await self._queue.put(event)
            except asyncio.QueueFull:
                logger.warning("Audit event queue full, dropping event")

    # Convenience methods for specific event types

    async def log_read(
        self,
        path: str,
        success: bool,
        duration_ms: float = 0.0,
        size_bytes: int | None = None,
        offset: int = 0,
        limit: int | None = None,
        error: Exception | None = None,
    ) -> None:
        """Log a read operation."""
        await self._log_event(
            AuditEventType.READ,
            AuditLevel.INFO if success else AuditLevel.ERROR,
            path,
            "read",
            success,
            duration_ms,
            {"size_bytes": size_bytes, "offset": offset, "limit": limit},
            error,
        )

    async def log_write(
        self,
        path: str,
        success: bool,
        duration_ms: float = 0.0,
        size_bytes: int | None = None,
        is_new_file: bool = False,
        error: Exception | None = None,
    ) -> None:
        """Log a write operation."""
        await self._log_event(
            AuditEventType.WRITE,
            AuditLevel.INFO if success else AuditLevel.ERROR,
            path,
            "write",
            success,
            duration_ms,
            {"size_bytes": size_bytes, "is_new_file": is_new_file},
            error,
        )

    async def log_delete(
        self,
        path: str,
        success: bool,
        duration_ms: float = 0.0,
        is_directory: bool = False,
        error: Exception | None = None,
    ) -> None:
        """Log a delete operation."""
        await self._log_event(
            AuditEventType.DELETE,
            AuditLevel.WARNING if success else AuditLevel.ERROR,
            path,
            "delete",
            success,
            duration_ms,
            {"is_directory": is_directory},
            error,
        )

    async def log_edit(
        self,
        path: str,
        success: bool,
        duration_ms: float = 0.0,
        edit_type: str = "",
        error: Exception | None = None,
    ) -> None:
        """Log an edit operation."""
        await self._log_event(
            AuditEventType.EDIT,
            AuditLevel.INFO if success else AuditLevel.ERROR,
            path,
            "edit",
            success,
            duration_ms,
            {"edit_type": edit_type},
            error,
        )

    async def log_glob(
        self,
        pattern: str,
        success: bool,
        duration_ms: float = 0.0,
        match_count: int = 0,
        error: Exception | None = None,
    ) -> None:
        """Log a glob operation."""
        await self._log_event(
            AuditEventType.GLOB,
            AuditLevel.DEBUG if success else AuditLevel.ERROR,
            pattern,
            "glob",
            success,
            duration_ms,
            {"match_count": match_count},
            error,
        )

    async def log_permission_denied(
        self,
        path: str,
        operation: str,
        reason: str,
    ) -> None:
        """Log a permission denied event."""
        await self._log_event(
            AuditEventType.PERMISSION_DENIED,
            AuditLevel.WARNING,
            path,
            operation,
            False,
            0.0,
            {"reason": reason},
        )

    async def log_path_traversal(
        self,
        path: str,
        attempted_path: str,
        operation: str,
    ) -> None:
        """Log a path traversal attempt."""
        await self._log_event(
            AuditEventType.PATH_TRAVERSAL,
            AuditLevel.ERROR,
            path,
            operation,
            False,
            0.0,
            {"attempted_path": attempted_path},
        )

    async def log_rate_limited(
        self,
        operation: str,
        path: str | None,
        retry_after: float,
    ) -> None:
        """Log a rate limit event."""
        await self._log_event(
            AuditEventType.RATE_LIMITED,
            AuditLevel.WARNING,
            path,
            operation,
            False,
            0.0,
            {"retry_after": retry_after},
        )

    async def __aenter__(self) -> AuditLogger:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


class AuditedFilesystem:
    """Wrapper that adds audit logging to any filesystem.

    This class wraps a UnifiedFilesystem and logs all operations
    to an AuditLogger.

    Example:
        >>> fs = LocalFilesystem("/workspace")
        >>> audit = AuditLogger(config)
        >>> audited_fs = AuditedFilesystem(fs, audit)
        >>> async with audited_fs:
        ...     content = await audited_fs.read("file.txt")
    """

    def __init__(
        self,
        filesystem: Any,
        audit_logger: AuditLogger,
    ) -> None:
        """Initialize audited filesystem.

        Args:
            filesystem: Filesystem to wrap.
            audit_logger: Audit logger instance.
        """
        self._fs = filesystem
        self._audit = audit_logger

    async def __aenter__(self) -> AuditedFilesystem:
        """Async context manager entry."""
        await self._audit.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self._audit.stop()

    async def read(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Any:
        """Read file with audit logging."""
        start = time.monotonic()
        try:
            result = await self._fs.read(path, offset=offset, limit=limit)
            duration = (time.monotonic() - start) * 1000
            await self._audit.log_read(
                path,
                True,
                duration,
                size_bytes=len(result.content) if hasattr(result, "content") else None,
                offset=offset,
                limit=limit,
            )
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            await self._audit.log_read(path, False, duration, error=e)
            raise

    async def write(self, path: str, content: str | bytes) -> Any:
        """Write file with audit logging."""
        start = time.monotonic()
        try:
            result = await self._fs.write(path, content)
            duration = (time.monotonic() - start) * 1000
            size = len(content) if isinstance(content, (str, bytes)) else 0
            await self._audit.log_write(
                path,
                True,
                duration,
                size_bytes=size,
                is_new_file=not await self._fs.exists(path),
            )
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            await self._audit.log_write(path, False, duration, error=e)
            raise

    async def delete(self, path: str) -> Any:
        """Delete file with audit logging."""
        start = time.monotonic()
        try:
            result = await self._fs.delete(path)
            duration = (time.monotonic() - start) * 1000
            await self._audit.log_delete(path, True, duration)
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            await self._audit.log_delete(path, False, duration, error=e)
            raise
