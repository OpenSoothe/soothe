"""Unit tests for Internal EventBus (RFC-222, IG-295)."""

import pytest

from soothe.core.events.internal_bus import InternalEventBus, get_internal_bus, reset_internal_bus
from soothe.core.events.internal_events import (
    INTERNAL_GOAL_COMPLETED,
    INTERNAL_GOAL_STATE_CHANGED,
    InternalGoalCompletedEvent,
    InternalGoalStateChangedEvent,
)


class TestInternalEventBus:
    """Tests for InternalEventBus class."""

    def test_create_bus(self) -> None:
        """Test basic EventBus creation."""
        bus = InternalEventBus()
        assert bus._subscribers == {}
        assert not bus.has_subscribers("any.event")

    def test_subscribe(self) -> None:
        """Test subscribing to event type."""
        bus = InternalEventBus()
        handler_called = False

        async def handler(event: object) -> None:
            nonlocal handler_called
            handler_called = True

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler)

        assert bus.has_subscribers(INTERNAL_GOAL_COMPLETED)
        assert bus.subscriber_count(INTERNAL_GOAL_COMPLETED) == 1

    def test_subscribe_multiple_handlers(self) -> None:
        """Test multiple handlers for same event type."""
        bus = InternalEventBus()

        async def handler1(event: object) -> None:
            pass

        async def handler2(event: object) -> None:
            pass

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler1)
        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler2)

        assert bus.subscriber_count(INTERNAL_GOAL_COMPLETED) == 2

    def test_unsubscribe(self) -> None:
        """Test unsubscribing handler."""
        bus = InternalEventBus()

        async def handler(event: object) -> None:
            pass

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler)
        bus.unsubscribe(INTERNAL_GOAL_COMPLETED, handler)

        assert not bus.has_subscribers(INTERNAL_GOAL_COMPLETED)

    @pytest.mark.asyncio
    async def test_emit_calls_handlers(self) -> None:
        """Test emit calls all handlers."""
        bus = InternalEventBus()
        call_order: list[str] = []

        async def handler1(event: object) -> None:
            call_order.append("handler1")

        async def handler2(event: object) -> None:
            call_order.append("handler2")

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler1)
        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler2)

        event = InternalGoalCompletedEvent(goal_id="g1", loop_id="l1", plan_result={})
        await bus.emit(event)

        assert call_order == ["handler1", "handler2"]

    @pytest.mark.asyncio
    async def test_emit_no_subscribers(self) -> None:
        """Test emit with no subscribers."""
        bus = InternalEventBus()
        event = InternalGoalCompletedEvent(goal_id="g1", loop_id="l1", plan_result={})

        # Should not raise, just log
        await bus.emit(event)

    @pytest.mark.asyncio
    async def test_emit_handler_error_doesnt_fail(self) -> None:
        """Test handler errors are logged but don't fail emit."""
        bus = InternalEventBus()
        handler2_called = False

        async def failing_handler(event: object) -> None:
            raise RuntimeError("Handler error")

        async def handler2(event: object) -> None:
            nonlocal handler2_called
            handler2_called = True

        bus.subscribe(INTERNAL_GOAL_COMPLETED, failing_handler)
        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler2)

        event = InternalGoalCompletedEvent(goal_id="g1", loop_id="l1", plan_result={})
        await bus.emit(event)

        # Second handler should still be called despite first failing
        assert handler2_called

    @pytest.mark.asyncio
    async def test_emit_sync_handler(self) -> None:
        """Test emit works with sync handlers."""
        bus = InternalEventBus()
        handler_called = False

        def sync_handler(event: object) -> None:
            nonlocal handler_called
            handler_called = True

        bus.subscribe(INTERNAL_GOAL_STATE_CHANGED, sync_handler)

        event = InternalGoalStateChangedEvent(
            goal_id="g1", old_status="pending", new_status="active"
        )
        await bus.emit(event)

        assert handler_called

    def test_subscriber_count(self) -> None:
        """Test subscriber count."""
        bus = InternalEventBus()

        async def handler(event: object) -> None:
            pass

        assert bus.subscriber_count("nonexistent") == 0

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler)
        assert bus.subscriber_count(INTERNAL_GOAL_COMPLETED) == 1

    def test_has_subscribers(self) -> None:
        """Test has_subscribers check."""
        bus = InternalEventBus()

        async def handler(event: object) -> None:
            pass

        assert not bus.has_subscribers(INTERNAL_GOAL_COMPLETED)

        bus.subscribe(INTERNAL_GOAL_COMPLETED, handler)
        assert bus.has_subscribers(INTERNAL_GOAL_COMPLETED)


class TestSingletonBus:
    """Tests for singleton InternalEventBus."""

    def test_get_internal_bus_returns_singleton(self) -> None:
        """Test get_internal_bus returns same instance."""
        reset_internal_bus()

        bus1 = get_internal_bus()
        bus2 = get_internal_bus()

        assert bus1 is bus2

    def test_reset_internal_bus(self) -> None:
        """Test reset_internal_bus clears singleton."""
        bus1 = get_internal_bus()
        reset_internal_bus()
        bus2 = get_internal_bus()

        assert bus1 is not bus2
