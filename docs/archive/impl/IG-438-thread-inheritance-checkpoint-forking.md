# IG-438: Thread Inheritance with LangGraph Checkpoint Forking

**RFC**: RFC-223
**Status**: In Progress
**Created**: 2026-05-27
**Depends on**: RFC-201, RFC-214, RFC-216, RFC-218

---

## Goal

Implement checkpoint-based thread inheritance for step execution in AgentLoop, achieving:
1. Main thread ID alignment with loop_id
2. Efficient history inheritance via LangGraph `acopy_thread()` API
3. Hybrid fork strategy for DAG dependencies

---

## Files to Touch

| File | Action | Purpose |
|------|--------|---------|
| `packages/soothe/src/soothe/core/loop/engine/thread_fork_manager.py` | CREATE | ThreadForkManager component |
| `packages/soothe/src/soothe/core/loop/engine/__init__.py` | MODIFY | Export ThreadForkManager |
| `packages/soothe/src/soothe/core/loop/state/schemas.py` | MODIFY | Add step_thread_ids, thread_fork_sources |
| `packages/soothe/src/soothe/core/loop/engine/executor.py` | MODIFY | Call ThreadForkManager, add checkpointer param |
| `packages/soothe/src/soothe/core/loop/engine/agent_loop.py` | MODIFY | Pass checkpointer to Executor |
| `packages/soothe/tests/unit/core/loop/engine/test_thread_fork_manager.py` | CREATE | Unit tests for ThreadForkManager |

---

## Implementation Steps

### Step 1: Create ThreadForkManager (thread_fork_manager.py)

Create new file with:

```python
"""Thread checkpoint forking for step inheritance (RFC-223)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)


class ThreadForkManager:
    """Manages thread checkpoint forking for step inheritance.

    RFC-223: Singleton dependency steps fork from predecessor's checkpoint
    to inherit full conversation history. Multi-dependency steps fork from
    main thread and use message injection.

    Args:
        checkpointer: LangGraph checkpointer for acopy_thread calls.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None) -> None:
        self._checkpointer = checkpointer

    def select_fork_source(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
    ) -> str:
        """Select source thread_id for checkpoint fork.

        Uses DIRECT dependencies only (not transitive closure):
        - No deps → main thread (loop_id)
        - Single dep → predecessor's step thread
        - Multiple deps → main thread (fallback)

        Args:
            step: Current step to execute.
            decision: Current decision with dependency information.
            state: Loop state with step_thread_ids mapping.

        Returns:
            Source thread_id to fork from.
        """
        # Use direct dependencies only
        direct_deps = step.dependencies or []

        # No direct dependencies → first step, fork from main
        if not direct_deps:
            return state.thread_id

        # Multiple direct dependencies → fork from main, use message injection
        if len(direct_deps) > 1:
            return state.thread_id

        # Singleton direct dependency → fork from predecessor's thread
        pred_step_id = direct_deps[0]
        pred_thread_id = state.step_thread_ids.get(pred_step_id)

        # Predecessor thread not tracked → fallback to main
        if not pred_thread_id:
            return state.thread_id

        return pred_thread_id

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
    ) -> str:
        """Execute checkpoint fork from source to target thread.

        Args:
            source_thread_id: Thread to copy checkpoint from.
            target_thread_id: Thread to copy checkpoint to.

        Returns:
            target_thread_id if successful, source_thread_id as fallback.
        """
        if not self._checkpointer:
            logger.debug("No checkpointer, skipping fork")
            return source_thread_id

        try:
            await self._checkpointer.acopy_thread(source_thread_id, target_thread_id)
            logger.info(
                "Checkpoint forked: %s → %s",
                source_thread_id,
                target_thread_id,
            )
            return target_thread_id
        except Exception:
            logger.warning(
                "Checkpoint fork failed: %s → %s, proceeding without inheritance",
                source_thread_id,
                target_thread_id,
                exc_info=True,
            )
            return source_thread_id

    async def prepare_thread_for_step(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
        main_thread_id: str,
    ) -> str:
        """Prepare thread for step execution (full preparation flow).

        Args:
            step: Step to execute.
            decision: Decision with dependency info.
            state: Loop state to update with mappings.
            main_thread_id: The loop's main thread_id (loop_id).

        Returns:
            Thread_id to use for CoreAgent stream.
        """
        # Determine source for fork
        source_thread_id = self.select_fork_source(step, decision, state)

        # Build target thread_id with __step_ prefix
        target_thread_id = f"{main_thread_id}__step_{step.id}"

        # Execute fork
        actual_thread_id = await self.fork_checkpoint(source_thread_id, target_thread_id)

        # Update state mappings
        state.step_thread_ids[step.id] = actual_thread_id
        state.thread_fork_sources[actual_thread_id] = source_thread_id

        return actual_thread_id
```

