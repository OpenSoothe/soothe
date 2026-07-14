"""Per-async-task router profile overlay for daemon / runner streaming.

Loop workers set a ``ContextVar`` for the duration of a turn (via
``stream_turn_overrides``) so ``SootheConfig.resolve_model`` (chat roles only)
uses the selected ``router_profiles`` entry without mutating process-wide config.
"""

from __future__ import annotations

import contextvars
from typing import TypeAlias

_Token: TypeAlias = contextvars.Token[str | None]

_stream_router_profile: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "soothe_stream_router_profile",
    default=None,
)


def attach_stream_router_profile(name: str | None) -> _Token:
    """Attach a router profile name for the current asyncio Task.

    Args:
        name: Profile name from ``router_profiles``, or ``None`` to clear.

    Returns:
        Token to pass to `reset_stream_router_profile`.
    """
    if not name or not str(name).strip():
        return _stream_router_profile.set(None)
    return _stream_router_profile.set(str(name).strip())


def reset_stream_router_profile(token: _Token) -> None:
    """Restore the previous overlay for this Task."""
    _stream_router_profile.reset(token)


def get_stream_router_profile() -> str | None:
    """Return the active stream router profile name, if any."""
    return _stream_router_profile.get()
