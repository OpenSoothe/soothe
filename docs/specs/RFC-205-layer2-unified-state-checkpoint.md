# RFC-205: Layer 2 Unified State Model and Independent Checkpoint

**RFC**: 0205  
**Title**: Layer 2 Unified State Model and Independent Checkpoint  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-04-08  
**Dependencies**: RFC-201, RFC-203, RFC-100

## Abstract

This RFC defines an independent checkpoint system for Layer 2 (AgentLoop) that stores step-level semantic traces instead of Layer 1's message-level execution history. Layer 2 checkpoint captures "what was attempted and what resulted" at the agentic level, enabling architectural separation from Layer 1, improved recovery, and more efficient Reason context derivation.

## Motivation

### Current Problems

1. **Architectural coupling**: Layer 2 reads Layer 1's LangGraph checkpoint to derive prior conversation, creating dependency on CoreAgent's persistence layer
2. **Loss of semantic structure**: Step input/output is embedded in verbose message traces (HumanMessage, AIMessage, ToolMessage), not stored as first-class semantic data
3. **Recovery fragility**: Layer 2 state (decisions, working memory, Reason history) lost on crashes
4. **Token overhead**: Reason loads full message history (thousands of tokens) instead of semantic step traces (hundreds of tokens)
5. **Debugging opacity**: Message traces don't clearly show agentic decision flow

### Proposed Solution

Give Layer 2 its own checkpoint system that:

- Stores step I/O (input/output) with tool/subagent metadata
- Includes Reason decision history
- Integrates working memory state
- Persists per-iteration (Plan + Execute cycle)
- Enables independent recovery without Layer 1 dependency
- Derives Reason context from step outputs, not messages

---

## Architecture

### Layer 1 vs Layer 2 Checkpoint Semantics

| Aspect | Layer 1 (CoreAgent) | Layer 2 (AgentLoop) |
|--------|---------------------|---------------------|
| **Granularity** | Message-level | Step-level |
| **Data** | HumanMessage, AIMessage, ToolMessage | Step input/output, decisions |
| **Purpose** | Execution trace | Semantic goal trace |
| **Storage** | LangGraph checkpointer (SQLite/PostgreSQL) | JSON files in `runs/{thread_id}/` |
| **Consumer** | CoreAgent runtime | Plan phase, recovery |

**Key insight**: Layer 2 checkpoint captures agentic decisions and their outcomes, not the low-level tool invocations.

---

## Data Model

### Layer2Checkpoint

```python
class Layer2Checkpoint(BaseModel):
    """Complete Layer 2 state for a goal execution."""

    # Identity
    thread_id: str
    goal: str
    created_at: datetime
    updated_at: datetime

    # Execution state
    iteration: int
    max_iterations: int
    status: Literal["running", "completed", "failed", "cancelled"]

    # Reason history (step I/O, not messages)
    reason_history: list[ReasonStepRecord]

    # Act history
    act_history: list[ActWaveRecord]

    # Working memory state
    working_memory_state: WorkingMemoryState

    # Metrics
    total_duration_ms: int
    total_tokens_used: int
```

### ReasonStepRecord

```python
class ReasonStepRecord(BaseModel):
    """One Plan phase execution."""

    iteration: int
    timestamp: datetime

    # Input
    goal_text: str
    prior_step_outputs: list[str]  # Derived from previous Act wave outputs

    # Reasoning
    reasoning: str
    status: Literal["done", "continue", "replan"]
    goal_progress: float

    # Decision
    decision: AgentDecision | None

    # Output
    user_summary: str
    soothe_next_action: str
```

### ActWaveRecord

```python
class ActWaveRecord(BaseModel):
    """One Act wave execution."""

    iteration: int
    timestamp: datetime

    # Steps executed
    steps: list[StepExecutionRecord]

    # Metadata
    execution_mode: Literal["parallel", "sequential", "dependency"]
    duration_ms: int

    # Metrics
    tool_call_count: int
    subagent_task_count: int
    hit_subagent_cap: bool
    error_count: int
```

### StepExecutionRecord

```python
class StepExecutionRecord(BaseModel):
    """Single step execution with I/O."""

    step_id: str
    description: str

    # Input
    step_input: str  # The actual task text sent to execution

    # Output
    success: bool
    output: str  # Final result (could be large)
    error: str | None

    # Tool/subagent metadata
    tool_calls: list[ToolCallRecord]
    subagent_calls: list[SubagentCallRecord]
```

### ToolCallRecord and SubagentCallRecord

```python
class ToolCallRecord(BaseModel):
    """Tool invocation summary."""

    tool_name: str
    success: bool
    output_preview: str  # Truncated for checkpoint (e.g., 200 chars)


class SubagentCallRecord(BaseModel):
    """Subagent delegation summary."""

    subagent_name: str
    task_input: str
    output_length: int
    success: bool
```

