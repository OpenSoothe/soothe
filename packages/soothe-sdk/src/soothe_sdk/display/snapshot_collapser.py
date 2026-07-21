"""Collapse live card lists into goal-bound display snapshots."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from soothe_sdk.display.snapshot_types import GoalDisplaySnapshot
from soothe_sdk.display.transcript_types import MessageData, MessageType


def _last_card_per_id(cards: list[MessageData]) -> list[MessageData]:
    """Keep the last occurrence of each card id while preserving order."""
    index_by_id: dict[str, int] = {}
    ordered: list[MessageData] = []
    for card in cards:
        if card.id in index_by_id:
            ordered[index_by_id[card.id]] = card
        else:
            index_by_id[card.id] = len(ordered)
            ordered.append(card)
    return ordered


def fold_display_cards(cards: list[MessageData]) -> list[MessageData]:
    """Collapse streaming duplicates; keep terminal card state per id."""
    if not cards:
        return []
    from soothe_sdk.display.card_binder import merge_consecutive_assistant_cards

    return merge_consecutive_assistant_cards(_last_card_per_id(cards))


def _ensure_user_card(cards: list[MessageData], goal_text: str) -> list[MessageData]:
    text = goal_text.strip()
    if not text:
        return cards
    for card in cards:
        if card.type == MessageType.USER and card.content.strip():
            return cards
    user = MessageData(type=MessageType.USER, content=text, id=f"msg-{uuid.uuid4().hex[:8]}")
    return [user, *cards]


def _ensure_assistant_card(cards: list[MessageData], goal_completion: str) -> list[MessageData]:
    text = goal_completion.strip()
    if not text:
        return cards
    for card in reversed(cards):
        if card.type == MessageType.ASSISTANT and card.content.strip():
            return cards
    assistant = MessageData(
        type=MessageType.ASSISTANT,
        content=text,
        id=f"msg-{uuid.uuid4().hex[:8]}",
        is_streaming=False,
    )
    return [*cards, assistant]


def build_goal_snapshot(
    *,
    goal_id: str,
    goal_index: int,
    goal_text: str,
    status: str,
    started_at: str,
    completed_at: str | None,
    duration_ms: int,
    tokens_used: int,
    goal_completion: str,
    live_cards: list[MessageData],
    plan_summary: dict | None = None,
    step_outcomes: list[dict] | None = None,
) -> GoalDisplaySnapshot:
    """Build a frozen snapshot from live cards and execution metadata."""
    display = fold_display_cards(live_cards)
    display = _ensure_user_card(display, goal_text)
    display = _ensure_assistant_card(display, goal_completion)
    return GoalDisplaySnapshot(
        goal_id=goal_id,
        goal_index=goal_index,
        goal_text=goal_text.strip(),
        status=status,
        started_at=started_at or datetime.now(UTC).isoformat(),
        completed_at=completed_at,
        duration_ms=max(0, duration_ms),
        tokens_used=max(0, tokens_used),
        plan_summary=plan_summary,
        step_outcomes=list(step_outcomes or []),
        goal_completion=goal_completion.strip(),
        display_cards=display,
        card_count=len(display),
    )


def split_cards_by_user_segments(cards: list[MessageData]) -> list[list[MessageData]]:
    """Split a flat card list into per-goal segments at user message boundaries."""
    if not cards:
        return []
    segments: list[list[MessageData]] = []
    current: list[MessageData] = []
    for card in cards:
        if card.type == MessageType.USER and current:
            segments.append(current)
            current = [card]
        else:
            current.append(card)
    if current:
        segments.append(current)
    return segments


__all__ = [
    "build_goal_snapshot",
    "fold_display_cards",
    "split_cards_by_user_segments",
]
