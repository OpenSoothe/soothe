# IG-134: Layer 2 Unified State Model and Independent Checkpoint

**Implementation Guide**: 0134
**Title**: Layer 2 Unified State Model and Independent Checkpoint
**RFC**: RFC-205
**Status**: Completed
**Created**: 2026-04-08
**Dependencies**: RFC-201, RFC-203, RFC-100
**Updated**: 2026-04-12 (terminology refactoring per IG-153)

---

## Overview

Implement Layer 2's independent checkpoint system that stores step-level semantic traces (input/output) instead of Layer 1's message-level execution history.

### Key Changes

1. Create `Layer2Checkpoint` model with unified state
2. Implement `Layer2StateManager` for persistence and recovery
3. Refactor `AgentLoop` to use independent checkpoint
4. Update Plan to derive prior conversation from step outputs
5. Integrate working memory state serialization

---

## Module Organization

```
src/soothe/cognition/agent_loop/
├── checkpoint.py              # NEW: Layer2Checkpoint model
├── state_manager.py           # NEW: Layer2StateManager
├── loop_agent.py              # REFACTOR: Use state manager
├── executor.py                # UPDATE: Record step I/O
├── reason.py                  # UPDATE: Derive from step outputs
└── schemas.py                 # EXISTING: LoopState, etc.
```

---

## Step 1: Create Checkpoint Models

### File: `src/soothe/cognition/agent_loop/checkpoint.py`

Create models for Layer 2 checkpoint state:

```python
"""Layer 2 Checkpoint Models (RFC-205).

Defines step-level semantic traces for agentic goal execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """Tool invocation summary."""

    tool_name: str
    success: bool
    output_preview: str = Field(description="Truncated output (max 200 chars)")


class SubagentCallRecord(BaseModel):
    """Subagent delegation summary."""

    subagent_name: str
    task_input: str
    output_length: int
    success: bool


class StepExecutionRecord(BaseModel):
    """Single step execution with I/O."""

    step_id: str
    description: str

    # Input
    step_input: str = Field(description="Task text sent to execution")

    # Output
    success: bool
    output: str = Field(description="Final result")
    error: str | None = None

    # Tool/subagent metadata
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    subagent_calls: list[SubagentCallRecord] = Field(default_factory=list)


class ExecuteWaveRecord(BaseModel):
    """One Execute wave execution."""

    iteration: int
    timestamp: datetime

    # Steps executed
    steps: list[StepExecutionRecord] = Field(default_factory=list)

    # Metadata
    execution_mode: Literal["parallel", "sequential", "dependency"]
    duration_ms: int

    # Metrics
    tool_call_count: int = 0
    subagent_task_count: int = 0
    hit_subagent_cap: bool = False
    error_count: int = 0


class PlanStepRecord(BaseModel):
    """One Plan phase execution."""

    iteration: int
    timestamp: datetime

    # Input
    goal_text: str
    prior_step_outputs: list[str] = Field(
        default_factory=list,
        description="Derived from previous Execute wave outputs"
    )

    # Reasoning
    reasoning: str
    status: Literal["done", "continue", "replan"]
    goal_progress: float

    # Decision
    decision: dict | None = Field(description="AgentDecision serialized")

    # Output
    user_summary: str
    next_action: str


class WorkingMemoryEntry(BaseModel):
    """One working memory entry."""

    step_id: str
    description: str
    success: bool
    inline_summary: str
    spill_relpath: str | None = None


class WorkingMemoryState(BaseModel):
    """Working memory snapshot."""

    entries: list[WorkingMemoryEntry] = Field(default_factory=list)
    spill_files: list[str] = Field(
        default_factory=list,
        description="Relative paths to spill files"
    )


class Layer2Checkpoint(BaseModel):
    """Complete Layer 2 state for a goal execution."""

    # Identity
    thread_id: str
    goal: str
    created_at: datetime
    updated_at: datetime

    # Execution state
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["running", "completed", "failed", "cancelled"] = "running"

    # Plan history (step I/O, not messages)
    plan_history: list[PlanStepRecord] = Field(default_factory=list)

    # Execute history
    execute_history: list[ExecuteWaveRecord] = Field(default_factory=list)

    # Working memory state
    working_memory_state: WorkingMemoryState = Field(
        default_factory=WorkingMemoryState
    )

    # Metrics
    total_duration_ms: int = 0
    total_tokens_used: int = 0

    schema_version: str = "1.0"
```

