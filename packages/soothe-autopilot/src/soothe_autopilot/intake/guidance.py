"""Guidance absorb/collect façade for Autopilot intake.

Absorbs advisory text into ContextEngine `guidance_accumulated` for the next
worker dispatch. Does not create or inject goals.
"""

from __future__ import annotations

from typing import Any, Protocol

from soothe.context.models import GoalNode

from soothe_autopilot.intake.models import (
    GUIDANCE_SCOPES,
    GUIDANCE_SOURCES,
    GuidanceScope,
    GuidanceSource,
)


class _AbsorbCapable(Protocol):
    """Protocol for CE-like objects that can absorb guidance text."""

    async def absorb_guidance(
        self,
        goal_id: str,
        guidance_text: str,
        scope: str = "goal",
        *,
        source: str = "user",
    ) -> bool: ...


async def absorb_guidance(
    ce: _AbsorbCapable,
    goal_id: str,
    text: str,
    *,
    scope: GuidanceScope = "goal",
    source: GuidanceSource = "user",
) -> bool:
    """Absorb guidance into CE for `goal_id` (next Autopilot dispatch).

    Args:
        ce: ContextEngine (or test double) with `absorb_guidance`.
        goal_id: Target goal or job root id.
        text: Operator / channel guidance text.
        scope: `goal` for one node, `job` for root job-wide entries.
        source: Provenance tag (`user`, `channel`, or `system`).

    Returns:
        True when absorbed, False when the goal is missing or text empty.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    scope_norm: str = scope if scope in GUIDANCE_SCOPES else "goal"
    source_norm: str = source if source in GUIDANCE_SOURCES else "user"
    return await ce.absorb_guidance(
        goal_id,
        cleaned,
        scope=scope_norm,
        source=source_norm,
    )


async def absorb_user_guidance(
    ce: _AbsorbCapable,
    goal_id: str,
    text: str,
    *,
    scope: GuidanceScope = "goal",
) -> bool:
    """Absorb CLI / WS `job_guidance` text (source=user)."""
    return await absorb_guidance(ce, goal_id, text, scope=scope, source="user")


async def absorb_channel_guidance(
    ce: _AbsorbCapable,
    goal_id: str,
    text: str,
    *,
    scope: GuidanceScope = "goal",
) -> bool:
    """Absorb channel guidance (source=channel). No ChannelManager wiring yet."""
    return await absorb_guidance(ce, goal_id, text, scope=scope, source="channel")


def collect_operator_guidance(
    goal: GoalNode,
    all_goals: dict[str, GoalNode],
) -> list[str]:
    """Collect guidance texts for a goal about to be dispatched.

    Includes guidance on the goal itself plus job-scoped entries on the root.
    """
    texts: list[str] = []
    seen: set[str] = set()

    def _append(entries: list[dict[str, Any]] | None) -> None:
        for entry in entries or []:
            text = str(entry.get("text") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            texts.append(text)

    _append(goal.guidance_accumulated)

    root: GoalNode | None = goal
    visited: set[str] = set()
    while root is not None and root.parent_id and root.parent_id not in visited:
        visited.add(root.id)
        parent = all_goals.get(root.parent_id)
        if parent is None:
            break
        root = parent
    if root is not None and root.id != goal.id:
        job_scoped = [
            e for e in (root.guidance_accumulated or []) if str(e.get("scope") or "") == "job"
        ]
        _append(job_scoped)

    return texts
