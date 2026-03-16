"""Session logging and input history for the Soothe TUI."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)

_LOG_CONTENT_LIMIT = 2000


def _truncate_for_log(text: str, limit: int = _LOG_CONTENT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


# ---------------------------------------------------------------------------
# Session logger
# ---------------------------------------------------------------------------


class SessionLogger:
    """Append-only JSONL writer for stream and conversation records.

    Captures structured event records for offline replay and audit, plus
    user/assistant conversation turns for lightweight in-terminal review.

    Args:
        session_dir: Directory for session logs. Defaults to ``SOOTHE_HOME/sessions/``.
        thread_id: Thread ID for the log file name.
    """

    def __init__(
        self,
        session_dir: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        self._session_dir = Path(session_dir or os.path.join(SOOTHE_HOME, "sessions")).expanduser()
        self._thread_id = thread_id or "default"
        self._initialized = False

    @property
    def session_dir(self) -> Path:
        """Root directory for session JSONL files."""
        return self._session_dir

    @property
    def log_path(self) -> Path:
        """Path to the current thread's JSONL file."""
        return self._session_dir / f"{self._thread_id}.jsonl"

    def set_thread_id(self, thread_id: str) -> None:
        """Update the thread ID (and thus the log file)."""
        self._thread_id = thread_id
        self._initialized = False

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
            from soothe.cli.progress_verbosity import classify_custom_event

            record: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "kind": "event",
                "namespace": list(namespace),
                "classification": classify_custom_event(namespace, data),
                "data": data,
            }
            self._write_record(record)
        elif mode == "messages" and isinstance(data, (tuple, list)) and len(data) == 2:
            self._log_message_event(namespace, data)

    def log_user_input(self, text: str) -> None:
        """Log a user turn for later session review.

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
        """Log an assistant turn for later session review.

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
        """Log tool calls and tool results from messages-mode chunks."""
        try:
            from langchain_core.messages import AIMessage, ToolMessage

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
        except Exception:
            logger.debug("Failed to log message event", exc_info=True)

    def read_recent_records(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent session records from disk.

        Args:
            limit: Maximum number of records to return.

        Returns:
            Parsed JSONL records in chronological order.
        """
        if limit <= 0 or not self.log_path.exists():
            return []

        try:
            with open(self.log_path, encoding="utf-8") as fh:
                lines = fh.readlines()[-limit:]
        except OSError:
            logger.debug("SessionLogger read failed", exc_info=True)
            return []

        records: list[dict[str, Any]] = []
        for line in lines:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Skipping invalid session log line", exc_info=True)
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    def recent_conversation(self, limit: int = 6) -> list[dict[str, Any]]:
        """Return recent conversation turns from the current session log."""
        records = self.read_recent_records(limit=max(limit * 4, limit))
        items = [record for record in records if record.get("kind") == "conversation"]
        return items[-limit:]

    def recent_actions(self, limit: int = 12) -> list[dict[str, Any]]:
        """Return recent action/event records from the current session log."""
        records = self.read_recent_records(limit=max(limit * 4, limit))
        items = [record for record in records if record.get("kind") == "event"]
        return items[-limit:]

    def _write_record(self, record: dict[str, Any]) -> None:
        """Append a single JSONL record to the session log."""
        try:
            self._ensure_dir()
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            logger.debug("SessionLogger write failed", exc_info=True)

    def _ensure_dir(self) -> None:
        if not self._initialized:
            try:
                self._session_dir.mkdir(parents=True, exist_ok=True)
                self._initialized = True
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Input history
# ---------------------------------------------------------------------------


class InputHistory:
    """Persistent command history backed by a JSON file.

    Args:
        history_file: Path to the history JSON file.
        max_size: Maximum number of history entries to retain.
    """

    def __init__(
        self,
        history_file: str | None = None,
        max_size: int = 1000,
    ) -> None:
        self.history_file = Path(history_file or os.path.join(SOOTHE_HOME, "history.json")).expanduser()
        self.max_size = max_size
        self.history: list[str] = []
        self._load()

    def _load(self) -> None:
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def _save(self) -> None:
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w") as f:
                json.dump(self.history[-self.max_size :], f, indent=2)
        except Exception:
            logger.debug("InputHistory save failed", exc_info=True)

    def add(self, line: str) -> None:
        """Add a line to history (deduplicates consecutive entries).

        Args:
            line: The input line to record.
        """
        stripped = line.strip()
        if stripped and (not self.history or self.history[-1] != stripped):
            self.history.append(stripped)
            if len(self.history) > self.max_size:
                self.history = self.history[-self.max_size :]
            self._save()