### Step 2: Update LoopState (schemas.py)

Add fork tracking fields to LoopState:

```python
# In LoopState class, add:

# RFC-223: Thread fork tracking
step_thread_ids: dict[str, str] = Field(
    default_factory=dict,
    description="Maps step_id → thread_id used for execution",
)
thread_fork_sources: dict[str, str] = Field(
    default_factory=dict,
    description="Maps thread_id → source thread_id for fork lineage",
)
```

### Step 3: Modify Executor (executor.py)

3a. Add checkpointer parameter to constructor:

```python
def __init__(
    self,
    core_agent: CoreAgent,
    *,
    checkpointer: BaseCheckpointSaver | None = None,  # NEW
    max_parallel_steps: int = 16,
    config: SootheConfig | None = None,
    goal_context_manager: GoalContextManager | None = None,
    loop_id: str | None = None,
) -> None:
    self._checkpointer = checkpointer
    # ... rest unchanged
```

3b. In `_execute_step_collecting_events()`, add ThreadForkManager call:

```python
# Import at top
from soothe.core.loop.engine.thread_fork_manager import ThreadForkManager

# In _execute_step_collecting_events, after start = time.perf_counter():

# RFC-223: Prepare fork thread
fork_manager = ThreadForkManager(self._checkpointer)
stream_thread_id = await fork_manager.prepare_thread_for_step(
    step=step,
    decision=loop_state.current_decision,
    state=loop_state,
    main_thread_id=thread_id,
)

# Determine if multi-dep (needs message injection)
direct_deps = step.dependencies or []
needs_message_injection = len(direct_deps) > 1

# ... existing code for graph_input_messages ...

# Multi-dep: inject predecessor messages (transitive)
if needs_message_injection and loop_state.current_decision:
    transitive_preds = transitive_dependency_step_ids(step, loop_state.current_decision)
    if transitive_preds:
        cap = self._branch_predecessor_message_cap()
        graph_input_messages = predecessor_execute_messages_for_branch(
            loop_state.loop_messages,
            transitive_preds,
            max_messages=cap,
        )

# Use forked thread_id in config (replace existing stream_thread_id logic)
cfg_thread = stream_thread_id  # Already forked, not branch pattern
```

### Step 4: Update AgentLoop (agent_loop.py)

Pass checkpointer to Executor when creating it:

```python
# Find Executor instantiation, add checkpointer param
self._executor = Executor(
    self.core_agent,
    checkpointer=self._checkpointer,  # NEW
    max_parallel_steps=...,
    config=...,
)
```

### Step 5: Export ThreadForkManager (__init__.py)

```python
from .thread_fork_manager import ThreadForkManager

__all__ = [
    # ... existing exports
    "ThreadForkManager",
]
```

### Step 6: Create Unit Tests

File: `packages/soothe/tests/unit/core/loop/engine/test_thread_fork_manager.py`

