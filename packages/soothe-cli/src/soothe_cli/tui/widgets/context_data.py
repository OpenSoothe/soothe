"""Shared helpers for the /context modal (goal DAG + token usage)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from soothe_cli.runtime.state.session_stats import format_token_count
from soothe_cli.runtime.token_usage import fetch_conversation_token_count

logger = logging.getLogger(__name__)

LoadTokenSnapshotFn = Callable[[], Awaitable["TokenUsageSnapshot"]]

__all__ = [
    "LoadTokenSnapshotFn",
    "TokenUsageSnapshot",
    "format_token_usage",
    "load_ce_goals",
    "load_token_usage_snapshot",
    "summarize_goal_statuses",
]


@dataclass(frozen=True, slots=True)
class TokenUsageSnapshot:
    """Token usage fields shown in the context modal."""

    context_tokens: int
    approximate: bool = False
    conv_tokens: int | None = None
    model_name: str | None = None
    context_limit: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0


async def load_token_usage_snapshot(
    *,
    context_tokens: int,
    approximate: bool = False,
    loop_id: str | None,
    daemon_session: Any,
    model_name: str | None = None,
    context_limit: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> TokenUsageSnapshot:
    """Build the token snapshot shown in the context modal."""
    conv_tokens: int | None = None
    if loop_id and daemon_session is not None:
        conv_tokens = await fetch_conversation_token_count(daemon_session, loop_id)

    effective_tokens = context_tokens
    effective_approximate = approximate
    if effective_tokens <= 0 and conv_tokens:
        effective_tokens = conv_tokens
        effective_approximate = True

    return TokenUsageSnapshot(
        context_tokens=effective_tokens,
        approximate=effective_approximate,
        conv_tokens=conv_tokens,
        model_name=model_name,
        context_limit=context_limit,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _goal_viewer_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a daemon goal snapshot (or CE-shaped dict) for the DAG panel."""
    goal_id = str(raw.get("id") or raw.get("goal_id") or "").strip()
    description = str(raw.get("description") or raw.get("goal_text") or "").strip()
    status = str(raw.get("status") or "unknown").strip() or "unknown"
    depends_raw = raw.get("depends_on")
    depends_on: list[str] = []
    if isinstance(depends_raw, list):
        depends_on = [str(dep) for dep in depends_raw if str(dep).strip()]
    return {
        "id": goal_id or "?",
        "description": description,
        "status": status,
        "depends_on": depends_on,
    }


async def load_ce_goals(loop_id: str, daemon_session: Any = None) -> list[dict[str, Any]]:
    """Load goals for ``loop_id`` via the daemon session (loop history RPC).

    Prefers Context Engine-shaped fields when present; otherwise maps RFC-631
    display snapshots (``goal_id`` / ``goal_text``). Dependency edges are only
    shown when the daemon includes ``depends_on``.
    """
    raw_loop_id = str(loop_id or "").strip()
    if not raw_loop_id or raw_loop_id == "unknown" or daemon_session is None:
        return []

    fetch = getattr(daemon_session, "fetch_loop_history", None)
    if not callable(fetch):
        return []

    try:
        history = await fetch(raw_loop_id)
    except Exception:
        logger.debug("Failed to load goals for loop %s", raw_loop_id, exc_info=True)
        return []

    goals_raw = getattr(history, "goals", None)
    if not isinstance(goals_raw, list):
        return []

    goals: list[dict[str, Any]] = []
    for item in goals_raw:
        if isinstance(item, dict):
            goals.append(_goal_viewer_dict(item))
    return goals


def format_token_usage(snapshot: TokenUsageSnapshot) -> str:
    """Render token usage lines for the context modal."""
    count = snapshot.context_tokens
    model_name = (snapshot.model_name or "").strip()
    context_limit = snapshot.context_limit
    suffix = "+" if snapshot.approximate else ""
    in_count = snapshot.input_tokens
    out_count = snapshot.output_tokens

    if count <= 0:
        parts: list[str] = ["No token usage yet"]
        if context_limit is not None:
            parts.append(f"{format_token_count(context_limit)} token context window")
        if model_name:
            parts.append(model_name)
        return " · ".join(parts)

    formatted = format_token_count(count)
    usage = f"{formatted}{suffix} tokens used this loop"
    if in_count > 0 or out_count > 0:
        usage += f" (in: {format_token_count(in_count)} · out: {format_token_count(out_count)})"

    msg = f"{usage} · {model_name}" if model_name else usage

    if context_limit is not None:
        limit_str = format_token_count(context_limit)
        msg += f"\n├ Context window: {limit_str} tokens"

    conv_tokens = snapshot.conv_tokens
    if conv_tokens is not None:
        conv_str = format_token_count(conv_tokens)
        conv_unit = " tokens" if conv_tokens < 1000 else ""  # noqa: PLR2004
        msg += f"\n└ Conversation (est.): ~{conv_str}{conv_unit}"
    return msg


def summarize_goal_statuses(goals: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
    """Return total goal count and per-status tallies."""
    counts: dict[str, int] = {}
    for goal in goals:
        status = str(goal.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return len(goals), counts
