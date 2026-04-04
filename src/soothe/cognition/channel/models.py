"""RFC-204: Channel Message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

# User → Soothe message types
CHANNEL_USER_TO_SOOTHE = frozenset(
    {
        "task_submit",
        "task_cancel",
        "signal_interrupt",
        "signal_resume",
        "query_status",
        "feedback",
    }
)

# Soothe → User message types
CHANNEL_SOOTHE_TO_USER = frozenset(
    {
        "status_update",
        "goal_progress",
        "finding_report",
        "blocker_alert",
        "dreaming_entered",
        "session_summary",
    }
)

# Message types that require acknowledgment
CRITICAL_MESSAGE_TYPES = frozenset(
    {
        "blocker_alert",
        "dreaming_entered",
        "must_goal_confirmation",
    }
)


@dataclass
class ChannelMessage:
    """RFC-204: Message for user ↔ Soothe communication.

    Args:
        type: Message type string (e.g., "task_submit", "status_update").
        payload: Type-specific content as dict.
        timestamp: Message creation time.
        sender: Originator — "user", "soothe", or "system".
        requires_ack: Whether this message needs acknowledgment.
        ack_id: Acknowledgment ID for retry tracking (set on critical messages).
    """

    type: str
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    sender: Literal["user", "soothe", "system"] = "soothe"
    requires_ack: bool = False
    ack_id: str | None = None

    def __post_init__(self) -> None:
        """Auto-set requires_ack for critical message types."""
        if not self.requires_ack and self.type in CRITICAL_MESSAGE_TYPES:
            self.requires_ack = True

    def to_dict(self) -> dict:
        """Serialize to JSON-serializable dict."""
        return {
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender,
            "requires_ack": self.requires_ack,
            "ack_id": self.ack_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChannelMessage:
        """Deserialize from dict."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            from datetime import datetime as _dt

            ts = _dt.fromisoformat(ts)
        return cls(
            type=data["type"],
            payload=data.get("payload", {}),
            timestamp=ts or datetime.now(tz=UTC),
            sender=data.get("sender", "soothe"),
            requires_ack=data.get("requires_ack", False),
            ack_id=data.get("ack_id"),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json

        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> ChannelMessage:
        """Deserialize from JSON string."""
        import json

        return cls.from_dict(json.loads(text))
