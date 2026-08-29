"""Shared types and dataclasses for the TUI app sub-package.

Single source of truth for type aliases and data structures used across
mixin modules. Previously duplicated in `_module_init.py` and `_execution.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.widgets.message_store import MessageData

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

InputMode = Literal["normal", "shell", "command"]
"""Input mode that determines message routing."""


@dataclass(frozen=True, slots=True)
class QueuedMessage:
    """Represents a queued user message awaiting processing."""

    text: str
    """The message text content."""

    mode: InputMode
    """The input mode that determines message routing."""


DeferredActionKind = Literal["model_switch", "loop_switch", "chat_output"]
"""Valid `DeferredAction.kind` values for type-checked deduplication."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DeferredAction:
    """An action deferred until the current busy state resolves."""

    kind: DeferredActionKind
    """Identity key for deduplication — one of `DeferredActionKind`."""

    execute: Callable[[], Awaitable[None]]
    """Async callable that performs the actual work."""


@dataclass(frozen=True, slots=True)
class _LoopHistoryPayload:
    """Data returned by `_fetch_loop_history_data`."""

    messages: list[MessageData]
    """Converted message data ready for bulk loading."""

    context_tokens: int
    """Persisted accumulated loop token usage from checkpoint (0 if absent)."""

    goals: tuple[dict[str, Any], ...] = ()
    """Goal display snapshots from ``loop_history_fetch`` (RFC-631)."""


def _new_loop_id() -> str:
    """Deferred-import wrapper around `sessions.generate_loop_id`.

    Returns:
    UUID7 string.
    """
    from soothe_cli.loops.sessions import generate_loop_id

    return generate_loop_id()


class TextualSessionState:
    """Session state for the Textual app."""

    def __init__(
        self,
        *,
        loop_id: str | None = None,
    ) -> None:
        """Initialize session state.

        Args:
        loop_id: Optional loop ID (generates UUID7 if not provided)
        """
        self.loop_id = loop_id or _new_loop_id()

    def reset_loop(self) -> str:
        """Reset to a new loop.

        Returns:
        The new loop_id.
        """
        self.loop_id = _new_loop_id()
        return self.loop_id


@dataclass(frozen=True)
class AppResult:
    """Result from running the Textual application."""

    return_code: int
    """Exit code (0 for success, non-zero for error)."""

    loop_id: str | None
    """The final StrangeLoop id at shutdown (may change if the user switched loops)."""

    session_stats: SessionStats = field(default_factory=SessionStats)
    """Cumulative usage stats across all turns in the session."""

    update_available: tuple[bool, str | None] = (False, None)
    """`(is_available, latest_version)` for post-exit update warning."""
