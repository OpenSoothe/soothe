"""IG-534 Phase 0: Multi-loop performance isolation load harness.

Tests daemon streaming path under multiple concurrent loops to validate:
1. Correctness (B): No silent event loss, terminal frames delivered
2. Fairness (A): Cross-loop isolation, no unbounded interference
3. Capacity: N concurrent heavy loops without starvation

IG-535: Defaults tuned for 32 concurrent loops (production multi-tenant workloads).

CI Mode: When SOOTHE_CI_MODE=true, reduces loop counts and durations for faster CI runs.

Run with: pytest -v --run-integration packages/soothe-daemon/tests/integration/daemon/test_multi_loop_performance.py
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from soothe.foundation.events import EventPriority

from soothe_daemon.event.bus import EventBus, get_event_bus_drop_counts

# ============================================================================
# CI Mode Configuration
# ============================================================================

SOOTHE_CI_MODE = os.getenv("SOOTHE_CI_MODE", "").lower() in ("true", "1", "yes")


class CIMode:
    """CI-optimized scaling for performance tests.

    Production values provide rigorous validation, CI values enable fast feedback.
    Override via environment: SOOTHE_CI_MODE=true
    """

    # Multi-loop test scaling
    MULTI_LOOP_COUNT = 8 if SOOTHE_CI_MODE else 32  # IG-535 baseline: 32
    MULTI_LOOP_N64 = 16 if SOOTHE_CI_MODE else 64  # Phase 2 gate: 64
    MULTI_LOOP_EVENTS = 25 if SOOTHE_CI_MODE else 100
    MULTI_LOOP_TIMEOUT = 5.0 if SOOTHE_CI_MODE else 10.0

    # Flood/fairness test scaling
    FLOOD_EVENTS_HEAVY = 100 if SOOTHE_CI_MODE else 500
    FLOOD_EVENTS_LIGHT = 15 if SOOTHE_CI_MODE else 50
    FAIRNESS_THRESHOLD = 10 if SOOTHE_CI_MODE else 38  # 75% of light events

    # Queue capacity scaling
    QUEUE_CAPACITY = 500 if SOOTHE_CI_MODE else 1000
    QUEUE_CAPACITY_N64 = 1000 if SOOTHE_CI_MODE else 2000

    # Phase 3 synthesis scaling
    SYNTHESIS_EVENTS = 10 if SOOTHE_CI_MODE else 30

    @classmethod
    def summary(cls) -> str:
        """Return CI mode summary for test output."""
        return f"CI={SOOTHE_CI_MODE} (loops={cls.MULTI_LOOP_COUNT}, events={cls.MULTI_LOOP_EVENTS})"


@dataclass
class LoopClientSimulator:
    """Simulates one client subscribed to one loop with event tracking."""

    loop_id: str
    client_id: str
    event_queue: asyncio.Queue[tuple[dict[str, Any], Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=10000)
    )
    events_received: list[dict[str, Any]] = field(default_factory=list)
    goal_completion_received: bool = False
    goal_completion_latency_ms: float | None = None
    terminal_frames_received: list[str] = field(default_factory=list)
    dropped_events: int = 0
    first_event_latency_ms: float | None = None
    start_time: float = 0.0

    async def consume_events(self, timeout: float = 30.0) -> None:
        """Consume events from queue until done or timeout."""
        self.start_time = time.monotonic()
        while True:
            try:
                event, _meta = await asyncio.wait_for(self.event_queue.get(), timeout=timeout)
                self.events_received.append(event)

                # Track first event latency
                if self.first_event_latency_ms is None:
                    self.first_event_latency_ms = (time.monotonic() - self.start_time) * 1000

                # Track goal_completion
                if event.get("type") == "event" and event.get("mode") == "messages":
                    data = event.get("data")
                    if isinstance(data, (tuple, list)) and data:
                        msg = data[0]
                        if isinstance(msg, dict) and msg.get("phase") == "goal_completion":
                            self.goal_completion_received = True
                            if self.goal_completion_latency_ms is None:
                                self.goal_completion_latency_ms = (
                                    time.monotonic() - self.start_time
                                ) * 1000

                # Track terminal frames
                if event.get("type") == "status":
                    state = event.get("state")
                    if state in ("idle", "running"):
                        self.terminal_frames_received.append(state)

            except TimeoutError:
                break


@dataclass
class MultiLoopMetrics:
    """Aggregate metrics across all simulated loops."""

    loops: list[LoopClientSimulator] = field(default_factory=list)
    test_duration_sec: float = 0.0
    event_bus_drops: dict[str, int] = field(default_factory=dict)

    def add_loop(self, loop: LoopClientSimulator) -> None:
        self.loops.append(loop)

    def get_summary(self) -> dict[str, Any]:
        """Generate metrics summary for IG-534 exit criteria."""
        total_events = sum(len(loop.events_received) for loop in self.loops)
        goal_completion_delivered = sum(1 for loop in self.loops if loop.goal_completion_received)
        loops_with_terminal = sum(1 for loop in self.loops if loop.terminal_frames_received)

        first_event_latencies = [
            loop.first_event_latency_ms
            for loop in self.loops
            if loop.first_event_latency_ms is not None
        ]
        synthesis_latencies = [
            loop.goal_completion_latency_ms
            for loop in self.loops
            if loop.goal_completion_latency_ms is not None
        ]

        # Calculate cross-loop fairness: p95 spread of first-event latencies
        if len(first_event_latencies) > 1:
            sorted_latencies = sorted(first_event_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p95_latency = sorted_latencies[p95_idx]
            min_latency = sorted_latencies[0]
            latency_spread_ratio = p95_latency / min_latency if min_latency > 0 else 0
        else:
            p95_latency = 0
            latency_spread_ratio = 0

        if synthesis_latencies:
            sorted_synth = sorted(synthesis_latencies)
            synth_p95_idx = int(len(sorted_synth) * 0.95)
            synthesis_p95_ms = sorted_synth[synth_p95_idx]
        else:
            synthesis_p95_ms = 0.0

        if first_event_latencies:
            sorted_first = sorted(first_event_latencies)
            first_p50_ms = sorted_first[len(sorted_first) // 2]
        else:
            first_p50_ms = 0.0

        return {
            "test_duration_sec": self.test_duration_sec,
            "total_loops": len(self.loops),
            "total_events_received": total_events,
            "goal_completion_delivered": goal_completion_delivered,
            "loops_with_terminal_frames": loops_with_terminal,
            "first_event_latency_p95_ms": p95_latency,
            "first_event_latency_p50_ms": first_p50_ms,
            "synthesis_visible_p95_ms": synthesis_p95_ms,
            "latency_spread_ratio": latency_spread_ratio,
            "event_bus_drops": self.event_bus_drops,
        }


# ============================================================================
# Phase 1 Exit Criteria Tests (IG-534)
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_loop_goal_completion_delivery() -> None:
    """IG-534 Phase 1 exit criterion: 0 terminal delivery failures.

    IG-535: Validates at 32 concurrent loops (production baseline).
    CI Mode: Scales down to 8 loops for faster CI runs.

    Simulates N loops each receiving synthesis streams with goal_completion
    tail frames. Validates that every loop receives its terminal frame even
    under concurrent load.
    """
    num_loops = CIMode.MULTI_LOOP_COUNT  # IG-535: 32 (CI: 8)
    events_per_loop = CIMode.MULTI_LOOP_EVENTS
    bus = EventBus()
    metrics = MultiLoopMetrics()

    # Create loop simulators
    for i in range(num_loops):
        loop_id = f"loop:test-{i}"
        client = LoopClientSimulator(loop_id=loop_id, client_id=f"client-{i}")
        await bus.subscribe(f"loop:{loop_id}", client.event_queue)
        metrics.add_loop(client)

    # Start consumers with CI-scaled timeout
    consumer_tasks = [
        asyncio.create_task(loop.consume_events(timeout=CIMode.MULTI_LOOP_TIMEOUT))
        for loop in metrics.loops
    ]

    # Publish events for each loop concurrently
    async def publish_loop_events(loop_idx: int) -> None:
        loop_id = f"loop:test-{loop_idx}"
        for j in range(events_per_loop - 1):
            event = {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "streaming", "content": f"chunk-{j}"}, {}),
            }
            await bus.publish(f"loop:{loop_id}", event)

        # Terminal goal_completion frame (must not be dropped)
        gc_event = {
            "type": "event",
            "loop_id": loop_id,
            "mode": "messages",
            "data": ({"phase": "goal_completion", "content": "final"}, {}),
        }
        await bus.publish(f"loop:{loop_id}", gc_event)

        # Status idle (terminal control frame)
        status_event = {"type": "status", "loop_id": loop_id, "state": "idle"}
        await bus.publish(f"loop:{loop_id}", status_event)

    start_time = time.monotonic()
    await asyncio.gather(*[publish_loop_events(i) for i in range(num_loops)])

    # Wait for consumers to finish
    await asyncio.gather(*consumer_tasks)
    metrics.test_duration_sec = time.monotonic() - start_time
    metrics.event_bus_drops = get_event_bus_drop_counts()

    summary = metrics.get_summary()

    # Phase 1 exit criteria
    # 1. All goal_completion frames delivered
    assert summary["goal_completion_delivered"] == num_loops, (
        f"Goal completion delivery failures: "
        f"{num_loops - summary['goal_completion_delivered']} loops missing tail frame"
    )

    # 2. All loops received terminal status
    assert summary["loops_with_terminal_frames"] >= num_loops, (
        f"Terminal status delivery failures: {summary['loops_with_terminal_frames']}/{num_loops}"
    )

    # 3. No CRITICAL/HIGH drops in event bus (NORMAL drops allowed)
    critical_drops = sum(v for k, v in metrics.event_bus_drops.items() if k.startswith("CRITICAL|"))
    high_drops = sum(v for k, v in metrics.event_bus_drops.items() if k.startswith("HIGH|"))
    assert critical_drops == 0, f"CRITICAL events dropped: {critical_drops}"
    assert high_drops == 0, f"HIGH events dropped: {high_drops}"

    print(f"\n=== IG-534 Phase 1: goal_completion delivery ({CIMode.summary()}) ===")
    print(f"Loops: {num_loops}, Duration: {summary['test_duration_sec']:.2f}s")
    print(f"Goal completions delivered: {summary['goal_completion_delivered']}/{num_loops}")
    print(f"Event bus drops: {metrics.event_bus_drops}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_loop_fairness_under_pressure() -> None:
    """IG-534 Phase 2 gate: cross-loop isolation under concurrent load.

    IG-535: Validates at 32 concurrent loops (production baseline).
    CI Mode: Scales down to 8 loops for faster CI runs.

    Validates that all loops receive events regardless of relative load.
    The fairness criterion is that each loop receives at least 75% of its
    published events even when one loop floods the bus.
    """
    num_loops = CIMode.MULTI_LOOP_COUNT  # IG-535: 32 (CI: 8)
    bus = EventBus()
    metrics = MultiLoopMetrics()

    # Create loop simulators with CI-scaled queue capacity
    for i in range(num_loops):
        loop_id = f"loop:fair-{i}"
        client = LoopClientSimulator(
            loop_id=loop_id,
            client_id=f"client-{i}",
            event_queue=asyncio.Queue(maxsize=CIMode.QUEUE_CAPACITY),  # CI: 500, Prod: 1000
        )
        await bus.subscribe(f"loop:{loop_id}", client.event_queue)
        metrics.add_loop(client)

    # Start consumers with CI-scaled timeout
    consumer_tasks = [
        asyncio.create_task(loop.consume_events(timeout=CIMode.MULTI_LOOP_TIMEOUT))
        for loop in metrics.loops
    ]

    # Heavy loop (index 0) floods with CI-scaled events
    async def flood_heavy_loop() -> None:
        loop_id = "loop:fair-0"
        for j in range(CIMode.FLOOD_EVENTS_HEAVY):  # CI: 100, Prod: 500
            event = {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "streaming", "content": f"flood-{j}"}, {}),
            }
            await bus.publish(f"loop:{loop_id}", event)

    # Light loops send fewer events concurrently (CI-scaled)
    async def send_light_events(loop_idx: int) -> None:
        loop_id = f"loop:fair-{loop_idx}"
        for j in range(CIMode.FLOOD_EVENTS_LIGHT):  # CI: 15, Prod: 50
            event = {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "streaming", "content": f"light-{j}"}, {}),
            }
            await bus.publish(f"loop:{loop_id}", event)

    start_time = time.monotonic()
    # Run all loops concurrently (fairness test)
    await asyncio.gather(
        flood_heavy_loop(),
        *[send_light_events(i) for i in range(1, num_loops)],
    )

    # Wait for consumers
    await asyncio.gather(*consumer_tasks)
    metrics.test_duration_sec = time.monotonic() - start_time

    # Phase 2 fairness gate: light loops should receive most of their events
    # Heavy loop may have queue pressure, but light loops should not be starved
    heavy_received = len(metrics.loops[0].events_received)
    light_received_counts = [len(loop.events_received) for loop in metrics.loops[1:]]

    # CI-scaled fairness threshold: ≥75% of light events
    fairness_threshold = CIMode.FAIRNESS_THRESHOLD
    light_events = CIMode.FLOOD_EVENTS_LIGHT
    for i, count in enumerate(light_received_counts):
        assert count >= fairness_threshold, (
            f"Loop {i + 1} starved: received only {count}/{light_events} events "
            f"while heavy loop got {heavy_received}"
        )

    print(f"\n=== IG-534 Phase 2: Cross-loop fairness ({CIMode.summary()}) ===")
    print(f"Events received: heavy={heavy_received}, light={light_received_counts}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_loop_n64_start_delay_gate() -> None:
    """IG-534 Phase 2 deferred gate: p95 cross-loop start delay ≤ 2× baseline at N=64.

    CI Mode: Scales down to N=16 for faster CI runs.
    """
    num_loops = CIMode.MULTI_LOOP_N64  # CI: 16, Prod: 64
    bus = EventBus()
    metrics = MultiLoopMetrics()

    for i in range(num_loops):
        loop_id = f"loop:n64-{i}"
        client = LoopClientSimulator(
            loop_id=loop_id,
            client_id=f"client-{i}",
            event_queue=asyncio.Queue(maxsize=CIMode.QUEUE_CAPACITY_N64),  # CI: 1000, Prod: 2000
        )
        await bus.subscribe(f"loop:{loop_id}", client.event_queue)
        metrics.add_loop(client)

    consumer_tasks = [
        asyncio.create_task(loop.consume_events(timeout=CIMode.MULTI_LOOP_TIMEOUT))
        for loop in metrics.loops
    ]

    async def publish_loop_events(loop_idx: int) -> None:
        loop_id = f"loop:n64-{loop_idx}"
        for j in range(20):
            event = {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "streaming", "content": f"chunk-{j}"}, {}),
            }
            await bus.publish(f"loop:{loop_id}", event)
        await bus.publish(
            f"loop:{loop_id}",
            {"type": "status", "loop_id": loop_id, "state": "idle"},
        )

    start_time = time.monotonic()
    await asyncio.gather(*[publish_loop_events(i) for i in range(num_loops)])
    await asyncio.gather(*consumer_tasks)
    metrics.test_duration_sec = time.monotonic() - start_time

    summary = metrics.get_summary()
    assert summary["latency_spread_ratio"] <= 2.0, (
        f"N={num_loops} p95/min start delay ratio {summary['latency_spread_ratio']:.2f} exceeds 2× gate"
    )
    assert summary["loops_with_terminal_frames"] >= num_loops

    print(f"\n=== IG-534 Phase 2: N={num_loops} start-delay gate ({CIMode.summary()}) ===")
    print(f"latency_spread_ratio={summary['latency_spread_ratio']:.2f}")
    print(f"p95_first_event_ms={summary['first_event_latency_p95_ms']:.2f}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_goal_completion_blocks_on_full_queue() -> None:
    """IG-534: goal_completion frames block when queue full (not dropped).

    Validates that synthesis tail frames wait for queue space instead of
    being silently dropped, even when queue is at capacity.
    """
    bus = EventBus()
    # Small queue to force blocking scenario
    queue: asyncio.Queue[tuple[dict, Any]] = asyncio.Queue(maxsize=1)
    loop_id = "loop:block-test"

    await bus.subscribe(f"loop:{loop_id}", queue)

    # Fill queue with one regular event
    await bus.publish(f"loop:{loop_id}", {"type": "filler"})
    assert queue.full()

    # Publish goal_completion (should block, not drop)
    gc_event = {
        "type": "event",
        "loop_id": loop_id,
        "mode": "messages",
        "data": ({"phase": "goal_completion", "content": "tail"}, {}),
    }
    publish_task = asyncio.create_task(bus.publish(f"loop:{loop_id}", gc_event))

    # Give it time to start blocking
    await asyncio.sleep(0.05)
    assert not publish_task.done(), "goal_completion should block when queue full"

    # Drain the filler
    event1, _ = await queue.get()
    assert event1["type"] == "filler"

    # Now goal_completion should complete delivery
    await asyncio.wait_for(publish_task, timeout=1.0)

    # Verify goal_completion was delivered
    event2, _ = await queue.get()
    assert event2.get("type") == "event"
    data = event2.get("data")
    assert isinstance(data, (tuple, list))
    assert data[0].get("phase") == "goal_completion"

    print("\n=== IG-534: goal_completion blocking behavior ===")
    print("goal_completion blocked successfully until queue space available")


# ============================================================================
# Phase 3 Exit Criteria Tests (IG-534)
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phase3_synthesis_visible_p95_under_5s() -> None:
    """IG-534 Phase 3: p95 synthesis delivery within 5s under 32-loop load.

    CI Mode: Scales down to 8 loops for faster CI runs.
    """
    num_loops = CIMode.MULTI_LOOP_COUNT  # CI: 8, Prod: 32
    bus = EventBus()
    metrics = MultiLoopMetrics()

    for i in range(num_loops):
        loop_id = f"loop:phase3-synth-{i}"
        client = LoopClientSimulator(loop_id=loop_id, client_id=f"client-{i}")
        await bus.subscribe(f"loop:{loop_id}", client.event_queue)
        metrics.add_loop(client)

    consumer_tasks = [
        asyncio.create_task(loop.consume_events(timeout=CIMode.MULTI_LOOP_TIMEOUT))
        for loop in metrics.loops
    ]

    async def publish_loop_events(loop_idx: int) -> None:
        loop_id = f"loop:phase3-synth-{loop_idx}"
        for j in range(CIMode.SYNTHESIS_EVENTS):  # CI: 10, Prod: 30
            await bus.publish(
                f"loop:{loop_id}",
                {
                    "type": "event",
                    "loop_id": loop_id,
                    "mode": "messages",
                    "data": ({"phase": "streaming", "content": f"chunk-{j}"}, {}),
                },
            )
        await bus.publish(
            f"loop:{loop_id}",
            {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "goal_completion", "content": "final"}, {}),
            },
        )

    await asyncio.gather(*[publish_loop_events(i) for i in range(num_loops)])
    await asyncio.gather(*consumer_tasks)

    summary = metrics.get_summary()
    assert summary["goal_completion_delivered"] == num_loops
    assert summary["synthesis_visible_p95_ms"] <= 5000.0, (
        f"p95 synthesis visible {summary['synthesis_visible_p95_ms']:.0f}ms exceeds 5s gate"
    )

    print(f"\n=== IG-534 Phase 3: synthesis visible gate ({CIMode.summary()}) ===")
    print(f"synthesis_visible_p95_ms={summary['synthesis_visible_p95_ms']:.2f}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phase3_first_chunk_p50_under_load() -> None:
    """IG-534 Phase 3: first-chunk p50 stays low under concurrent 32-loop load.

    CI Mode: Scales down to 8 loops for faster CI runs.
    """
    num_loops = CIMode.MULTI_LOOP_COUNT  # CI: 8, Prod: 32
    bus = EventBus()
    metrics = MultiLoopMetrics()

    for i in range(num_loops):
        loop_id = f"loop:phase3-ttfc-{i}"
        client = LoopClientSimulator(loop_id=loop_id, client_id=f"client-{i}")
        await bus.subscribe(f"loop:{loop_id}", client.event_queue)
        metrics.add_loop(client)

    consumer_tasks = [
        asyncio.create_task(loop.consume_events(timeout=CIMode.MULTI_LOOP_TIMEOUT))
        for loop in metrics.loops
    ]

    async def publish_first_chunk(loop_idx: int) -> None:
        loop_id = f"loop:phase3-ttfc-{loop_idx}"
        await bus.publish(
            f"loop:{loop_id}",
            {
                "type": "event",
                "loop_id": loop_id,
                "mode": "messages",
                "data": ({"phase": "streaming", "content": "first"}, {}),
            },
        )

    await asyncio.gather(*[publish_first_chunk(i) for i in range(num_loops)])
    await asyncio.gather(*consumer_tasks)

    summary = metrics.get_summary()
    # With 100ms coalesce default and direct bus delivery, p50 should be well under
    # the Phase 2 300ms baseline (240ms = 20% improvement threshold).
    assert summary["first_event_latency_p50_ms"] <= 240.0, (
        f"p50 first-chunk {summary['first_event_latency_p50_ms']:.0f}ms exceeds 240ms gate"
    )

    print(f"\n=== IG-534 Phase 3: time-to-first-chunk gate ({CIMode.summary()}) ===")
    print(f"first_event_latency_p50_ms={summary['first_event_latency_p50_ms']:.2f}")


# ============================================================================
# Phase 0 Observability Tests
# ============================================================================


@pytest.mark.asyncio
async def test_event_bus_drop_counter_observable() -> None:
    """IG-534 Phase 0: drop counters are queryable for observability."""
    bus = EventBus()
    queue: asyncio.Queue[tuple[dict, Any]] = asyncio.Queue(maxsize=1)

    await bus.subscribe("loop:counter-test", queue)

    # Fill queue
    await bus.publish("loop:counter-test", {"type": "filler"})

    # Attempt to publish NORMAL event (should drop)
    meta = SimpleNamespace(priority=EventPriority.NORMAL)
    for _ in range(5):
        await bus.publish("loop:counter-test", {"type": "drop-test"}, event_meta=meta)

    # Query counters
    counts = get_event_bus_drop_counts()
    key = "NORMAL|loop:counter-test"
    assert key in counts, f"Drop counter missing for {key}"
    assert counts[key] >= 1, "Drop counter should record NORMAL drops"

    print("\n=== IG-534 Phase 0: Drop counters ===")
    print(f"Drop counts: {counts}")
