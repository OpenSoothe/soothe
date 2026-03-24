"""Event bus for topic-based event routing (RFC-0013)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        """Publish event to all subscribers of topic.

        Args:
            topic: Topic identifier (e.g., "thread:abc123")
            event: Event dictionary to broadcast
        """
        async with self._lock:
            queues = self._subscribers.get(topic, set()).copy()

        if not queues:
            logger.debug("No subscribers for topic %s", topic)
            return

        # Send to all subscriber queues concurrently
        dropped = 0
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
                logger.warning("Queue full for topic %s, dropping event", topic)

        logger.debug("Published event to topic %s: %d delivered, %d dropped", topic, len(queues) - dropped, dropped)

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
