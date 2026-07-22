"""Thread logging and input history for Soothe."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME
from soothe.sloop.checkpoints.directory_manager import (
    THREADS_DATA_DIR,
    PersistenceDirectoryManager,
)

logger = logging.getLogger(__name__)

_LOG_CONTENT_LIMIT = 2000
_MESSAGE_TUPLE_LENGTH = 2
_BUFFER_FLUSH_THRESHOLD = 100
_BUFFER_FLUSH_INTERVAL_SECONDS = 1.0


def _truncate_for_log(text: str, limit: int = _LOG_CONTENT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


class ThreadLogger:
    """Append-only JSONL writer for stream and conversation records.

    Captures structured event records for offline replay and audit, plus
    user/assistant conversation turns for lightweight in-terminal review.

    Args:
        thread_dir: Directory for thread logs. Defaults to ``SOOTHE_HOME/data/threads/{thread_id}/logs/``.
        thread_id: Thread ID for the log file name.
    """

    def __init__(
        self,
        thread_dir: str | None = None,
        thread_id: str | int | None = None,
        retention_days: int = 30,
        max_size_mb: int = 100,
    ) -> None:
        """Initialize the thread logger.

        Args:
            thread_dir: Directory for thread logs. Defaults to ``SOOTHE_HOME/data/threads/{thread_id}/logs/``.
            thread_id: Thread ID for the log file name.
            retention_days: Days to retain thread logs before cleanup.
            max_size_mb: Maximum total size for all thread logs under ``data/threads/``.
        """
        tid = str(thread_id or "default")
        default_dir = PersistenceDirectoryManager.get_thread_directory(tid) / "logs"
        self._thread_dir = Path(thread_dir or default_dir).expanduser()
        self._thread_id = tid
        self._retention_days = retention_days
        self._max_size_mb = max_size_mb
        self._initialized = False
        self._buffer: list[str] = []
        self._last_flush_time: float = time.time()
        self._goal_completion_chunk_accum: list[str] = []

    @property
    def log_path(self) -> Path:
        """Path to the current thread's JSONL file."""
        return self._thread_dir / "conversation.jsonl"

    def log(
        self,
        namespace: tuple[str, ...],
        mode: str,
        data: Any,
    ) -> None:
        """Log a stream chunk: custom events and tool-related messages.

        Args:
            namespace: Stream namespace (empty tuple for main agent).
            mode: Stream mode (``messages``, ``updates``, ``custom``).
            data: Stream data payload.
        """
        if mode == "custom" and isinstance(data, dict):
            from soothe_sdk.ux import classify_event_to_tier

            record: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "kind": "event",
                "namespace": list(namespace),
                "classification": classify_event_to_tier(data.get("type", ""), namespace),
                "data": data,
            }
            self._write_record(record)
        elif (
            mode == "messages"
            and isinstance(data, (tuple, list))
            and len(data) == _MESSAGE_TUPLE_LENGTH
        ):
            self._log_message_event(namespace, data)

    def log_user_input(self, text: str) -> None:
        """Log a user turn for later thread review.

        Args:
            text: User-entered prompt text.
        """
        cleaned = text.strip()
        if not cleaned:
            return
        self._write_record(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "kind": "conversation",
                "role": "user",
                "text": cleaned,
            }
        )

    def log_assistant_response(self, text: str) -> None:
        """Log an assistant turn for later thread review.

        Args:
            text: Final assistant response text.
        """
        cleaned = text.strip()
        if not cleaned:
            return
        self._write_record(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "kind": "conversation",
                "role": "assistant",
                "text": cleaned,
            }
        )

    def _log_message_event(
        self,
        namespace: tuple[str, ...],
        data: Any,
    ) -> None:
        """Log tool calls / tool results / loop assistant output from messages-mode chunks."""
        try:
            from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
            from soothe_sdk.ux.loop_stream import assistant_output_phase

            msg, _metadata = data
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                self._write_record(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "kind": "tool_result",
                        "namespace": list(namespace),
                        "tool_name": getattr(msg, "name", "unknown"),
                        "content": _truncate_for_log(content),
                    }
                )
            elif isinstance(msg, AIMessageChunk):
                from soothe_sdk.ux.loop_stream import is_goal_completion_stream_terminal

                phase = assistant_output_phase(msg)
                if phase != "goal_completion":
                    return
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content:
                    self._goal_completion_chunk_accum.append(content)
                if is_goal_completion_stream_terminal(msg):
                    cleaned = "".join(self._goal_completion_chunk_accum).strip()
                    self._goal_completion_chunk_accum.clear()
                    if cleaned:
                        self._write_record(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "kind": "conversation",
                                "role": "assistant",
                                "text": cleaned,
                                "phase": "goal_completion",
                                "namespace": list(namespace),
                            }
                        )
            elif isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in tool_calls:
                    if isinstance(tc, dict) and tc.get("name"):
                        self._write_record(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "kind": "tool_call",
                                "namespace": list(namespace),
                                "tool_name": tc["name"],
                                "args_preview": _truncate_for_log(str(tc.get("args", {})), 500),
                            }
                        )

                phase = assistant_output_phase(msg)
                if phase and not tool_calls:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    cleaned = content.strip()
                    if cleaned:
                        self._write_record(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "kind": "conversation",
                                "role": "assistant",
                                "text": cleaned,
                                "phase": phase,
                                "namespace": list(namespace),
                            }
                        )
        except Exception:
            logger.debug("Failed to log message event", exc_info=True)

    def read_recent_records(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent thread records from disk.

        Args:
            limit: Maximum number of records to return.

        Returns:
            Parsed JSONL records in chronological order.
        """
        if limit <= 0 or not self.log_path.exists():
            return []

        try:
            with self.log_path.open(encoding="utf-8") as fh:
                lines = fh.readlines()[-limit:]
        except OSError:
            logger.debug("ThreadLogger read failed", exc_info=True)
            return []

        records: list[dict[str, Any]] = []
        for line in lines:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Skipping invalid thread log line", exc_info=True)
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    def _write_record(self, record: dict[str, Any]) -> None:
        """Append a single JSONL record to the thread log (buffered)."""
        try:
            self._ensure_dir()
            self._buffer.append(json.dumps(record, default=str))
            current_time = time.time()
            if (
                len(self._buffer) >= _BUFFER_FLUSH_THRESHOLD
                or current_time - self._last_flush_time >= _BUFFER_FLUSH_INTERVAL_SECONDS
            ):
                self._flush_buffer()
        except OSError:
            logger.debug("ThreadLogger write failed", exc_info=True)

    def _flush_buffer(self) -> None:
        """Flush buffered records to disk."""
        if not self._buffer:
            return
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(self._buffer) + "\n")
                fh.flush()
                with contextlib.suppress(OSError):
                    os.fsync(fh.fileno())
            self._buffer.clear()
            self._last_flush_time = time.time()
        except OSError:
            logger.debug("ThreadLogger flush failed", exc_info=True)

    def flush(self) -> None:
        """Public flush method for explicit buffer clearing."""
        self._flush_buffer()

    def _ensure_dir(self) -> None:
        if not self._initialized:
            try:
                self._thread_dir.mkdir(parents=True, exist_ok=True)
                self._initialized = True
            except OSError:
                pass


def cleanup_stale_thread_logs(
    *,
    retention_days: int = 30,
    max_size_mb: int = 100,
    threads_root: Path | None = None,
) -> int:
    """Delete old ``conversation.jsonl`` files across all thread directories.

    Expects the layout ``threads/{id}/logs/conversation.jsonl``.

    Args:
        retention_days: Remove logs older than this many days.
        max_size_mb: When total size exceeds this budget, delete oldest logs first.
        threads_root: Override ``$SOOTHE_HOME/data/threads`` for tests.

    Returns:
        Number of log files deleted.
    """
    root = Path(threads_root or Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR)
    if not root.is_dir():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    max_bytes = max(0, max_size_mb) * 1024 * 1024

    deleted = 0
    log_files: list[tuple[Path, Path, float, int]] = []
    for thread_dir in root.iterdir():
        if not thread_dir.is_dir():
            continue
        log_path = thread_dir / "logs" / "conversation.jsonl"
        if not log_path.is_file():
            continue
        try:
            stat = log_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            if mtime < cutoff:
                log_path.unlink(missing_ok=True)
                _remove_thread_dir_if_empty(thread_dir)
                deleted += 1
                continue
            log_files.append((log_path, thread_dir, stat.st_mtime, stat.st_size))
        except OSError:
            logger.debug("Failed to stat thread log %s", log_path, exc_info=True)

    if max_bytes <= 0:
        return deleted

    total_size = sum(size for _, _, _, size in log_files)
    if total_size > max_bytes:
        log_files.sort(key=lambda item: item[2])
        for log_path, thread_dir, _, size in log_files:
            if total_size <= max_bytes:
                break
            try:
                log_path.unlink(missing_ok=True)
                _remove_thread_dir_if_empty(thread_dir)
                total_size -= size
                deleted += 1
            except OSError:
                logger.debug("Failed to delete thread log %s", log_path, exc_info=True)
    return deleted


def _remove_thread_dir_if_empty(thread_dir: Path) -> None:
    """Remove ``threads/{id}`` when only empty ``logs/`` remains."""
    try:
        if not thread_dir.is_dir():
            return
        remaining = [p for p in thread_dir.rglob("*") if p.is_file()]
        if remaining:
            return
        shutil.rmtree(thread_dir, ignore_errors=True)
    except OSError:
        logger.debug("Failed to remove empty thread dir %s", thread_dir, exc_info=True)
