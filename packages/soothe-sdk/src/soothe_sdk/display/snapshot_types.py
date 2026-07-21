"""Goal-bound display snapshot types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe_sdk.display.card_ledger import card_from_wire_dict, card_to_wire_dict
from soothe_sdk.display.transcript_types import MessageData

GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION = 1


@dataclass
class GoalDisplaySnapshot:
    """Immutable display + execution record for one completed goal."""

    goal_id: str
    goal_index: int
    goal_text: str
    status: str
    started_at: str
    completed_at: str | None
    duration_ms: int
    tokens_used: int
    plan_summary: dict[str, Any] | None
    step_outcomes: list[dict[str, Any]]
    goal_completion: str
    display_cards: list[MessageData]
    card_count: int
    schema_version: int = GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION

    def to_wire_dict(self) -> dict[str, Any]:
        """Serialize for SQLite storage and RPC transport."""
        return {
            "goal_id": self.goal_id,
            "goal_index": self.goal_index,
            "goal_text": self.goal_text,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "plan_summary": self.plan_summary,
            "step_outcomes": self.step_outcomes,
            "goal_completion": self.goal_completion,
            "display_cards": [card_to_wire_dict(c) for c in self.display_cards],
            "card_count": self.card_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_wire_dict(cls, data: dict[str, Any]) -> GoalDisplaySnapshot:
        """Deserialize from RPC transport or SQLite JSON."""
        raw_cards = data.get("display_cards")
        cards: list[MessageData] = []
        if isinstance(raw_cards, list):
            for item in raw_cards:
                if isinstance(item, dict):
                    cards.append(card_from_wire_dict(item))
        return cls(
            goal_id=str(data.get("goal_id") or ""),
            goal_index=int(data.get("goal_index") or 0),
            goal_text=str(data.get("goal_text") or ""),
            status=str(data.get("status") or "completed"),
            started_at=str(data.get("started_at") or ""),
            completed_at=data.get("completed_at") if data.get("completed_at") else None,
            duration_ms=int(data.get("duration_ms") or 0),
            tokens_used=int(data.get("tokens_used") or 0),
            plan_summary=data.get("plan_summary")
            if isinstance(data.get("plan_summary"), dict)
            else None,
            step_outcomes=[
                dict(item) for item in (data.get("step_outcomes") or []) if isinstance(item, dict)
            ],
            goal_completion=str(data.get("goal_completion") or ""),
            display_cards=cards,
            card_count=int(data.get("card_count") or len(cards)),
            schema_version=int(data.get("schema_version") or GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION),
        )


def snapshot_from_dataclass_dict(data: dict[str, Any]) -> GoalDisplaySnapshot:
    """Alias for ``from_wire_dict`` used by persistence layer."""
    return GoalDisplaySnapshot.from_wire_dict(data)


__all__ = [
    "GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION",
    "GoalDisplaySnapshot",
    "snapshot_from_dataclass_dict",
]
