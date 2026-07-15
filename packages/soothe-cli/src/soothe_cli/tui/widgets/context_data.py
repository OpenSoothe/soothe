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


def _load_soothe_config_for_context() -> Any:
    """Load full daemon ``SootheConfig`` for context-engine persistence."""
    from pathlib import Path

    from soothe.config.settings import SootheConfig
    from soothe_sdk.paths import SOOTHE_HOME

    path = Path(SOOTHE_HOME) / "config" / "config.yml"
    if path.exists():
        return SootheConfig.from_yaml_file(str(path))
    return SootheConfig()


async def load_ce_goals(loop_id: str) -> list[dict[str, Any]]:
    """Load Context Engine goals for ``loop_id`` via the configured persistence backend."""
    raw_loop_id = str(loop_id or "").strip()
    if not raw_loop_id or raw_loop_id == "unknown":
        return []

    try:
        from soothe.foundation.context.persistence.factory import (
            resolve_context_engine_persistence,
        )

        config = _load_soothe_config_for_context()
        persistence = resolve_context_engine_persistence(config, raw_loop_id)
        dag = await persistence.load_dag()
        close = getattr(persistence, "close", None)
        if callable(close):
            await close()
    except Exception:
        logger.debug("Failed to load CE goals for loop %s", raw_loop_id, exc_info=True)
        return []

    if dag is None:
        return []

    return [
        goal.model_dump(mode="json") for goal in dag.goals.values() if hasattr(goal, "model_dump")
    ]


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
