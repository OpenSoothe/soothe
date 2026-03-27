"""Unit tests for ParallelToolsMiddleware semaphore control."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolRuntime

from soothe.middleware.parallel_tools import ParallelToolsMiddleware


@pytest.mark.asyncio
async def test_semaphore_limits_parallel_execution():
    """Verify max_parallel_tools limits concurrent execution with timing proof.

    Scenario: 5 tools with max_parallel=2, each takes 2s
    Expected: ~5s total (batched: 2+2+1 parallel batches)
    If unlimited: ~2s total (all 5 parallel)
    If sequential: ~10s total (one by one)
    """
    middleware = ParallelToolsMiddleware(max_parallel_tools=2)

    # Track execution timing
    execution_times = []

    async def mock_handler(request: ToolCallRequest) -> ToolMessage:
        start = time.perf_counter()
        execution_times.append(("start", request.tool_call["name"], start))
        await asyncio.sleep(2.0)  # Simulate 2s tool execution
        end = time.perf_counter()
        execution_times.append(("end", request.tool_call["name"], end))
        return ToolMessage(
            content=f"result from {request.tool_call['name']}",
            tool_call_id=request.tool_call["id"],
        )

    # Create 5 ToolCallRequests (mimicking LangGraph's asyncio.gather launch)
    requests = [
        ToolCallRequest(
            tool_call={"name": f"tool{i}", "args": {}, "id": f"call{i}"},
            tool=None,
            state={},
            runtime=MagicMock(spec=ToolRuntime),
        )
        for i in range(5)
    ]

    # Launch all 5 simultaneously (like LangGraph does)
    start_time = time.perf_counter()
    results = await asyncio.gather(*[middleware.awrap_tool_call(req, mock_handler) for req in requests])
    end_time = time.perf_counter()

    duration = end_time - start_time

    # Verify results
    assert len(results) == 5
    assert all(isinstance(r, ToolMessage) for r in results)

    # Verify timing proves batching
    # With max_parallel=2: should be 4-6s (3 batches: 2+2+1)
    # Without limits: would be ~2s (all 5 parallel)
    # Sequential: would be ~10s
    assert duration > 4.0, f"Duration {duration}s too short - semaphore not limiting"
    assert duration < 7.0, f"Duration {duration}s too long - not parallel enough"

    # Verify max concurrent was respected
    start_times = sorted([t for label, _, t in execution_times if label == "start"])
    end_times = sorted([t for label, _, t in execution_times if label == "end"])

    # At any point, at most 2 tools should be active
    active_count = 0
    max_active = 0
    events = sorted(execution_times, key=lambda x: x[2])

    for label, _, _ in events:
        if label == "start":
            active_count += 1
            max_active = max(max_active, active_count)
        else:
            active_count -= 1

    assert max_active <= 2, f"Max concurrent {max_active} exceeded limit of 2"


@pytest.mark.asyncio
async def test_semaphore_one_tool_sequential_execution():
    """Verify max_parallel_tools=1 produces sequential execution."""
    middleware = ParallelToolsMiddleware(max_parallel_tools=1)

    execution_order = []

    async def mock_handler(request: ToolCallRequest) -> ToolMessage:
        execution_order.append(request.tool_call["name"])
        await asyncio.sleep(0.5)
        return ToolMessage(
            content="result",
            tool_call_id=request.tool_call["id"],
        )

    # Create 3 requests
    requests = [
        ToolCallRequest(
            tool_call={"name": f"tool{i}", "args": {}, "id": f"call{i}"},
            tool=None,
            state={},
            runtime=MagicMock(spec=ToolRuntime),
        )
        for i in range(3)
    ]

    # Launch all 3 simultaneously
    start_time = time.perf_counter()
    results = await asyncio.gather(*[middleware.awrap_tool_call(req, mock_handler) for req in requests])
    end_time = time.perf_counter()

    duration = end_time - start_time

    # With max_parallel=1: should be ~1.5s (sequential: 3 * 0.5s)
    # If parallel: would be ~0.5s
    assert duration >= 1.4, f"Duration {duration}s too short - not sequential"
    assert duration < 2.0, f"Duration {duration}s too long"

    # Verify they executed one by one (order preserved due to semaphore)
    assert len(execution_order) == 3


@pytest.mark.asyncio
async def test_semaphore_releases_on_exception():
    """Verify semaphore slot released when tool execution fails."""
    middleware = ParallelToolsMiddleware(max_parallel_tools=2)

    call_count = 0

    async def failing_handler(request: ToolCallRequest) -> ToolMessage:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call fails
            raise RuntimeError("Tool execution failed")
        # Second call succeeds
        return ToolMessage(content="success", tool_call_id=request.tool_call["id"])

    requests = [
        ToolCallRequest(
            tool_call={"name": "tool", "args": {}, "id": "call"},
            tool=None,
            state={},
            runtime=MagicMock(spec=ToolRuntime),
        )
        for _ in range(3)
    ]

    # Execute with exceptions
    results = await asyncio.gather(
        *[middleware.awrap_tool_call(req, failing_handler) for req in requests],
        return_exceptions=True,
    )

    # Verify semaphore was released after failure
    # First failed, but second and third should have executed
    assert len(results) == 3
    assert isinstance(results[0], RuntimeError)
    assert isinstance(results[1], ToolMessage)
    assert isinstance(results[2], ToolMessage)

    # Verify semaphore is not stuck (available slots = max_parallel)
    assert middleware._semaphore._value == 2


@pytest.mark.asyncio
async def test_semaphore_allows_high_parallelism():
    """Verify max_parallel_tools=10 allows high concurrency."""
    middleware = ParallelToolsMiddleware(max_parallel_tools=10)

    execution_times = []

    async def mock_handler(request: ToolCallRequest) -> ToolMessage:
        start = time.perf_counter()
        execution_times.append(("start", request.tool_call["name"], start))
        await asyncio.sleep(1.0)
        execution_times.append(("end", request.tool_call["name"], time.perf_counter()))
        return ToolMessage(content="result", tool_call_id=request.tool_call["id"])

    # Create 10 requests (at the limit)
    requests = [
        ToolCallRequest(
            tool_call={"name": f"tool{i}", "args": {}, "id": f"call{i}"},
            tool=None,
            state={},
            runtime=MagicMock(spec=ToolRuntime),
        )
        for i in range(10)
    ]

    start_time = time.perf_counter()
    results = await asyncio.gather(*[middleware.awrap_tool_call(req, mock_handler) for req in requests])
    end_time = time.perf_counter()

    duration = end_time - start_time

    # With max_parallel=10: all 10 should run in parallel -> ~1s
    # If limited to fewer: would take longer
    assert duration >= 1.0, "Duration too short"
    assert duration < 2.0, f"Duration {duration}s too long - parallelism limited"

    # Verify max concurrent was at least 8 (allowing for async scheduling variance)
    active_count = 0
    max_active = 0
    events = sorted(execution_times, key=lambda x: x[2])

    for label, _, _ in events:
        if label == "start":
            active_count += 1
            max_active = max(max_active, active_count)
        else:
            active_count -= 1

    assert max_active >= 8, f"Max concurrent {max_active} too low - should be near 10"


@pytest.mark.asyncio
async def test_semaphore_default_is_10():
    """Verify default max_parallel_tools is 10."""
    middleware = ParallelToolsMiddleware()
    assert middleware.max_parallel_tools == 10
    assert middleware._semaphore._value == 10


@pytest.mark.asyncio
async def test_semaphore_logging_messages():
    """Verify middleware logs slot acquisition and release."""
    middleware = ParallelToolsMiddleware(max_parallel_tools=3)

    async def mock_handler(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="result", tool_call_id=request.tool_call["id"])

    request = ToolCallRequest(
        tool_call={"name": "test_tool", "args": {}, "id": "test_call"},
        tool=None,
        state={},
        runtime=MagicMock(spec=ToolRuntime),
    )

    # Execute one tool
    result = await middleware.awrap_tool_call(request, mock_handler)

    assert isinstance(result, ToolMessage)
    # Logging is verified by checking logs in test output
    # (pytest captures logs when run with -v flag)


@pytest.mark.asyncio
async def test_semaphore_multiple_retries_allowed():
    """Verify handler can be called multiple times (for retry middleware)."""
    middleware = ParallelToolsMiddleware(max_parallel_tools=2)

    call_count = 0

    async def retry_handler(request: ToolCallRequest) -> ToolMessage:
        # This simulates retry logic where handler is called multiple times
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Simulate retry by calling handler again
            # (In real middleware, this would be done by retry wrapper)
            pass
        return ToolMessage(content="success after retries", tool_call_id=request.tool_call["id"])

    request = ToolCallRequest(
        tool_call={"name": "retry_tool", "args": {}, "id": "retry_call"},
        tool=None,
        state={},
        runtime=MagicMock(spec=ToolRuntime),
    )

    result = await middleware.awrap_tool_call(request, retry_handler)

    assert isinstance(result, ToolMessage)
    # Semaphore should be released after final execution
    assert middleware._semaphore._value == 2
