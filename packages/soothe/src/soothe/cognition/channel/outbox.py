"""RFC-204: File-based channel outbox.

Writes messages to outbox directory as JSON files. Supports retry tracking
for messages requiring acknowledgment.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from .models import ChannelMessage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class ChannelOutbox:
    """Write messages to the autopilot outbox directory.

    Args:
        outbox_dir: Path to outbox directory. Defaults to $SOOTHE_HOME/autopilot/outbox.
    """

    def __init__(self, outbox_dir: str | Path | None = None) -> None:
        """Initialize outbox.

        Args:
            outbox_dir: Path to outbox directory.
        """
        self._outbox_dir = Path(outbox_dir) if outbox_dir else None
        self._pending_acks: dict[str, int] = {}  # ack_id → retry count

    def set_directory(self, path: str | Path) -> None:
        """Set outbox directory path.

        Args:
            path: New outbox directory path.
        """
        self._outbox_dir = Path(path)
        self._outbox_dir.mkdir(parents=True, exist_ok=True)

    def send(self, message: ChannelMessage) -> str:
        """Write a message to the outbox.

        Args:
            message: ChannelMessage to send.

        Returns:
            Message filename (ack_id if requires_ack, else generated UUID).
        """
        if not self._outbox_dir:
            logger.warning("Outbox not configured, dropping message: %s", message.type)
            return ""

        self._outbox_dir.mkdir(parents=True, exist_ok=True)

        if message.requires_ack and not message.ack_id:
            message.ack_id = uuid.uuid4().hex[:12]
            self._pending_acks[message.ack_id] = 0

        filename = f"{message.ack_id or uuid.uuid4().hex[:12]}_{message.type}.json"
        fpath = self._outbox_dir / filename
        fpath.write_text(message.to_json())

        logger.info("Outbox message written: %s (%s)", message.type, filename)
        return filename

    def acknowledge(self, ack_id: str) -> bool:
        """Mark a message as acknowledged.

        Args:
            ack_id: Acknowledgment ID from the message.

        Returns:
            True if message was found and acknowledged.
        """
        if ack_id in self._pending_acks:
            del self._pending_acks[ack_id]
            # Remove pending file
            if self._outbox_dir:
                for fpath in self._outbox_dir.glob(f"{ack_id}_*"):
                    ack_path = self._outbox_dir / "acknowledged"
                    ack_path.mkdir(exist_ok=True)
                    fpath.rename(ack_path / fpath.name)
            logger.info("Message acknowledged: %s", ack_id)
            return True
        return False

    def get_unacked(self) -> list[tuple[str, int]]:
        """Get messages that haven't been acknowledged.

        Returns:
            List of (ack_id, retry_count) tuples.
        """
        return list(self._pending_acks.items())

    def retry_count(self, ack_id: str) -> int:
        """Get retry count for a message.

        Args:
            ack_id: Acknowledgment ID.

        Returns:
            Number of retries attempted.
        """
        return self._pending_acks.get(ack_id, 0)

    def increment_retry(self, ack_id: str) -> int:
        """Increment retry count for a message.

        Args:
            ack_id: Acknowledgment ID.

        Returns:
            New retry count.
        """
        current = self._pending_acks.get(ack_id, 0)
        self._pending_acks[ack_id] = current + 1
        return current + 1

    def should_retry(self, ack_id: str) -> bool:
        """Check if a message should be retried.

        Args:
            ack_id: Acknowledgment ID.

        Returns:
            True if retry count is below MAX_RETRIES.
        """
        return self._pending_acks.get(ack_id, 0) < MAX_RETRIES

    def clear_ack(self, ack_id: str) -> None:
        """Remove a message from pending tracking.

        Args:
            ack_id: Acknowledgment ID.
        """
        self._pending_acks.pop(ack_id, None)