### WorkingMemoryState

```python
class WorkingMemoryState(BaseModel):
    """Working memory snapshot."""

    entries: list[WorkingMemoryEntry]
    spill_files: list[str]  # Relative paths to spill files


class WorkingMemoryEntry(BaseModel):
    """One working memory entry."""

    step_id: str
    description: str
    success: bool
    inline_summary: str
    spill_relpath: str | None
```

---

## Reason Context Derivation

### Problem

Reason needs prior conversation context, but Layer 2 no longer reads Layer 1 messages.

### Solution

Derive conversation from Act step outputs:

```python
def derive_prior_conversation(checkpoint: Layer2Checkpoint, limit: int = 10) -> list[str]:
    """Derive Reason conversation from step I/O traces.
    
    Args:
        checkpoint: Layer 2 checkpoint with act_history
        limit: Maximum step outputs to include
        
    Returns:
        List of XML-formatted assistant turns
    """
    conversation = []

    for act_wave in checkpoint.act_history:
        for step in act_wave.steps:
            if step.success and step.output:
                # Format as assistant turn
                conversation.append(f"<assistant>\n{step.output}\n</assistant>")

    return conversation[-limit:]
```

**Why this works**:
- Step outputs ARE user-visible deliverables
- No message-level detail needed
- Preserves what Reason cares about: "what was produced"
- Token-efficient: summaries, not full traces

---

## Persistence

### Storage Location

```
SOOTHE_HOME/
  runs/
    {thread_id}/
      layer2_checkpoint.json     # Layer 2 unified state
      loop/                       # Working memory spill files
        step-{id}-{seq}.md
      steps/                      # Step reports
        step-{id}.json
      checkpoint.json            # Layer 1 checkpoint (separate)
      manifest.json              # Run manifest
```

### Write Timing

- **Per-iteration**: After each Plan-Execute cycle completes
- **Atomic**: Write to temp file, then rename
- **Co-located**: Same directory as working memory and step reports

### File Format

JSON with schema versioning:

```json
{
  "schema_version": "1.0",
  "thread_id": "thread-123",
  "goal": "Translate the document to Chinese",
  "created_at": "2026-04-08T10:30:00Z",
  "updated_at": "2026-04-08T10:35:00Z",
  "iteration": 2,
  "max_iterations": 8,
  "status": "running",
  "reason_history": [
    {
      "iteration": 1,
      "timestamp": "2026-04-08T10:30:00Z",
      "goal_text": "Translate the document to Chinese",
      "prior_step_outputs": [],
      "reasoning": "User wants translation of document content...",
      "status": "continue",
      "goal_progress": 0.0,
      "decision": {
        "type": "execute_steps",
        "steps": [
          {
            "id": "step_abc",
            "description": "Translate document to Chinese",
            "subagent": "claude",
            "expected_output": "Chinese translation"
          }
        ],
        "execution_mode": "sequential",
        "reasoning": "Use translation subagent"
      },
      "user_summary": "I'll translate the document",
      "soothe_next_action": "I will use the translation subagent"
    }
  ],
  "act_history": [
    {
      "iteration": 1,
      "timestamp": "2026-04-08T10:30:30Z",
      "steps": [
        {
          "step_id": "step_abc",
          "description": "Translate document to Chinese",
          "step_input": "Translate: [document content]",
          "success": true,
          "output": "文档的中文翻译...",
          "error": null,
          "tool_calls": [],
          "subagent_calls": [
            {
              "subagent_name": "claude",
              "task_input": "Translate: [document content]",
              "output_length": 8500,
              "success": true
            }
          ]
        }
      ],
      "execution_mode": "sequential",
      "duration_ms": 45000,
      "tool_call_count": 0,
      "subagent_task_count": 1,
      "hit_subagent_cap": false,
      "error_count": 0
    }
  ],
  "working_memory_state": {
    "entries": [
      {
        "step_id": "step_abc",
        "description": "Translate document to Chinese",
        "success": true,
        "inline_summary": "✓ Chinese translation (8500 chars)",
        "spill_relpath": "loop/step-abc-1.md"
      }
    ],
    "spill_files": ["loop/step-abc-1.md"]
  },
  "total_duration_ms": 90000,
  "total_tokens_used": 25000
}
```

---

## Module Organization

### New File Structure

```
src/soothe/cognition/agent_loop/
├── checkpoint.py              # Layer2Checkpoint model
├── state_manager.py           # Persistence + recovery
├── loop_agent.py              # Main orchestrator (refactored)
├── executor.py                # Execute phase (existing)
├── reason.py                  # Plan phase (existing)
└── schemas.py                 # StepAction, AgentDecision (existing)
```

