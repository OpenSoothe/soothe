"""Tests for AutopilotService(subscribe_to_bus=...) flag (RFC-222 revised, Phase B, RFC-625).

The daemon's daemon-owned AutopilotService must coexist with the per-runner
AutopilotService until Phase D retires the latter. They share the singleton
InternalEventBus, so the daemon instance must pass subscribe_to_bus=False
to avoid double-handling every event.
"""

from __future__ import annotations

from soothe.config.models import AutonomousConfig
from soothe.foundation.autopilot.service import AutopilotService
from soothe.foundation.context import ContextEngine
from soothe.foundation.events.internal_bus import InternalEventBus
from soothe.foundation.events.internal_events import (
    INTERNAL_GOAL_STATE_CHANGED,
    INTERNAL_GOALS_READY,
)


def _config() -> AutonomousConfig:
    return AutonomousConfig(max_loops=2, max_parallel_goals=2)


class TestSubscribeToBusFlag:
    def test_default_subscribes(self) -> None:
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(ce=ce, config=_config(), internal_bus=bus)
        assert svc._subscribed is True
        assert bus.subscriber_count(INTERNAL_GOAL_STATE_CHANGED) == 1
        assert bus.subscriber_count(INTERNAL_GOALS_READY) == 1

    def test_explicit_true_subscribes(self) -> None:
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(ce=ce, config=_config(), internal_bus=bus, subscribe_to_bus=True)
        assert svc._subscribed is True
        assert bus.subscriber_count(INTERNAL_GOAL_STATE_CHANGED) == 1

    def test_false_does_not_subscribe(self) -> None:
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(ce=ce, config=_config(), internal_bus=bus, subscribe_to_bus=False)
        assert svc._subscribed is False
        assert bus.subscriber_count(INTERNAL_GOAL_STATE_CHANGED) == 0
        assert bus.subscriber_count(INTERNAL_GOALS_READY) == 0

    def test_coexistence_only_one_subscriber_fires(self) -> None:
        """Two AutopilotService instances sharing a bus: only the
        subscribing one handles events."""
        bus = InternalEventBus()
        ce = ContextEngine()
        svc_subscribed = AutopilotService(
            ce=ce, config=_config(), internal_bus=bus, subscribe_to_bus=True
        )
        svc_dormant = AutopilotService(
            ce=ce, config=_config(), internal_bus=bus, subscribe_to_bus=False
        )
        assert svc_subscribed._subscribed is True
        assert svc_dormant._subscribed is False
        # Bus sees exactly one handler per relevant topic.
        assert bus.subscriber_count(INTERNAL_GOAL_STATE_CHANGED) == 1
        assert bus.subscriber_count(INTERNAL_GOALS_READY) == 1

    def test_dormant_service_still_callable(self) -> None:
        """Dormant service must still be a usable object (just not subscribed)."""
        bus = InternalEventBus()
        ce = ContextEngine()
        svc = AutopilotService(ce=ce, config=_config(), internal_bus=bus, subscribe_to_bus=False)
        status = svc.status()
        assert status["running"] is False
        # has_real_dispatch is False without a runner_factory
        assert svc.has_real_dispatch is False
