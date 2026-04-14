"""Per-async-task model override for daemon / runner streaming (IG-172).

``QueryEngine`` sets a `ContextVar` for the duration of ``SootheRunner.astream`` so
``PerTurnModelMiddleware`` can swap the chat model without threading kwargs through
``AgentLoop`` and every ``astream`` callsite.
"""

from __future__ import annotations

import contextvars
from typing import Any

from typing_extensions import TypeAlias

_Token: TypeAlias = contextvars.Token[tuple[str, dict[str, Any]] | None]

_stream_model_override: contextvars.ContextVar[tuple[str, dict[str, Any]] | None] = contextvars.ContextVar(
    "soothe_stream_model_override",
    default=None,
)


def attach_stream_model_override(spec: str | None, params: dict[str, Any] | None) -> _Token:
    """Attach override for the current asyncio Task; returns a reset token.

    Args:
        spec: ``provider:model`` string, or ``None`` to clear.
        params: Extra kwargs merged into ``init_chat_model`` for this spec.

    Returns:
        Token to pass to `reset_stream_model_override`.
    """
    if not spec:
        return _stream_model_override.set(None)
    return _stream_model_override.set((spec.strip(), dict(params or {})))


def reset_stream_model_override(token: _Token) -> None:
    """Restore the previous override for this Task."""
    _stream_model_override.reset(token)


def get_stream_model_override() -> tuple[str, dict[str, Any]] | None:
    """Return ``(spec, params)`` when an override is active for this Task."""
    return _stream_model_override.get()
