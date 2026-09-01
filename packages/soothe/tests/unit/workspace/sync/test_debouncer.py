"""Tests for the checkpoint debouncer.

Tests verify:
    - Debounce timer fires after the configured window.
    - Multiple dirty events within the window collapse to one trigger.
    - Max-interval timer fires even under continuous activity.
    - Backpressure (P10) doubles the debounce window.
    - flush() forces an immediate checkpoint.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from soothe.workspace.sync.debouncer import CheckpointDebouncer

if TYPE_CHECKING:
    pass


class TestDebouncer:
    """Tests for the CheckpointDebouncer."""

    @pytest.mark.asyncio
    async def test_debounce_fires_after_window(self) -> None:
        """Debounce timer fires after the configured window."""
        triggered = asyncio.Event()

        async def trigger() -> None:
            triggered.set()

        debouncer = CheckpointDebouncer(
            trigger=trigger, debounce_seconds=0.1, max_interval_seconds=999
        )
        debouncer.start()
        debouncer.notify_dirty()

        try:
            await asyncio.wait_for(triggered.wait(), timeout=1.0)
            assert triggered.is_set()
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_multiple_events_collapse(self) -> None:
        """Multiple dirty events within the window collapse to one trigger."""
        call_count = 0

        async def trigger() -> None:
            nonlocal call_count
            call_count += 1

        debouncer = CheckpointDebouncer(
            trigger=trigger, debounce_seconds=0.15, max_interval_seconds=999
        )
        debouncer.start()

        # Send multiple events within the debounce window.
        debouncer.notify_dirty()
        await asyncio.sleep(0.05)
        debouncer.notify_dirty()
        await asyncio.sleep(0.05)
        debouncer.notify_dirty()

        try:
            await asyncio.sleep(0.3)
            assert call_count == 1
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_no_trigger_without_dirty(self) -> None:
        """No trigger fires when no dirty events arrive."""
        call_count = 0

        async def trigger() -> None:
            nonlocal call_count
            call_count += 1

        debouncer = CheckpointDebouncer(
            trigger=trigger, debounce_seconds=0.1, max_interval_seconds=999
        )
        debouncer.start()

        try:
            await asyncio.sleep(0.3)
            assert call_count == 0
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_max_interval_triggers(self) -> None:
        """Max-interval timer fires even under continuous activity."""
        call_count = 0

        async def trigger() -> None:
            nonlocal call_count
            call_count += 1

        debouncer = CheckpointDebouncer(
            trigger=trigger,
            debounce_seconds=999,  # very long — only max-interval fires
            max_interval_seconds=0.2,
        )
        debouncer.start()
        debouncer.notify_dirty()  # mark dirty

        try:
            await asyncio.sleep(0.5)
            assert call_count >= 1
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_backpressure_doubles_debounce(self) -> None:
        """P10: when pending > max_pending, debounce window doubles."""
        triggered = asyncio.Event()

        async def trigger() -> None:
            triggered.set()

        debouncer = CheckpointDebouncer(
            trigger=trigger,
            debounce_seconds=0.1,
            max_interval_seconds=999,
            max_pending=5,
        )
        debouncer.start()
        debouncer.set_pending_count(10)  # exceeds max_pending=5
        debouncer.notify_dirty()

        try:
            # After 0.1s (normal debounce), the trigger should NOT fire
            # because backpressure doubled the window to 0.2s.
            await asyncio.sleep(0.15)
            assert not triggered.is_set()

            # After 0.3s total, the doubled window should have fired.
            await asyncio.wait_for(triggered.wait(), timeout=0.5)
            assert triggered.is_set()
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_flush_forces_immediate_checkpoint(self) -> None:
        """flush() bypasses the debounce timer."""
        call_count = 0

        async def trigger() -> None:
            nonlocal call_count
            call_count += 1

        debouncer = CheckpointDebouncer(
            trigger=trigger, debounce_seconds=999, max_interval_seconds=999
        )
        debouncer.start()
        debouncer.notify_dirty()

        try:
            await debouncer.flush()
            assert call_count == 1
        finally:
            await debouncer.stop()

    @pytest.mark.asyncio
    async def test_flush_no_op_when_clean(self) -> None:
        """flush() does nothing when there are no dirty changes."""
        call_count = 0

        async def trigger() -> None:
            nonlocal call_count
            call_count += 1

        debouncer = CheckpointDebouncer(
            trigger=trigger, debounce_seconds=999, max_interval_seconds=999
        )
        debouncer.start()

        try:
            await debouncer.flush()
            assert call_count == 0
        finally:
            await debouncer.stop()