---

## Step 2: Implement State Manager

### File: `src/soothe/cognition/agent_loop/state_manager.py`

Create persistence layer for Layer 2 checkpoint:

```python
"""Layer 2 State Manager (RFC-205).

Manages checkpoint lifecycle: initialize, save, load, recovery.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.checkpoint import (
    ExecuteWaveRecord,
    Layer2Checkpoint,
    PlanStepRecord,
    WorkingMemoryState,
)
from soothe.config import SOOTHE_HOME

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.executor import ExecuteWaveResult
    from soothe.cognition.agent_loop.planning import PlanResult
    from soothe.cognition.agent_loop.working_memory import LoopWorkingMemory

logger = logging.getLogger(__name__)


class Layer2StateManager:
    """Manages Layer 2 checkpoint lifecycle."""

    def __init__(self, thread_id: str, workspace: Path | None = None):
        """Initialize with thread context.

        Args:
            thread_id: Thread identifier
            workspace: Optional workspace path (uses SOOTHE_HOME if None)
        """
        self.thread_id = thread_id
        self.workspace = workspace or Path(SOOTHE_HOME).expanduser()
        self.run_dir = self.workspace / "runs" / thread_id
        self.checkpoint_path = self.run_dir / "layer2_checkpoint.json"
        self._checkpoint: Layer2Checkpoint | None = None

    def initialize(self, goal: str, max_iterations: int = 10) -> Layer2Checkpoint:
        """Create new checkpoint for goal execution.

        Args:
            goal: Goal description
            max_iterations: Maximum loop iterations

        Returns:
            New Layer2Checkpoint instance
        """
        now = datetime.now(UTC)
        checkpoint = Layer2Checkpoint(
            thread_id=self.thread_id,
            goal=goal,
            created_at=now,
            updated_at=now,
            max_iterations=max_iterations,
        )
        self._checkpoint = checkpoint
        self.save(checkpoint)
        logger.info(
            "[Layer2] Initialized checkpoint for thread %s (goal: %s)",
            self.thread_id,
            goal[:50],
        )
        return checkpoint

    def load(self) -> Layer2Checkpoint | None:
        """Load existing checkpoint for recovery.

        Returns:
            Layer2Checkpoint if exists and valid, None otherwise
        """
        if not self.checkpoint_path.exists():
            return None

        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            checkpoint = Layer2Checkpoint.model_validate(data)
            self._checkpoint = checkpoint
            logger.info(
                "[Layer2] Loaded checkpoint for thread %s (iteration %d, status %s)",
                self.thread_id,
                checkpoint.iteration,
                checkpoint.status,
            )
            return checkpoint
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                "[Layer2] Failed to load checkpoint for thread %s: %s",
                self.thread_id,
                e,
            )
            return None

    def save(self, checkpoint: Layer2Checkpoint) -> None:
        """Persist checkpoint to disk atomically.

        Write to temp file, then rename to avoid partial writes.

        Args:
            checkpoint: Checkpoint to save
        """
        checkpoint.updated_at = datetime.now(UTC)

        # Ensure run directory exists
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Write atomically: temp → rename
        data = checkpoint.model_dump(mode="json")
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=self.run_dir,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        # Atomic rename
        tmp_path.replace(self.checkpoint_path)
        self._checkpoint = checkpoint

        logger.debug(
            "[Layer2] Saved checkpoint for thread %s (iteration %d)",
            self.thread_id,
            checkpoint.iteration,
        )

    def record_iteration(
        self,
        plan_result: PlanResult,
        execute_wave: ExecuteWaveResult,
        working_memory: LoopWorkingMemory,
    ) -> None:
        """Update checkpoint after each iteration.

        Args:
            plan_result: Plan phase result
            execute_wave: Execute wave execution result
            working_memory: Current working memory state
        """
        if self._checkpoint is None:
            logger.error("[Layer2] No checkpoint to update")
            return

        # Record Plan step
        plan_record = PlanStepRecord(
            iteration=self._checkpoint.iteration,
            timestamp=datetime.now(UTC),
            goal_text=plan_result.goal_text,
            prior_step_outputs=self._derive_prior_step_outputs(),
            reasoning=plan_result.reasoning,
            status=plan_result.status,
            goal_progress=plan_result.goal_progress,
            decision=plan_result.decision.model_dump() if plan_result.decision else None,
            user_summary=plan_result.user_summary,
            next_action=plan_result.next_action,
        )
        self._checkpoint.plan_history.append(plan_record)

        # Record Execute wave
        execute_record = self._build_execute_wave_record(execute_wave)
        self._checkpoint.execute_history.append(execute_record)

        # Record working memory state
        self._checkpoint.working_memory_state = self._serialize_working_memory(
            working_memory
        )

        # Update metrics
        self._checkpoint.iteration += 1
        self._checkpoint.total_duration_ms += execute_wave.duration_ms
        self._checkpoint.total_tokens_used += execute_wave.total_tokens_used

        # Save checkpoint
        self.save(self._checkpoint)

    def derive_plan_conversation(self, limit: int = 10) -> list[str]:
        """Derive prior conversation from step outputs.

        Args:
            limit: Maximum step outputs to include

        Returns:
            List of XML-formatted assistant turns
        """
        if self._checkpoint is None:
            return []

        conversation = []
        for execute_wave in self._checkpoint.execute_history:
            for step in execute_wave.steps:
                if step.success and step.output:
                    # Format as assistant turn
                    conversation.append(f"<assistant>\n{step.output}\n</assistant>")

        return conversation[-limit:]

    def finalize(self, status: str) -> None:
        """Mark checkpoint as completed/failed.

        Args:
            status: Final status (completed, failed, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        self.save(self._checkpoint)
        logger.info(
            "[Layer2] Finalized checkpoint for thread %s (status: %s)",
            self.thread_id,
            status,
        )

    def _derive_prior_step_outputs(self) -> list[str]:
        """Get prior step outputs from previous Execute waves."""
        if not self._checkpoint or not self._checkpoint.execute_history:
            return []

        outputs = []
        for execute_wave in self._checkpoint.execute_history:
            for step in execute_wave.steps:
                if step.success and step.output:
                    outputs.append(step.output)

        return outputs

    def _build_execute_wave_record(self, execute_wave: ExecuteWaveResult) -> ExecuteWaveRecord:
        """Convert ExecuteWaveResult to ExecuteWaveRecord."""
        from soothe.cognition.agent_loop.checkpoint import (
            StepExecutionRecord,
            ToolCallRecord,
            SubagentCallRecord,
        )

        steps = []
        for step_result in act_wave.step_results:
            # Truncate output preview to 200 chars
            output_preview = step_result.output[:200] if step_result.output else ""

            step_record = StepExecutionRecord(
                step_id=step_result.step_id,
                description=step_result.description,
                step_input=step_result.step_input,
                success=step_result.success,
                output=step_result.output,
                error=step_result.error,
                tool_calls=[
                    ToolCallRecord(
                        tool_name=tc.tool_name,
                        success=tc.success,
                        output_preview=tc.output[:200] if tc.output else "",
                    )
                    for tc in step_result.tool_calls
                ],
                subagent_calls=[
                    SubagentCallRecord(
                        subagent_name=sc.subagent_name,
                        task_input=sc.task_input,
                        output_length=len(sc.output) if sc.output else 0,
                        success=sc.success,
                    )
                    for sc in step_result.subagent_calls
                ],
            )
            steps.append(step_record)

        return ExecuteWaveRecord(
            iteration=self._checkpoint.iteration if self._checkpoint else 0,
            timestamp=datetime.now(UTC),
            steps=steps,
            execution_mode=execute_wave.execution_mode,
            duration_ms=execute_wave.duration_ms,
            tool_call_count=execute_wave.tool_call_count,
            subagent_task_count=execute_wave.subagent_task_count,
            hit_subagent_cap=execute_wave.hit_subagent_cap,
            error_count=execute_wave.error_count,
        )

    def _serialize_working_memory(
        self, working_memory: LoopWorkingMemory
    ) -> WorkingMemoryState:
        """Serialize working memory state to checkpoint."""
        from soothe.cognition.agent_loop.checkpoint import WorkingMemoryEntry

        entries = []
        spill_files = []

        for entry in working_memory.entries:
            wm_entry = WorkingMemoryEntry(
                step_id=entry.step_id,
                description=entry.description,
                success=entry.success,
                inline_summary=entry.inline_summary,
                spill_relpath=entry.spill_relpath,
            )
            entries.append(wm_entry)

            if entry.spill_relpath:
                spill_files.append(entry.spill_relpath)

        return WorkingMemoryState(
            entries=entries,
            spill_files=spill_files,
        )
```

