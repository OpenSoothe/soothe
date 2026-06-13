"""Internal EventBus for AL ↔ GE ↔ AP coordination (RFC-222).

This module provides an in-memory async event dispatch system for
internal coordination between StrangeLoop, GoalEngine, and AutopilotService.
Internal events use the `soothe.internal.*` namespace and never leak
to external clients (WebSocket, TUI).

Architecture:
- InternalEventBus: Async pub/sub dispatcher
- Internal events: soothe.internal.goal.*, soothe.internal.loop.*, etc.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class InternalEventBus:
    """In-memory async event dispatch for AL ↔ GE ↔ AP.

    Provides pub/sub semantics for internal coordination events.
    All handlers are async and called in subscription order.
    Errors in handlers are logged but don't fail the emit.

    Thread-safe via asyncio.Lock for concurrent emit/subscribe.

    Usage:
        bus = InternalEventBus()
        bus.subscribe("soothe.internal.goal.completed", ge.handle_goal_completed)
        await bus.emit(InternalGoalCompletedEvent(...))
    """

    def __init__(self) -> None:
        """Initialize the internal event bus."""
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Register handler for event type.

        Handlers are called in subscription order on emit.
        Multiple handlers can subscribe to the same event type.

        Args:
            event_type: Event type string (e.g., "soothe.internal.goal.completed").
            handler: Async callable to receive the event.
        """
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.debug(
            "Subscribed handler to %s (total: %d)", event_type, len(self._subscribers[event_type])
        )

    def unsubscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Remove handler registration.

        Args:
            event_type: Event type string.
            handler: Handler to remove.
        """
        if event_type in self._subscribers:
            before = len(self._subscribers[event_type])
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]
            after = len(self._subscribers[event_type])
            if after < before:
                logger.debug("Unsubscribed handler from %s (remaining: %d)", event_type, after)

    async def emit(self, event: BaseModel) -> None:
        """Dispatch event to all subscribers.

        Handlers are called sequentially in subscription order.
        Handler errors are logged but don't prevent other handlers.

        The internal lock is held ONLY long enough to snapshot the handler
        list — it is released before any handler runs. This is critical:
        handlers commonly emit further events (e.g. AutopilotService's
        ``_handle_goal_state_changed`` calls ``_mark_loop_idle`` which
        emits more events), and holding the lock across handler execution
        would deadlock the bus.

        Args:
            event: Pydantic event model with `type` field.
        """
        event_type = getattr(event, "type", None) or event.__class__.__name__
        async with self._lock:
            handlers = list(self._subscribers.get(event_type, ()))

        if not handlers:
            logger.debug("No subscribers for %s", event_type)
            return

        logger.debug("Emitting %s to %d handlers", event_type, len(handlers))
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.warning(
                    "Handler for %s failed: %s",
                    event_type,
                    handler.__name__,
                    exc_info=True,
                )

    def has_subscribers(self, event_type: str) -> bool:
        """Check if event type has subscribers.

        Args:
            event_type: Event type string.

        Returns:
            True if any handlers subscribed.
        """
        return bool(self._subscribers.get(event_type))

    def subscriber_count(self, event_type: str) -> int:
        """Get subscriber count for event type.

        Args:
            event_type: Event type string.

        Returns:
            Number of subscribed handlers.
        """
        return len(self._subscribers.get(event_type, []))


# Singleton instance for internal coordination
_internal_bus: InternalEventBus | None = None


def get_internal_bus() -> InternalEventBus:
    """Get the singleton InternalEventBus instance.

    .. deprecated:: RFC-222 Q8
        This singleton is deprecated. New code MUST construct its own
        ``InternalEventBus`` and inject it where needed. Module-global state
        creates spooky coupling across ``AutopilotService`` instances and
        breaks isolation between tests. The singleton is kept solely as a
        fallback for the preserved-unwired ``FileLockMiddleware`` and for
        backward compatibility with older test fixtures.

    Returns:
        The singleton InternalEventBus.
    """
    global _internal_bus
    if _internal_bus is None:
        _internal_bus = InternalEventBus()
        logger.info("Internal EventBus initialized")
    return _internal_bus


def reset_internal_bus() -> None:
    """Reset the singleton InternalEventBus.

    Used in tests to isolate between test cases.
    """
    global _internal_bus
    _internal_bus = None