```python
"""Unit tests for ThreadForkManager (RFC-223)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from soothe.core.loop.engine.thread_fork_manager import ThreadForkManager
from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction


class TestSelectForkSource:
    """Tests for select_fork_source method."""

    def test_no_deps_returns_main_thread(self):
        """First step (no deps) forks from main thread."""
        manager = ThreadForkManager(None)
        step = StepAction(id="A", dependencies=[])
        decision = AgentDecision(steps=[step])
        state = LoopState(thread_id="loop1")

        source = manager.select_fork_source(step, decision, state)
        assert source == "loop1"

    def test_singleton_dep_returns_predecessor_thread(self):
        """Single direct dep forks from predecessor's thread."""
        manager = ThreadForkManager(None)
        step_b = StepAction(id="B", dependencies=["A"])
        step_a = StepAction(id="A", dependencies=[])
        decision = AgentDecision(steps=[step_a, step_b])
        state = LoopState(
            thread_id="loop1",
            step_thread_ids={"A": "loop1__step_A"},
        )

        source = manager.select_fork_source(step_b, decision, state)
        assert source == "loop1__step_A"

    def test_chain_singleton_inherits_from_immediate_predecessor(self):
        """Chain A→B→C: C forks from B (direct dep), not A."""
        manager = ThreadForkManager(None)
        step_a = StepAction(id="A", dependencies=[])
        step_b = StepAction(id="B", dependencies=["A"])
        step_c = StepAction(id="C", dependencies=["B"])  # Direct dep on B
        decision = AgentDecision(steps=[step_a, step_b, step_c])
        state = LoopState(
            thread_id="loop1",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source = manager.select_fork_source(step_c, decision, state)
        assert source == "loop1__step_B"

    def test_multi_dep_returns_main_thread(self):
        """Multiple direct deps fallback to main thread."""
        manager = ThreadForkManager(None)
        step_c = StepAction(id="C", dependencies=["A", "B"])
        decision = AgentDecision(steps=[
            StepAction(id="A", dependencies=[]),
            StepAction(id="B", dependencies=[]),
            step_c,
        ])
        state = LoopState(
            thread_id="loop1",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source = manager.select_fork_source(step_c, decision, state)
        assert source == "loop1"

    def test_missing_predecessor_thread_fallback_to_main(self):
        """If predecessor thread_id not tracked, fallback to main."""
        manager = ThreadForkManager(None)
        step_b = StepAction(id="B", dependencies=["A"])
        decision = AgentDecision(steps=[
            StepAction(id="A", dependencies=[]),
            step_b,
        ])
        state = LoopState(thread_id="loop1")  # No step_thread_ids

        source = manager.select_fork_source(step_b, decision, state)
        assert source == "loop1"


class TestForkCheckpoint:
    """Tests for fork_checkpoint method."""

    @pytest.mark.asyncio
    async def test_calls_acopy_thread(self):
        """Verify checkpointer.acopy_thread is called."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)

        result = await manager.fork_checkpoint("source1", "target1")

        mock_checkpointer.acopy_thread.assert_called_once_with("source1", "target1")
        assert result == "target1"

    @pytest.mark.asyncio
    async def test_failure_returns_source(self):
        """On failure, return source as fallback."""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.acopy_thread = AsyncMock(side_effect=Exception("DB error"))
        manager = ThreadForkManager(mock_checkpointer)

        result = await manager.fork_checkpoint("source1", "target1")

        assert result == "source1"

    @pytest.mark.asyncio
    async def test_no_checkpointer_returns_source(self):
        """No checkpointer → skip fork, return source."""
        manager = ThreadForkManager(None)

        result = await manager.fork_checkpoint("source1", "target1")

        assert result == "source1"


class TestPrepareThreadForStep:
    """Tests for prepare_thread_for_step method."""

    @pytest.mark.asyncio
    async def test_updates_state_mappings(self):
        """Verify state mappings are updated."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)
        step = StepAction(id="A", dependencies=[])
        decision = AgentDecision(steps=[step])
        state = LoopState(thread_id="loop1")

        result = await manager.prepare_thread_for_step(
            step, decision, state, "loop1"
        )

        assert result == "loop1__step_A"
        assert state.step_thread_ids["A"] == "loop1__step_A"
        assert state.thread_fork_sources["loop1__step_A"] == "loop1"

    @pytest.mark.asyncio
    async def test_singleton_step_tracks_lineage(self):
        """Singleton dep step tracks fork lineage."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)
        step_b = StepAction(id="B", dependencies=["A"])
        decision = AgentDecision(steps=[
            StepAction(id="A", dependencies=[]),
            step_b,
        ])
        state = LoopState(
            thread_id="loop1",
            step_thread_ids={"A": "loop1__step_A"},
        )

        result = await manager.prepare_thread_for_step(
            step_b, decision, state, "loop1"
        )

        assert result == "loop1__step_B"
        assert state.thread_fork_sources["loop1__step_B"] == "loop1__step_A"
```

---

## Verification Checklist

After implementation:
- [ ] ThreadForkManager created with select_fork_source, fork_checkpoint, prepare_thread_for_step
- [ ] LoopState has step_thread_ids and thread_fork_sources fields
- [ ] Executor accepts checkpointer parameter
- [ ] Executor calls ThreadForkManager.prepare_thread_for_step
- [ ] Thread naming uses `__step_` prefix (not `__p`)
- [ ] Multi-dep steps still use predecessor_execute_messages_for_branch
- [ ] Unit tests pass
- [ ] Run `./scripts/verify_finally.sh`

---

## Notes

- Fork threads are kept after goal completion (no cleanup in initial impl)
- Thread naming change is internal; existing tests should verify behavior not IDs
- Solo mode unaffected (ThreadForkManager only active in AgentLoop)