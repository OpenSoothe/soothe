"""Event bus for topic-based event routing (RFC-0013).

IG-258 Phase 2: Lock-free publish with reader-writer pattern.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from soothe.events import EventPriority

if TYPE_CHECKING:
    from soothe.events import EventMeta

    from soothe_daemon.event.size_stats import EventSizeDistributionCollector

logger = logging.getLogger(__name__)

# IG-392: When consumer < producer, NORMAL/HIGH drops can happen at very high rate
# (streaming + subagents). Per-drop WARNING spam obscures real issues and I/O. Throttle
# to at most one WARNING per topic per interval. (Timeout is correlated, not causal:
# the queue fills during long streams; timeout ends the wait.)
_NORMAL_DROP_LOG_LAST: dict[str, float] = {}
_HIGH_DROP_LOG_LAST: dict[str, float] = {}
_NO_SUBSCRIBER_LOG_LAST: dict[str, float] = {}
_DROP_LOG_INTERVAL_SEC = 5.0

# IG-534 Phase 0: Drop counters for observability (thread-safe for concurrent publishers)
_drop_counters: dict[str, int] = {}  # key: f"{priority}|{topic}"
_drop_counters_lock = threading.Lock()


def _increment_drop_counter(priority: str, topic: str) -> int:
    """Increment drop counter and return current total (IG-534)."""
    key = f"{priority}|{topic}"
    with _drop_counters_lock:
        _drop_counters[key] = _drop_counters.get(key, 0) + 1
        return _drop_counters[key]


def get_event_bus_drop_counts() -> dict[str, int]:
    """Return snapshot of drop counters for daemon_status (IG-534 Phase 0).

    Returns dict mapping ``priority|topic`` to cumulative drop count.
    """
    with _drop_counters_lock:
        return dict(_drop_counters)


def _effective_queue_max(queue: asyncio.Queue[Any]) -> int:
    """Bounded queue max size for capacity math (0 = unlimited → treat as large cap)."""
    m = queue.maxsize
    if m == 0:
        return 10000  # match default client_session queue; heuristic for "unlimited"
    return m


def _throttle_log(
    last_map: dict[str, float],
    topic: str,
    *,
    interval: float,
) -> bool:
    """Return True if we should emit a log line for this topic (rate-limited)."""
    now = time.monotonic()
    prev = last_map.get(topic, 0.0)
    if now - prev >= interval:
        last_map[topic] = now
        return True
    return False


def _wire_has_goal_completion_phase(event: dict[str, Any]) -> bool:
    """Return True when a wire event carries goal_completion synthesis."""
    if event.get("type") != "event" or event.get("mode") != "messages":
        return False
    data = event.get("data")
    if not isinstance(data, (tuple, list)) or not data:
        return False
    msg = data[0]
    return isinstance(msg, dict) and msg.get("phase") == "goal_completion"


def _resolve_publish_priority(
    event: dict[str, Any],
    event_meta: EventMeta | None,
) -> EventPriority:
    """Resolve effective priority for one publish, including wire overrides."""
    priority = event_meta.priority if event_meta else EventPriority.NORMAL
    if (
        event_meta is None
        and event.get("type") == "status"
        and event.get("state") in ("running", "idle")
    ):
        return EventPriority.CRITICAL
    if _wire_has_goal_completion_phase(event) and priority.value > EventPriority.HIGH.value:
        return EventPriority.HIGH
    return priority


def _should_block_on_queue_full(
    event: dict[str, Any],
    event_meta: EventMeta | None,
    priority: EventPriority,
    *,
    queue_size: int,
    queue_max: int,
) -> bool:
    """Return True when a full queue must block rather than drop this event."""
    if priority == EventPriority.CRITICAL:
        return True
    if _wire_has_goal_completion_phase(event):
        return True
    top_type = event.get("type") if isinstance(event, dict) else None
    if top_type in ("event_batch", "tool_call_updates_batch"):
        return queue_size >= int(queue_max * 0.8)
    if priority == EventPriority.NORMAL and queue_size >= int(queue_max * 0.9):
        return _is_user_visible_for_backpressure(event, event_meta)
    return False


def _is_user_visible_for_backpressure(
    event: dict[str, Any],
    event_meta: EventMeta | None,
) -> bool:
    """Return True for wire frames that must not be silently dropped under pressure."""
    from soothe.events.visibility import (
        WireEnvelopeKind,
        classify_wire_envelope,
        event_type_from_wire_message,
        is_catalog_event_client_wire_visible,
    )

    kind = classify_wire_envelope(event)
    if kind in (
        WireEnvelopeKind.EVENT_MESSAGES,
        WireEnvelopeKind.EVENT_UPDATES,
        WireEnvelopeKind.CONTROL,
    ):
        return True
    if kind is WireEnvelopeKind.EVENT_CATALOG:
        wire_type = event_type_from_wire_message(event) or ""
        return is_catalog_event_client_wire_visible(wire_type, event_meta)
    return False


class EventBus:
    """Async pub/sub event bus with lock-free publishing (IG-258 Phase 2).

    Phase 2 improvements:
    - Lock-free publish (no asyncio.Lock in hot path)
    - Write lock only for subscribe/unsubscribe (writer operations)
    - Direct dict read (atomic in Python)
    - Multiple concurrent publishers (no contention)

    IG-475: Added cleanup_orphaned_topics() to remove topics with no subscribers.

    The event bus implements topic-based routing where publishers emit
    events to specific topics and subscribers receive events for topics
    they've subscribed to.

    Topic format (IG-408):
        ``loop:{loop_id}`` — primary; client subscriptions and daemon ``_broadcast``
        scoped delivery.
        ``global`` — daemon-wide frames (e.g. some status, command_response).

    Example (loop-scoped):
        >>> bus = EventBus()
        >>> queue = asyncio.Queue()
        >>> await bus.subscribe("loop:abc123", queue)
        >>> await bus.publish("loop:abc123", {"type": "event", "loop_id": "abc123"})
        >>> event = await queue.get()
        >>> print(event["loop_id"])
        abc123
    """

    def __init__(
        self,
        *,
        event_size_stats: EventSizeDistributionCollector | None = None,
    ) -> None:
        """Initialize the event bus with lock-free publish (Phase 2).

        Args:
            event_size_stats: Optional collector for streaming wire-size stats (IG-403).
        """
        # Regular dict (atomic read, no lock needed)
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        # Write lock only for subscribe/unsubscribe (IG-258 Phase 2)
        self._write_lock = asyncio.Lock()
        self._event_size_stats = event_size_stats
        # IG-475: Track orphaned topics for cleanup
        self._topics_with_no_subscribers_log: set[str] = set()

    async def publish(
        self,
        topic: str,
        event: dict[str, Any],
        event_meta: EventMeta | None = None,
    ) -> None:
        """Publish event to all subscribers with lock-free hot path (IG-258 Phase 2).

        Phase 2 improvement: No lock acquisition for publish (reader operation).
        - Direct dict read (atomic in Python)
        - Multiple concurrent publishers
        - No contention in hot path

        Implements priority-aware overflow strategy (IG-258 Phase 1):
        - CRITICAL events: Never dropped, block until space available
        - HIGH events: Rarely dropped, warn if dropped
        - NORMAL events: Drop when full; one throttled warning per topic per interval
        - LOW events: Silent drop when queue near capacity (80%)

        Args:
            topic: Topic identifier (e.g., "loop:abc123")
            event: Event dictionary to broadcast
            event_meta: Optional EventMeta for filtering (RFC-0022) and priority (IG-258)
        """
        if self._event_size_stats is not None:
            self._event_size_stats.record_event_dict(event)

        # NO LOCK! Direct dict read (atomic in Python) - IG-258 Phase 2
        queues = self._subscribers.get(topic, set()).copy()

        # Early return if no subscribers (no lock needed)
        if not queues:
            if _throttle_log(
                _NO_SUBSCRIBER_LOG_LAST,
                topic,
                interval=_DROP_LOG_INTERVAL_SEC,
            ):
                wire_type = event.get("type") if isinstance(event, dict) else None
                logger.warning(
                    "No subscribers for topic %s; dropping event (type=%s)",
                    topic,
                    wire_type,
                )
            return

        priority = _resolve_publish_priority(event, event_meta)
        await asyncio.gather(
            *(
                self._deliver_to_subscriber(queue, topic, event, event_meta, priority)
                for queue in queues
            )
        )

    async def _deliver_to_subscriber(
        self,
        queue: asyncio.Queue[Any],
        topic: str,
        event: dict[str, Any],
        event_meta: EventMeta | None,
        priority: EventPriority,
    ) -> None:
        """Deliver one event to a single subscriber queue with priority policy."""
        queue_size = queue.qsize()
        queue_max = _effective_queue_max(queue)
        near_capacity = queue_size > (queue_max * 0.8)  # 80% threshold

        block_on_full = _should_block_on_queue_full(
            event,
            event_meta,
            priority,
            queue_size=queue_size,
            queue_max=queue_max,
        )

        # Fast drop when already at capacity (avoids exception per put on hot path).
        # HIGH events must not be dropped here (IG-258: "Rarely dropped"); they fall
        # through to put_nowait and block on QueueFull instead.
        if not block_on_full and priority == EventPriority.NORMAL and queue_size >= queue_max:
            _increment_drop_counter("NORMAL", topic)
            if _throttle_log(
                _NORMAL_DROP_LOG_LAST,
                topic,
                interval=_DROP_LOG_INTERVAL_SEC,
            ):
                logger.warning(
                    "Queue full for topic %s, dropping NORMAL priority events "
                    "(consumer slower than producer; suppressing similar logs %.0fs)",
                    topic,
                    _DROP_LOG_INTERVAL_SEC,
                )
            return

        try:
            # LOW priority: Skip when queue near capacity
            if near_capacity and priority == EventPriority.LOW:
                logger.debug(
                    "Skipping LOW priority event for queue at %d/%d capacity",
                    queue_size,
                    queue_max,
                )
                return

            # Try non-blocking put first
            queue.put_nowait((event, event_meta))
        except asyncio.QueueFull:
            # CRITICAL and protected events block until space is available.
            # HIGH events also block: per IG-258 they are "rarely dropped" and carry
            # tool/subagent results whose loss corrupts client state under load.
            if block_on_full or priority == EventPriority.HIGH:
                if priority == EventPriority.HIGH:
                    logger.warning(
                        "Queue full for HIGH priority event, blocking until space "
                        "available (topic=%s, queue=%d/%d)",
                        topic,
                        queue_size,
                        queue_max,
                    )
                else:
                    logger.warning(
                        "Queue full for protected event, blocking until space available "
                        "(topic=%s, priority=%s)",
                        topic,
                        priority.name,
                    )
                await queue.put((event, event_meta))
            elif priority == EventPriority.NORMAL:
                if _throttle_log(
                    _NORMAL_DROP_LOG_LAST,
                    topic,
                    interval=_DROP_LOG_INTERVAL_SEC,
                ):
                    logger.warning(
                        "Queue full for topic %s, dropping NORMAL priority events "
                        "(consumer backlog; suppressing similar logs %.0fs)",
                        topic,
                        _DROP_LOG_INTERVAL_SEC,
                    )
            # LOW priority: rare here (handled above); drop silently

    async def subscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Subscribe queue to receive events for topic with write lock (Phase 2).

        Args:
            topic: Topic identifier to subscribe to
            queue: AsyncIO queue to receive events
        """
        # Write lock for subscribe (writer operation) - IG-258 Phase 2
        async with self._write_lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(queue)

        logger.debug("Subscribed queue to topic %s", topic)

    async def unsubscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe queue from topic with write lock (Phase 2).

        Args:
            topic: Topic identifier to unsubscribe from
            queue: Queue to remove from subscribers
        """
        # Write lock for unsubscribe (writer operation) - IG-258 Phase 2
        async with self._write_lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

        logger.debug("Unsubscribed queue from topic %s", topic)

    async def unsubscribe_all(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe queue from all topics with write lock (Phase 2).

        Args:
            queue: Queue to remove from all subscribers
        """
        # Write lock for unsubscribe_all (writer operation) - IG-258 Phase 2
        async with self._write_lock:
            topics_to_remove = []
            for topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    topics_to_remove.append(topic)

            for topic in topics_to_remove:
                del self._subscribers[topic]

        logger.debug("Unsubscribed queue from all topics")

    async def cleanup_orphaned_topics(self) -> int:
        """Remove topics with empty subscriber sets (IG-475).

        Periodically called by daemon to clean up topics that were not properly
        removed during unsubscribe (e.g., due to race conditions or early disconnects).

        Returns:
            Number of orphaned topics removed.
        """
        async with self._write_lock:
            orphaned = [topic for topic, queues in self._subscribers.items() if not queues]
            for topic in orphaned:
                del self._subscribers[topic]
                self._topics_with_no_subscribers_log.discard(topic)
            if orphaned:
                logger.info("Cleaned up %d orphaned event bus topics", len(orphaned))
            return len(orphaned)

    def get_subscriber_count(self, topic: str) -> int:
        """Return number of subscribers for a topic (no lock needed, atomic read).

        Args:
            topic: Topic identifier.

        Returns:
            Number of active subscriber queues for the topic.
        """
        return len(self._subscribers.get(topic, set()))

    @property
    def topic_count(self) -> int:
        """Return number of active topics (no lock needed, atomic read)."""
        return len(self._subscribers)
