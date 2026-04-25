"""Event bus for topic-based event routing (RFC-0013)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe.core.event_catalog import EventPriority

if TYPE_CHECKING:
    from soothe.core.event_catalog import EventMeta

logger = logging.getLogger(__name__)


class EventBus:
    """Async pub/sub event bus for routing events to subscribers.

    The event bus implements topic-based routing where publishers emit
    events to specific topics and subscribers receive events for topics
    they've subscribed to.

    Topic Format:
        "thread:{thread_id}" - Events for a specific conversation thread

    Example:
        >>> bus = EventBus()
        >>> queue = asyncio.Queue()
        >>> await bus.subscribe("thread:abc123", queue)
        >>> await bus.publish("thread:abc123", {"type": "event", "data": "hello"})
        >>> event = await queue.get()
        >>> print(event)
        {'type': 'event', 'data': 'hello'}
    """

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        topic: str,
        event: dict[str, Any],
        event_meta: EventMeta | None = None,
    ) -> None:
        """Publish event to all subscribers of topic with optional metadata.

        Implements priority-aware overflow strategy (IG-258):
        - CRITICAL events: Never dropped, block until space available
        - HIGH events: Rarely dropped, warn if dropped
        - NORMAL events: Standard drop with warning
        - LOW events: Silent drop when queue near capacity (80%)

        Args:
            topic: Topic identifier (e.g., "thread:abc123")
            event: Event dictionary to broadcast
            event_meta: Optional EventMeta for filtering (RFC-0022) and priority (IG-258)
        """
        async with self._lock:
            queues = self._subscribers.get(topic, set()).copy()

        if not queues:
            return

        # Send (event, event_meta) tuple to queues for filtering (RFC-0022)
        dropped = 0
        for queue in queues:
            # IG-258: Priority-aware overflow strategy
            queue_size = queue.qsize()
            queue_max = 10000  # Default maxsize from client_session.py
            near_capacity = queue_size > (queue_max * 0.8)  # 80% threshold

            # Get event priority from metadata
            priority = event_meta.priority if event_meta else EventPriority.NORMAL

            try:
                # LOW priority: Skip when queue near capacity
                if near_capacity and priority == EventPriority.LOW:
                    logger.debug(
                        "Skipping LOW priority event for queue at %d/%d capacity",
                        queue_size,
                        queue_max,
                    )
                    dropped += 1
                    continue

                # Try non-blocking put first
                queue.put_nowait((event, event_meta))
            except asyncio.QueueFull:
                # CRITICAL events: Block until space available (never drop)
                if priority == EventPriority.CRITICAL:
                    logger.warning(
                        "Queue full for CRITICAL event, blocking until space available (topic=%s)",
                        topic,
                    )
                    await queue.put((event, event_meta))
                else:
                    # Other priorities: Drop with appropriate logging
                    dropped += 1
                    if priority == EventPriority.HIGH:
                        logger.error(
                            "Dropped HIGH priority event due to queue overflow (topic=%s, queue=%d/%d)",
                            topic,
                            queue_size,
                            queue_max,
                        )
                    elif priority == EventPriority.NORMAL:
                        logger.warning(
                            "Queue full for topic %s, dropping NORMAL priority event",
                            topic,
                        )
                    # LOW priority already handled above with debug log

    async def subscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Subscribe queue to receive events for topic.

        Args:
            topic: Topic identifier to subscribe to
            queue: AsyncIO queue to receive events
        """
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(queue)

        logger.debug("Subscribed queue to topic %s", topic)

    async def unsubscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe queue from topic.

        Args:
            topic: Topic identifier to unsubscribe from
            queue: Queue to remove from subscribers
        """
        async with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

        logger.debug("Unsubscribed queue from topic %s", topic)

    async def unsubscribe_all(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe queue from all topics.

        Args:
            queue: Queue to remove from all subscribers
        """
        async with self._lock:
            topics_to_remove = []
            for topic in self._subscribers:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    topics_to_remove.append(topic)

            for topic in topics_to_remove:
                del self._subscribers[topic]

        logger.debug("Unsubscribed queue from all topics")

    @property
    def topic_count(self) -> int:
        """Return number of active topics."""
        return len(self._subscribers)
