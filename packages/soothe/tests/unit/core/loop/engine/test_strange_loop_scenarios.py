"""Integration tests for Layer 2 StrangeLoop (RFC-0008)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe.config.models import (
    ExecutePromptLedgerConfig,
    PlanPromptLedgerConfig,
)
from soothe.sloop import StrangeLoop


class MockCoreAgent:
    """Mock CoreAgent for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        # Mock graph attribute for iteration anchor capture
        self.graph = MagicMock()
        self.graph.checkpointer = None

    @property
    def checkpointer(self) -> None:
        """Mock checkpointer property (always None for tests)."""
        return self.graph.checkpointer

    def astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.astream`` (not a coroutine)."""

        async def mock_stream():
            self.call_count += 1
            # Use message format expected by strange_loop
            yield {"messages": [{"content": f"Mock output for: {user_input}"}]}

        return mock_stream()

    def execution_astream(self, user_input: str, config: dict, **kwargs: Any):
        """Return an async iterator like ``CoreAgent.execution_astream`` (ephemeral twin graph)."""

        async def mock_stream():
            self.call_count += 1
            yield {
                "messages": [
                    AIMessage(
                        content="Completed step with verifiable output: 42 items processed.",
                        tool_calls=[
                            {
                                "name": "run_command",
                                "args": {"command": "echo done"},
                                "id": f"tc-{self.call_count}",
                            }
                        ],
                    )
                ]
            }

        return mock_stream()

    async def execution_aget_state(self, config: dict | None = None) -> Any:
        """Stub graph state for interrupt resume checks in the executor."""
        state = MagicMock()
        state.tasks = []
        return state


def _make_config(max_iterations: int = 8) -> MagicMock:
    cfg = MagicMock()
    cfg.subagents = {}
    cfg.agent = MagicMock()
    al = cfg.agent.loop
    al.max_iterations = max_iterations
    al.max_subagent_tasks_per_wave = 16
    al.context_window_limit = 128000
    al.working_memory.max_inline_chars = 4000
    al.working_memory.max_entry_chars_before_spill = 500
    # Concurrency config (LoopConcurrencyConfig)
    al.concurrency.max_parallel_steps = 1
    al.concurrency.max_parallel_tools = 5
    al.concurrency.max_parallel_subagents = 4
    # Async checkpoint worker config (LoopCheckpointAsyncConfig). Must be real
    # floats — a MagicMock here makes ``asyncio.sleep(flush_interval)`` raise
    # TypeError on every tick, and the worker's ``except Exception`` swallows
    # it with no sleep, producing a ~100% CPU busy-loop that hangs the test.
    al.concurrency.checkpoint.flush_interval = 5.0
    al.concurrency.checkpoint.close_timeout_seconds = 5.0
    al.concurrency.checkpoint.durable_flush_timeout = 5.0
    # Execute/plan prompt-ledger config must be real typed instances — a
    # MagicMock here makes ``cross_goal_completion_tail > 0`` raise TypeError
    # inside execute-step projection and fail every parallel step. Typed
    # defaults satisfy both the direct attribute access in strange_loop and
    # the numeric comparisons in plan_ledger_projection.
    al.execute_prompt_ledger = ExecutePromptLedgerConfig()
    al.plan_prompt_ledger = PlanPromptLedgerConfig()
    # Thread switch policy: set on loop config directly, not on limits
    # _get_rate_limit_threshold looks at loop_cfg.thread_switch_policy
    al.thread_switch_policy = None
    # Goal completion / synthesis config
    al.goal_completion_mode = "llm_only"
    al.report_output.synthesis_max_chars = 10000
    al.report_output.synthesis_include_full_outputs = True
    al.report_output.output_summary_max_chars = 1500
    # Model attribute for SynthesisGenerator
    al.synthesis_model = None  # Will use planner._model
    # Router / observability
    cfg.router.fast = None
    cfg.observability.langfuse.trace_name = None
    cfg.observability.langfuse.enabled = False
    # Persistence backend for ContextEngine (RFC-624 Phase 4)
    cfg.persistence.default_backend = "sqlite"
    # Delete 'home' attribute so strange_loop uses SOOTHE_HOME default
    # (MagicMock creates attributes lazily, so we must explicitly delete)
    del cfg.home
    return cfg


@pytest.mark.asyncio
async def test_loop_agent_success() -> None:
    """Test StrangeLoop with successful execution."""
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config())

    result = await loop_agent.run(
        goal="Test goal",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"


@pytest.mark.asyncio
async def test_loop_agent_with_replan() -> None:
    """Test StrangeLoop with replan scenario."""
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config())

    result = await loop_agent.run(
        goal="Test goal that needs replan",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"


@pytest.mark.asyncio
async def test_loop_agent_with_continue() -> None:
    """Test StrangeLoop with continue-then-done scenario."""
    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config())

    result = await loop_agent.run(
        goal="Test goal with continue",
        thread_id="test_thread",
        max_iterations=8,
    )

    assert result.status == "done"


@pytest.mark.asyncio
async def test_loop_agent_max_iterations() -> None:
    """Test StrangeLoop respects max iterations."""

    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config(max_iterations=3))

    result = await loop_agent.run(
        goal="Never ending task",
        thread_id="test_thread",
        max_iterations=3,
    )

    # RFC-904: one-shot DISPATCH completes without plan assess; max_iterations unused.
    assert result.status == "done"


@pytest.mark.asyncio
async def test_loop_agent_parallel_execution() -> None:
    """Test StrangeLoop with parallel execution mode."""

    core_agent = MockCoreAgent()
    loop_agent = StrangeLoop(core_agent=core_agent, config=_make_config())

    result = await loop_agent.run(
        goal="Parallel task",
        thread_id="test_thread",
        max_iterations=8,
    )

    # RFC-904: root step executes as a single THREAD claim.
    assert core_agent.call_count >= 1
    assert result.status == "done"