---

## Step 3: Refactor AgentLoop Integration

### Update: `src/soothe/cognition/agent_loop/loop_agent.py`

Inject state manager into AgentLoop execution flow:

```python
# Add import
from soothe.cognition.agent_loop.state_manager import Layer2StateManager

# In run_with_progress():
async def run_with_progress(...):
    # Initialize state manager
    state_manager = Layer2StateManager(thread_id, workspace)

    # Try to recover from checkpoint
    checkpoint = state_manager.load()
    if checkpoint and checkpoint.status == "running":
        logger.info(
            "[AgentLoop] Recovering Layer 2 from checkpoint at iteration %d",
            checkpoint.iteration
        )
        state = self._restore_state_from_checkpoint(checkpoint)
    else:
        checkpoint = state_manager.initialize(goal, max_iterations)
        state = self._create_initial_state(goal, thread_id, ...)

    # Main loop
    while state.iteration < state.max_iterations:
        # Plan phase
        plan_result = await self.planning_phase.plan(...)

        if plan_result.is_done():
            state_manager.finalize(status="completed")
            yield "completed", {...}
            return

        # Execute phase
        execute_wave = await self._execute_wave(decision, state)

        # Record iteration to checkpoint
        state_manager.record_iteration(
            plan_result,
            execute_wave,
            state.working_memory
        )

        state.iteration += 1
```