### Layer2StateManager API

```python
class Layer2StateManager:
    """Manages Layer 2 checkpoint lifecycle."""

    def __init__(self, thread_id: str, workspace: Path):
        """Initialize with thread context."""

    def initialize(self, goal: str, max_iterations: int) -> Layer2Checkpoint:
        """Create new checkpoint for goal execution."""

    def load(self) -> Layer2Checkpoint | None:
        """Load existing checkpoint for recovery."""

    def save(self, checkpoint: Layer2Checkpoint) -> None:
        """Persist checkpoint to disk atomically."""

    def record_iteration(
        self,
        reason_result: PlanResult,
        act_wave: ActWaveRecord,
        working_memory: LoopWorkingMemory
    ) -> None:
        """Update checkpoint after each iteration."""

    def derive_reason_conversation(self, limit: int = 10) -> list[str]:
        """Get prior conversation from step outputs."""

    def finalize(self, status: str) -> None:
        """Mark checkpoint as completed/failed."""
```

---

## Integration with AgentLoop

### Refactored Execution Flow

```python
class AgentLoop:
    async def run_with_progress(self, goal: str, thread_id: str, ...):
        # Initialize state manager
        state_manager = Layer2StateManager(thread_id, workspace)

        # Try to recover from checkpoint
        checkpoint = state_manager.load()
        if checkpoint and checkpoint.status == "running":
            logger.info("Recovering Layer 2 from checkpoint at iteration %d", checkpoint.iteration)
            state = self._restore_state_from_checkpoint(checkpoint)
        else:
            checkpoint = state_manager.initialize(goal, max_iterations)
            state = self._create_initial_state(goal, thread_id, ...)

        # Main loop
        while state.iteration < state.max_iterations:
            # Plan phase
            reason_result = await self.reason_phase.reason(
                goal=goal,
                state=state,
                context=self._build_plan_context(state, state_manager)
            )

            if reason_result.is_done():
                state_manager.finalize(status="completed")
                yield "completed", {...}
                return

            # Execute phase
            act_wave = await self._execute_act_wave(decision, state)

            # Record iteration to checkpoint
            state_manager.record_iteration(
                reason_result,
                act_wave,
                state.working_memory
            )

            state.iteration += 1
```

---

## Recovery Flow

### Crash Scenario

**Crash at iteration 3, Plan phase**:

1. User restarts: `soothe "continue"`
2. Layer 2 loads `layer2_checkpoint.json`
3. Finds `status="running"`, `iteration=3`
4. Restores:
   - `reason_history` (2 Reason calls)
   - `act_history` (2 complete Act waves)
   - `working_memory_state` (spill files still exist)
5. Resumes from iteration 3, Plan phase
6. Plan phase derives prior context from `execute_history` step outputs

### Recovery Benefits

- ✅ Layer 2 state fully recoverable
- ✅ Working memory spill files preserved
- ✅ Plan history intact
- ✅ No Layer 1 dependency

---

## Benefits

| Aspect | Before (Layer 1 dependent) | After (Independent) |
|--------|---------------------------|---------------------|
| **Architectural separation** | ❌ Coupled to Layer 1 checkpoint | ✅ Independent persistence |
| **Recovery** | ❌ Layer 2 state lost on crash | ✅ Full Layer 2 recovery |
| **Reason context** | ⚠️ Loads verbose messages (thousands of tokens) | ✅ Semantic step I/O (hundreds of tokens) |
| **Debugging** | ⚠️ Message traces, not step traces | ✅ Human-readable step history |
| **Storage efficiency** | ❌ Full message history | ✅ Summarized step outputs |
| **Independence** | ❌ Coupled to LangGraph checkpointer | ✅ Own persistence format |

---

## Implementation Tasks

1. Create `Layer2Checkpoint` model in `checkpoint.py`
2. Implement `Layer2StateManager` in `state_manager.py`
3. Refactor `AgentLoop` to use state manager
4. Update Reason context derivation in `reason.py`
5. Add working memory state serialization
6. Add recovery tests

---

## Verification

After implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- All tests pass
- Layer 2 has independent checkpoint
- Recovery works without Layer 1

---

## Related Specifications

- **RFC-201**: Layer 2 Agentic Goal Execution
- **RFC-203**: Loop Working Memory
- **RFC-100**: Layer 1 CoreAgent Runtime
- **RFC-402**: Unified Thread Management

---

## Changelog

**2026-04-08 (created)**:
- Initial RFC defining Layer 2 independent checkpoint
- Unified state model including Plan history, Execute waves, working memory
- Step I/O semantics instead of message traces
- Per-iteration persistence