---

## Step 4: Update Executor for Step I/O

### Update: `src/soothe/cognition/agent_loop/executor.py`

Ensure executor records step_input and step_output:

```python
# In ActWaveResult and StepResult models:
class StepResult(BaseModel):
    """Add step_input field"""
    step_id: str
    description: str
    step_input: str  # NEW: Task text sent to execution
    success: bool
    output: str
    error: str | None
    tool_calls: list[ToolCallResult]
    subagent_calls: list[SubagentCallResult]

# In execute_step():
async def _execute_step(...):
    # Capture step_input (the task text)
    step_input = step.description  # or custom input text

    # Execute and capture output
    result = await self._run_with_tools(...)

    return StepResult(
        step_id=step.id,
        description=step.description,
        step_input=step_input,  # NEW
        success=result.success,
        output=result.output,
        error=result.error,
        tool_calls=result.tool_calls,
        subagent_calls=result.subagent_calls,
    )
```

---

## Step 5: Update Reason Context Derivation

### Update: `src/soothe/cognition/agent_loop/planning.py`

Replace Layer 1 message loading with step I/O derivation:

```python
# In plan():
async def plan(...):
    # Get prior conversation from state manager (not Layer 1 messages)
    if state_manager:
        prior_step_outputs = state_manager.derive_plan_conversation(limit=10)
    else:
        prior_step_outputs = []

    # Pass to prompt builder
    context = PlanContext(
        goal=goal,
        recent_messages=prior_step_outputs,  # Step outputs, not messages
        ...
    )
```

---

## Step 6: Update Runner Integration

### Update: `src/soothe/cognition/agent_loop/loop_agent.py`

Pass state_manager to Plan phase:

```python
# In run_with_progress():
plan_result = await self.planning_phase.plan(
    goal=goal,
    state=state,
    state_manager=state_manager,  # NEW: Pass state manager
    context=self._build_plan_context(state),
)
```

---

## Verification

After implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- All tests pass
- Layer 2 checkpoint file created at `runs/{thread_id}/layer2_checkpoint.json`
- Reason derives prior context from step outputs
- Recovery works without Layer 1 dependency

---

## Test Files to Create

1. `tests/unit/test_layer2_checkpoint_model.py` - Validate checkpoint models
2. `tests/unit/test_layer2_state_manager.py` - Test persistence lifecycle
3. `tests/unit/test_plan_step_io_derivation.py` - Test context derivation
4. `tests/integration/test_layer2_recovery.py` - Test crash recovery

---

## Implementation Notes

- **Checkpoint semantics**: Layer 2 stores step I/O, Layer 1 stores messages
- **Persistence timing**: Save after each iteration (Reason-Act cycle)
- **Atomic writes**: Use temp file + rename pattern
- **Reason context**: Derive from `act_history.step.outputs`, not messages
- **Recovery**: Load checkpoint, restore iteration count, working memory, reason_history

---

## Status

- **Draft**: Ready for implementation
- **Next**: Create checkpoint.py and state_manager.py