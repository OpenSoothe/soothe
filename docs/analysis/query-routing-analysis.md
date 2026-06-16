# Query Routing Analysis Report

> **Purpose**: Document how user queries flow through the Soothe system across different scenarios.
> **Version**: 1.2.0
> **Date**: 2026-05-11
> **Scope**: CLI → Daemon → Runner → StrangeLoop → CoreAgent

---

## Changelog

### v1.2.0 (2026-05-11)

#### Added
- **RFC-604 Status Assessment Integration** (Section 11)
  - Three-layer defense architecture for Plan phase robustness
  - `StatusAssessment` schema with ~50-80 token footprint
  - Conditional plan generation (skip when `status=done`)
  - Integration with Goal Engine for early routing decisions
  - Performance benefits: 50-65% token reduction per Plan phase

- **RFC-399 Descriptive Progress Levels** (Section 10.2)
  - Replaced numeric progress with descriptive levels: `none` | `low` | `medium` | `high` | `complete`
  - Easier for LLMs to estimate accurately than percentages
  - Reduces token usage in structured outputs
  - Aligns with human intuitive understanding

- **Error Propagation and Recovery Paths** (Section 17)
  - Error classification: fatal, retryable, validation, timeout
  - Fatal error propagation through `last_outcome` state
  - Checkpoint recovery scenarios (running, ready_for_next_goal, other)
  - Thread health metrics tracking
  - Fallback strategies with three-tier defense
  - Event propagation flow from Node → Runner → Daemon → Client

- **Scenarios 10-11** (Section 12)
  - Scenario 10: Error Recovery Flow - Complete error handling flow
  - Scenario 11: Autonomous Mode Recovery - RFC-200 backoff reasoning with LLM-driven DAG restructuring

- **IG-264 Minimal Fields Documentation**
  - Section 6.5: Minimal fields in SootheRunner
  - Section 9.4: Minimal fields in Loop Graph state transitions
  - Section 11.5: Lightweight StatusAssessment checks
  - Token reduction: ~60-97% vs full PlanResult schemas

#### Updated
- **Section 6: SootheRunner** - Refreshed with current selection logic
  - Execution mode selection criteria (autonomous vs agentic)
  - Fast path conditions with intent classification
  - Direct execute optimization (`require_goal_completion=False`)
  - Complete routing decision flow diagram
  - Latency estimates for each path

- **Section 13: Key Routing Decision Points**
  - Added entries for Status assessment, Progress level, Fatal error routing, Checkpoint recovery

- **Section 15: References**
  - Added RFC-399, RFC-604 to references table

---

## 1. Overview

Soothe routes queries through a multi-layer architecture with decision points at each layer. The routing determines:

- **Execution mode**: Autonomous vs. agentic
- **Intent handling**: Fast path (`quiz`) vs. full StrangeLoop
- **Thread continuation**: New goal vs. resume from checkpoint
- **Goal lifecycle**: Creation, execution, completion
- **Early completion optimization**: Direct execute vs. goal completion synthesis

---

## 2. Entry Points

### 2.1 CLI Entry

**File**: `packages/soothe-cli/src/soothe_cli/cli/main.py`

The CLI provides two modes:

| Mode | Flag | Flow |
|------|------|------|
| TUI | Default | `run_tui()` → WebSocket connection to daemon |
| Headless | `-p/--prompt` or `--no-tui` | `run_headless()` → WebSocket connection |

Both modes connect to the daemon via WebSocket for query execution.

### 2.2 Daemon Entry

**File**: `packages/soothe/src/soothe/daemon/server.py`

The daemon accepts queries via multiple transports:

| Transport | Handler |
|-----------|---------|
| WebSocket | `_transport_manager` (default port 8765) |
| HTTP REST | `_transport_manager` (optional) |
| Unix Socket | `_transport_manager` (local optimization) |

**Message arrival flow** (lines 805-836):
```
Transport receives message → _handle_transport_message()
                          → _dispatch_with_semaphore()
                          → MessageRouter.dispatch()
```

---

## 3. Message Router

**File**: `packages/soothe/src/soothe/daemon/message_router.py`

### 3.1 Message Type Routing (lines 119-280)

| Message Type | Handler | Description |
|--------------|---------|-------------|
| `command` | `/cancel`, `/exit`, `/quit` | Cancel loop or detach client |
| `loop_subscribe` | `_handle_loop_subscribe` | Subscribe client to loop events |
| `loop_new` | `_handle_loop_new` | Create new loop with UUID |
| `loop_input` | `_handle_loop_input` | Queue input to loop's isolated queue |
| `invoke_skill` | `_handle_invoke_skill` | Load skill markdown, enqueue composed prompt |
| `loop_detach` | `_handle_loop_detach` | Unsubscribe while loop continues |

> **Note**: Legacy global `input` message type was removed. All queries must use `loop_input` with a subscribed `loop_id`.

### 3.2 Loop Input Requirements (lines 1201-1269)

For `loop_input` messages, the router validates:

1. `loop_id` present in message
2. Loop exists in database
3. Client is subscribed to the loop

If valid, message is enqueued to `LoopInputDispatcher` for that `loop_id`.

---

## 4. Loop Isolation

**File**: `packages/soothe/src/soothe/daemon/loop_isolation.py`

### 4.1 Input Dispatcher

`LoopInputDispatcher` provides per-loop isolation:

- **Queue**: `_queues[loop_id]` — asyncio queue per loop
- **Worker**: `_workers[loop_id]` — worker task per loop
- **Processing**: Worker calls `_process_loop_input_message()` on daemon

### 4.2 Thread Binding (lines 32-93)

`bind_execution_thread_for_loop()` resolves:

| Component | Resolution |
|-----------|------------|
| thread_id | LangGraph checkpoint thread_id from loop metadata |
| workspace | `client_workspace` (user's CWD) OR per-loop daemon scratch |
| thread registry | Registry entries for tracking |

---

## 5. Query Engine

**File**: `packages/soothe/src/soothe/daemon/query_engine.py`

### 5.1 run_query() Flow (lines 83-567)

```
┌─────────────────────────────────────────────────────────────────┐
│  run_query(request)                                             │
│    ↓                                                            │
│  1. Capacity check (lines 159-198)                              │
│     - Reject if max_concurrent_threads reached                  │
│    ↓                                                            │
│  2. Vision preflight (lines 201-230)                            │
│     - Enrich user text with image understanding                 │
│    ↓                                                            │
│  3. Runner selection (lines 334-336)                            │
│     - LoopRunnerFactory.create_runner(loop_id)                  │
│    ↓                                                            │
│  4. Execution mode decision                                     │
│     - autonomous=True → _run_autonomous()                       │
│     - Default → _run_strange_loop()                             │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Runner Types

**File**: `packages/soothe/src/soothe/core/runner/factory.py`

| Runner | Condition | Description |
|--------|-----------|-------------|
| `PoolLoopRunner` | Worker pool enabled | Shared process pool |
| `RayLoopRunner` | Distributed enabled | Ray distributed execution |
| `LocalLoopRunner` | Default | Spawn subprocess per query |

---

## 6. SootheRunner

**File**: `packages/soothe/src/soothe/core/runner/__init__.py`

### 6.1 Execution Mode Selection (lines 505-598)

The runner selects execution mode based on query characteristics:

```python
async def astream(self, user_input, *, autonomous=False, ...):
    # Mode selection logic
    if autonomous and self._goal_engine:
        # RFC-0007: Goal-driven autonomous iteration
        async for chunk in self._run_autonomous(...):
            yield chunk
    else:
        # RFC-0008/RFC-201: Agentic loop with Reason→Act
        async for chunk in self._run_strange_loop(...):
            yield chunk
```

**Selection Criteria**:

| Mode | Condition | Use Case |
|------|-----------|----------|
| **Autonomous** | `autonomous=True` + `_goal_engine` | Complex multi-step tasks with explicit goal management |
| **Agentic** | Default | Single goal with iterative Reason→Act refinement |

### 6.2 Fast Path Conditions (lines 280-310)

Early intent classification enables fast-path routing:

```python
# Intent classification for routing decision
intent_classification = await self._intent_classifier.classify_intent(
    user_input,
    recent_messages=recent_for_classify,
    active_goal_id=active_goal_id,
    ...
)

# Fast path: skip StrangeLoop entirely for quiz (greetings, thanks, piggybacked trivia)
if intent_classification.intent_type == "quiz":
    async for chunk in self._run_quiz(user_input, ...):
        yield chunk
    return
```

**Fast Path Triggers**:

| Intent Type | Fast Path | Latency |
|-------------|-----------|---------|
| `quiz` | `_run_quiz()` → CoreAgent | ~1-2s |
| `new_goal` | Full StrangeLoop | ~5-30s |
| `continue_thread` | Full StrangeLoop | ~3-15s |

### 6.3 Initialization (lines 84-199)

Runner initializes:

- `CoreAgent` via `create_soothe_agent()`
- Checkpointer, memory, planner, policy, durability
- `IntentClassifier` for unified intent classification
- `ConcurrencyController` for hierarchical limits
- HITL interrupt resolver for interactive pauses

### 6.4 Current Selection Logic

**File**: `_runner_strange_loop.py` (lines 280-350)

Complete routing decision flow:

```
User Query
    ↓
IntentClassifier.classify_intent()
    ↓
┌─────────────────────────────────────────┐
│ intent_type == "quiz"                   │
│   → _run_quiz()                         │
│   → CoreAgent.astream() directly        │
│   → FAST PATH (~1-2s)                   │
└─────────────────────────────────────────┘
    ↓ (not quiz)
┌─────────────────────────────────────────┐
│ intent_type == "new_goal"               │
│   → StrangeLoop.run_with_progress()       │
│   → Full Plan→Execute loop              │
│   → AGENTIC PATH (~5-30s)               │
└─────────────────────────────────────────┘
    ↓
Emit StrangeLoopStartedEvent
    ↓
StrangeLoop execution with progress events
```

**Direct Execute Optimization**:

When `require_goal_completion=False` (from StatusAssessment):
- Skip extra LLM call for goal completion synthesis
- Use last AIMessage from execution as final response
- **Latency reduction**: ~500-1000ms saved per completion

### 6.5 Minimal Fields Optimization (IG-264)

The runner employs **minimal field schemas** for token-efficient execution:

```python
# StatusAssessment - only execution-critical fields
class StatusAssessment(BaseModel):
    status: Literal["continue", "replan", "done"]
    goal_progress: Literal["none", "low", "medium", "high", "complete"]
    assessment_reasoning: str = ""           # Brief only
    require_goal_completion: bool = False    # Skip extra LLM call
```

**Token Reduction Strategy**:

| Schema | Fields | Token Reduction |
|--------|--------|-----------------|
| Full PlanResult | 8+ fields | Baseline (~2000-3000 tokens) |
| StatusAssessment | 4 fields | **60% reduction** (~50-80 tokens) |
| PlanGeneration | 6 fields | **40-60% reduction** |

**Execution-Critical Fields Only**:
- `status` - Routing decision (continue/replan/done)
- `goal_progress` - Progress estimation for user feedback
- `require_goal_completion` - Optimization to skip unnecessary LLM calls
- Removed: verbose reasoning, optional metadata, nested objects

**Impact on Query Routing**:
- Faster plan phase execution
- Reduced truncation risk (smaller JSON)
- Lower latency for routing decisions
- Maintained decision quality with minimal context

---

## 7. Intent Classification

**File**: `packages/soothe/src/soothe/core/runner/_runner_strange_loop.py`

### 7.1 Classification (lines 280-310)

`IntentClassifier.classify_intent()` determines:

| Intent Type | Route | Description |
|-------------|-------|-------------|
| `quiz` | `_run_quiz()` | Fast path, skip StrangeLoop |
| `new_goal` | StrangeLoop | Full loop execution, fresh goal |
| `continue_thread` | StrangeLoop | Reuse working memory from prior goal |

### 7.2 Fast Path Execution

Fast path (`quiz`) skips the StrangeLoop orchestrator:

```
IntentClassifier → "quiz" → _run_quiz()
                → CoreAgent.astream() directly
                → Return response
```

---

## 8. StrangeLoop Orchestrator

**File**: `packages/soothe/src/soothe/core/loop/engine/strange_loop.py`

### 8.1 run_with_progress() (lines 102-342)

```
┌─────────────────────────────────────────────────────────────────┐
│  run_with_progress(goal, thread_id, workspace)                  │
│    ↓                                                            │
│  1. Checkpoint recovery (lines 173-244)                         │
│     - Load from StrangeLoopStateManager                           │
│     - Determine recovery scenario                               │
│    ↓                                                            │
│  2. Continue-thread mode (lines 153-162)                        │
│     - If intent_type=="continue_thread"                         │
│     - Seed ledger from prior goal                               │
│    ↓                                                            │
│  3. Loop Graph execution (lines 294-342)                        │
│     - Create LoopRuntimeContext                                 │
│     - invoke_strange_loop_graph(ctx)                              │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Checkpoint Recovery Scenarios

| Status | Action |
|--------|--------|
| `running` | Resume at iteration (recovery_valid_resume) |
| `ready_for_next_goal` | Start new goal in same loop |
| Other | Initialize fresh checkpoint |

---

## 9. Loop Graph Topology

**File**: `packages/soothe/src/soothe/core/loop/orchestrator/builder.py`

### 9.1 Graph Structure (RFC-220)

```
START → init_or_resume → iteration_gate → iteration_start
     → bounded_evidence_gather → plan_assess
     → [plan_generate OR resolve_decision OR goal_completion]
     → validate_evidence_bindings → execute → record_iteration
     → iteration_gate (loop)
```

### 9.2 Routing Conditions

**File**: `packages/soothe/src/soothe/core/loop/orchestrator/routing.py`

| Function | Condition | Route |
|----------|-----------|-------|
| `route_after_init` | Fast-path intent (`quiz`) | END |
| `route_after_plan` | `PLAN_ROUTE_GOAL_DONE` | goal_completion |
| `route_after_execute` | Fatal error | END |
| | Otherwise | record_iteration → loop |

### 9.3 Key Nodes

| Node | File | Purpose |
|------|------|---------|
| `init_or_resume` | `nodes/init_or_resume.py` | Classify intent, set route |
| `plan_assess` | `nodes/plan_assess.py` | Evaluate plan completeness |
| `plan_generate` | `nodes/plan_generate.py` | Generate/update execution plan |
| `execute` | `nodes/execute.py` | Execute step via CoreAgent |
| `goal_completion` | `nodes/goal_completion.py` | Synthesize results |

### 9.4 Minimal Fields in State Transitions (IG-264)

The Loop Graph uses **minimal field state** for efficient routing decisions:

**State Schema Optimization**:

```python
# Minimal state for routing decisions (IG-264)
class LoopState:
    # Execution-critical only
    iteration: int
    goal: str
    step_results: list[StepResult]  # Truncated evidence
    
    # Routing fields (minimal)
    last_outcome: Literal["continue", "fatal", "max_iterations"]
    intent_route: Literal["fast_path", "strange_loop"]
    plan_route: Literal["PLAN_ROUTE_GOAL_DONE", "continue"]
```

**Routing Condition Efficiency**:

| Routing Function | Minimal Check | Full State Access |
|------------------|---------------|-------------------|
| `route_after_init` | `state.get("intent_route")` | ❌ No full context needed |
| `route_after_plan` | `state.get("plan_route")` | ❌ No plan details needed |
| `route_after_execute` | `state.get("last_outcome")` | ❌ No step results needed |
| `route_after_assess` | `state.get("assess_route")` | ❌ No assessment details needed |

**State Transition Optimization**:

```
Node Execution
    ↓
Update minimal routing fields only
    ↓
┌─────────────────────────────────────────┐
│ Before IG-264:                          │
│   - Full state serialization            │
│   - All fields checkpointed             │
│   - ~500-1000 tokens per transition     │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ After IG-264:                           │
│   - Minimal fields only                 │
│   - Routing decisions: <50 tokens       │
│   - Full state: lazy loaded             │
│   - ~80% reduction in transition cost   │
└─────────────────────────────────────────┘
```

**Impact on Graph Execution**:
- Faster state transitions between nodes
- Reduced checkpoint I/O
- Lower memory footprint during routing
- Maintained correctness with minimal context

---

## 10. Goal Engine (Autonomous Mode)

**File**: `packages/soothe/src/soothe/core/goal_engine/engine.py`

### 10.1 Goal Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│  GoalEngine                                                     │
│    ↓                                                            │
│  create_goal() → Goal with priority, dependencies               │
│    ↓                                                            │
│  ready_goals() → Goals whose dependencies complete              │
│    ↓                                                            │
│  next_goal() → Highest-priority ready goal                      │
│    ↓                                                            │
│  execute_goal() → StrangeLoop.run_with_progress()                 │
│    ↓                                                            │
│  complete_goal() / fail_goal() → Mark status                    │
│    ↓                                                            │
│  Repeat until all goals terminal                                │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Goal Progress Tracking (RFC-399, RFC-604)

Goals track progress using **descriptive levels** (IG-399) instead of numeric values:

| Level | Description | Typical Usage |
|-------|-------------|---------------|
| `none` | No progress yet | Goal just created |
| `low` | Initial steps completed | Early execution phase |
| `medium` | Significant work done | Mid-execution |
| `high` | Near completion | Final steps |
| `complete` | Goal achieved | Ready for completion |

**Benefits**:
- Easier for LLMs to estimate accurately than numeric percentages
- Reduces token usage in structured outputs
- Aligns with human intuitive understanding of progress

### 10.3 Backoff Reasoning (RFC-200, lines 430-447)

On failure, `GoalBackoffReasoner` suggests DAG restructuring:

- Analyzes failure context
- Suggests dependency adjustments
- Resets backoff target to pending for retry

---

## 11. Status Assessment Integration (RFC-604)

**File**: `packages/soothe/src/soothe/core/loop/state/schemas.py`

### 11.1 Overview

RFC-604 introduces a **three-layer defense** for Plan phase robustness, with StatusAssessment as the key lightweight component for query routing decisions.

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Schema Diet                                   │
│  - Simplified PlanResult schema                         │
│  - max_length constraints                               │
│  Token reduction: ~40-60%                               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Query Splitting (StatusAssessment)            │
│  - Split: StatusAssessment + PlanGeneration             │
│  - Conditional plan generation                          │
│  Token reduction per call: ~50-65%                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Fallback (Existing)                           │
│  - 3 retry attempts                                     │
│  - Manual JSON extraction                               │
│  - Conservative defaults                                │
└─────────────────────────────────────────────────────────┘
```

### 11.2 StatusAssessment Schema

**Purpose**: Lightweight progress/status check before plan generation

```python
class StatusAssessment(BaseModel):
    """Lightweight schema for status assessment (~50-80 tokens)."""

    status: Literal["continue", "replan", "done"]
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "none"
    assessment_reasoning: str = ""           # Brief justification
    require_goal_completion: bool = False    # Skip extra LLM call optimization
```

**Fields**:

| Field | Type | Purpose |
|-------|------|---------|
| `status` | `continue\|replan\|done` | Routing decision for next phase |
| `goal_progress` | Descriptive level | Progress estimation (RFC-399) |
| `assessment_reasoning` | string | Brief status justification |
| `require_goal_completion` | boolean | Optimization flag (skip extra LLM call) |

### 11.3 Integration with Goal Engine

StatusAssessment feeds into Goal Engine routing:

```
StrangeLoop Plan Phase
    ↓
StatusAssessment LLM call (lightweight)
    ↓
┌─────────────────────────────────────────┐
│ status="done" + goal_progress="complete" │
│   → Goal completion synthesis           │
│   → require_goal_completion?            │
│      True  → Extra LLM call             │
│      False → Use last AIMessage         │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ status="continue"                       │
│   → PlanGeneration LLM call             │
│   → Generate/update execution plan      │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ status="replan"                         │
│   → PlanGeneration with fresh plan      │
│   → Discard in-flight decision          │
└─────────────────────────────────────────┘
```

### 11.4 Query Routing Impact

StatusAssessment enables **early routing decisions**:

| Assessment Result | Route | Action |
|-------------------|-------|--------|
| `status=done`, `progress=complete` | Goal Completion | Synthesize final response |
| `status=continue`, `progress=high` | Plan Generation | Minimal steps to finish |
| `status=replan`, `progress=low` | Plan Generation | Fresh plan, more steps |
| `require_goal_completion=false` | Fast Path | Skip extra LLM call |

**Performance Benefits**:
- **Token efficiency**: 50-65% reduction per Plan phase call
- **Latency**: Skip PlanGeneration when goal complete
- **Reliability**: Smaller schema reduces truncation risk

### 11.5 Lightweight Status Checks (IG-264)

StatusAssessment implements **minimal field design** for lightweight status checks:

**Minimal Schema Principle** (IG-264):
```python
class StatusAssessment(BaseModel):
    """Minimal fields for 60% token reduction vs full PlanResult."""
    
    # Core routing decision (1 field)
    status: Literal["continue", "replan", "done"]
    
    # Progress indicator (1 field, descriptive)
    goal_progress: Literal["none", "low", "medium", "high", "complete"]
    
    # Brief context (optional, truncated)
    assessment_reasoning: str = ""  # Brief only
    
    # Optimization flag (1 field)
    require_goal_completion: bool = False
```

**Field Count Comparison**:

| Schema | Total Fields | Required | Optional | Token Estimate |
|--------|--------------|----------|----------|----------------|
| Full PlanResult | 8+ | 5 | 3+ | ~2000-3000 |
| StatusAssessment | 4 | 2 | 2 | **~50-80** |
| **Reduction** | **50%** | **60%** | **33%** | **~97%** |

**Why Minimal Fields Matter for Routing**:

1. **Speed**: Faster LLM inference with smaller schema
2. **Reliability**: Reduced JSON truncation risk
3. **Cost**: Lower token usage per assessment call
4. **Focus**: Only execution-critical information

**Removed vs Retained**:

| Removed (Non-Critical) | Retained (Critical) |
|------------------------|---------------------|
| `evidence_summary` (verbose) | `status` (routing) |
| `confidence` (optional) | `goal_progress` (progress) |
| `decision` (large object) | `require_goal_completion` (optimize) |
| `full_output` (output) | `assessment_reasoning` (brief context) |
| Nested schemas | Flat structure |

**Query Routing Impact**:
- StatusAssessment enables **early routing decisions** without heavy schema
- 60% token reduction means faster plan phase execution
- Minimal fields sufficient for `continue`/`replan`/`done` routing
- Full PlanGeneration only when `status != done`

---

## 12. CoreAgent Execution

**File**: `packages/soothe/src/soothe/core/agent/_core.py`

### 12.1 astream() (lines 163-224)

CoreAgent normalizes input and delegates to LangGraph:

```python
async def astream(self, input, config):
    state = normalize_to_state_dict(input)
    return self._graph.astream(state, config)
```

### 12.2 Layer 2 Hints in Config

The `config.configurable` contains execution hints:

| Key | Purpose |
|-----|---------|
| `thread_id` | LangGraph checkpoint thread |
| `workspace` | Execution workspace |
| `soothe_step_subagent` | Enforce task delegation |
| `soothe_step_expected_output` | Advisory output type |

---

## 13. Complete Routing Scenarios

### Scenario 1: New Goal (Default)

```
User Query
    ↓
CLI/Daemon → loop_input message
    ↓
MessageRouter._handle_loop_input()
    ↓
LoopInputDispatcher.enqueue(loop_id)
    ↓
Worker → daemon._process_loop_input_message()
    ↓
QueryEngine.run_query()
    ↓
LoopRunnerFactory → LocalLoopRunner (subprocess)
    ↓
SootheRunner.astream()
    ↓
IntentClassifier → "new_goal"
    ↓
_run_strange_loop()
    ↓
StrangeLoop.run_with_progress()
    ↓
LoopGraph.invoke_strange_loop_graph()
    ↓
Nodes: init_or_resume → plan_assess → plan_generate → execute
    ↓
CoreAgent.astream() for each step
```

### Scenario 2: Continue Thread

```
User Query (with thread context)
    ↓
IntentClassifier → "continue_thread"
    ↓
StrangeLoop.run_with_progress(continue_thread_mode=True)
    ↓
Seeds working_memory from prior goal
    ↓
Reuses existing checkpoint state
    ↓
LoopGraph proceeds with accumulated context
```

### Scenario 3: Fast Path (Quiz)

```
User Query (simple question)
    ↓
IntentClassifier → "quiz"
    ↓
_run_quiz()
    ↓
CoreAgent.astream() directly
    ↓
Return response (skip StrangeLoop)
```

### Scenario 4: Autonomous Mode

```
User Query (autonomous=True)
    ↓
QueryEngine.run_query(autonomous=True)
    ↓
SootheRunner.astream() → _run_autonomous()
    ↓
GoalEngine.create_goal() → goal DAG
    ↓
GoalEngine.next_goal() → highest priority ready goal
    ↓
StrangeLoop.run_with_progress() for that goal
    ↓
GoalEngine.complete_goal() / fail_goal()
    ↓
Repeat until all goals terminal
```

### Scenario 5: Resume from Checkpoint

```
User Query (loop_id with existing checkpoint)
    ↓
StrangeLoop loads checkpoint from StrangeLoopStateManager
    ↓
status=="running" → Resume at iteration
status=="ready_for_next_goal" → Start new goal in same loop
status=="pending"/"completed" → Initialize fresh checkpoint
    ↓
Continue execution with recovered state
```

### Scenario 6: Goal Completion

```
plan_assess node → PLAN_ROUTE_GOAL_DONE signal
    ↓
goal_completion node
    ↓
Synthesize results from all steps
    ↓
Emit GoalProgressEvent
    ↓
Update checkpoint to "ready_for_next_goal" or "completed"
    ↓
END or loop for next goal
```

### Scenario 7: Skill Invocation

```
User Query (invoke_skill message)
    ↓
MessageRouter._handle_invoke_skill()
    ↓
Load skill markdown content
    ↓
Compose prompt with skill context
    ↓
Enqueue to LoopInputDispatcher
    ↓
Follow standard query flow with skill-loaded context
```

### Scenario 8: Loop Cancel

```
User command: /cancel
    ↓
MessageRouter._handle_command() → "cancel"
    ↓
Cancel active execution for loop_id
    ↓
Update checkpoint to "cancelled"
    ↓
Emit cancellation event to subscribed clients
```

### Scenario 9: Status Assessment Routing (RFC-604)

```
StrangeLoop enters Plan Phase
    ↓
StatusAssessment LLM call (lightweight, ~50-80 tokens)
    ↓
┌─────────────────────────────────────────┐
│ status="done" + goal_progress="complete" │
│   → Skip PlanGeneration                 │
│   → Direct to goal_completion           │
│   → require_goal_completion?            │
│      True  → Extra LLM call for synthesis
│      False → Use last AIMessage directly│
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ status="continue" or "replan"           │
│   → PlanGeneration LLM call             │
│   → Generate/update execution plan      │
│   → Proceed to Execute phase            │
└─────────────────────────────────────────┘
```

**Benefits**:
- 50-65% token reduction per Plan phase
- Skip unnecessary plan generation when goal complete
- Faster routing decisions with lightweight schema

### Scenario 10: Error Recovery Flow

```
Step Execution in Execute Phase
    ↓
Step encounters fatal error (tool failure, timeout, etc.)
    ↓
Executor captures StepResult with error_type="fatal"
    ↓
node_execute() detects fatal_errors in results
    ↓
┌─────────────────────────────────────────┐
│ Update goal_record.status = "failed"    │
│ Update checkpoint.thread_health_metrics │
│   - consecutive_goal_failures += 1      │
│   - last_goal_status = "failed"          │
└─────────────────────────────────────────┘
    ↓
Set checkpoint.status = "ready_for_next_goal"
    ↓
await state_manager.save(checkpoint)      ← Persist recovery state
    ↓
Emit "fatal_error" event with error details
    ↓
Return {"last_outcome": "fatal"}
    ↓
route_after_execute() detects "fatal"
    ↓
Route to END (terminate graph execution)
    ↓
Runner receives fatal event
    ↓
Daemon broadcasts to subscribed clients
    ↓
CLI/TUI displays error to user
    ↓
┌─────────────────────────────────────────┐
│ User can:                               │
│   - Start new goal in same thread       │
│   - Resume from checkpoint (if valid)   │
│   - Cancel and start fresh              │
└─────────────────────────────────────────┘
```

**Recovery Options**:

| Error Scenario | Recovery Action | Checkpoint Status |
|----------------|-----------------|-------------------|
| Fatal step error | Goal marked failed | `ready_for_next_goal` |
| Max iterations reached | Graceful termination | `completed` |
| Validation failure | Fallback defaults | `running` (continue) |
| Timeout | Step marked failed | `running` (continue) |

### Scenario 11: Autonomous Mode Recovery (RFC-200)

```
User Query (autonomous=True, complex multi-step task)
    ↓
GoalEngine.create_goal() → Goal with dependencies
    ↓
StrangeLoop.run_with_progress() executes goal
    ↓
┌─────────────────────────────────────────┐
│ Step execution FAILS                    │
│   - Tool error / Timeout / Validation   │
│   - StepResult.error_type = "fatal"     │
└─────────────────────────────────────────┘
    ↓
Goal marked failed in checkpoint
    ↓
GoalEngine detects failure
    ↓
┌─────────────────────────────────────────┐
│ GoalBackoffReasoner.reason_backoff()    │
│   - Analyze goal DAG state              │
│   - Review dependency chain             │
│   - Examine failure evidence            │
│   - LLM decides WHERE to backoff        │
└─────────────────────────────────────────┘
    ↓
BackoffDecision returned:
    ↓
┌─────────────────────────────────────────┐
│ Option A: Retry Same Goal               │
│   - Isolated failure                    │
│   - Reset goal to "pending"             │
│   - Increment retry_count               │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Option B: Backoff to Parent             │
│   - Dependency assumption failed        │
│   - Reset parent + children             │
│   - Re-evaluate prerequisites           │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Option C: Create Corrective Goals       │
│   - Systemic issue detected             │
│   - new_directives creates new goals    │
│   - Adjust DAG structure                │
└─────────────────────────────────────────┘
    ↓
GoalEngine.next_goal() selects next ready goal
    ↓
Repeat until all goals terminal
```

**Backoff Decision Schema**:

```python
class BackoffDecision:
    backoff_to_goal_id: str      # Where to resume in DAG
    reason: str                   # LLM reasoning for decision
    new_directives: list[Goal]   # Optional corrective goals
    evidence_summary: str         # Condensed failure analysis
```

**Recovery Strategies**:

| Failure Pattern | Backoff Action | DAG Impact |
|-----------------|----------------|------------|
| Isolated tool failure | Retry same goal | None |
| Dependency invalid | Backoff to parent | Parent reset |
| Systemic issue | Create corrective goals | DAG extended |
| Max retries exceeded | Mark failed permanently | Goal terminal |

---

## 13. Key Routing Decision Points Summary

| # | Decision Point | File | Lines | Routes |
|---|----------------|------|-------|--------|
| 1 | Message type | `message_router.py` | 119-280 | `loop_input`, `loop_new`, `command`, etc. |
| 2 | Capacity check | `query_engine.py` | 159-198 | Reject or proceed |
| 3 | Runner selection | `runner/factory.py` | - | Local, Pool, Ray |
| 4 | Execution mode | `runner/__init__.py` | 505-580 | Autonomous or Agentic |
| 5 | Intent classification | `_runner_strange_loop.py` | 280-310 | quiz, new_goal, continue_thread |
| 6 | Checkpoint status | `strange_loop.py` | 173-244 | Resume, new goal, fresh start |
| 7 | Plan routing | `routing.py` | 12-67 | goal_completion, execute, END |
| 8 | Goal completion | `plan_assess.py` | - | PLAN_ROUTE_GOAL_DONE signal |
| 9 | Status assessment | `state/schemas.py` | 453-475 | continue, replan, done |
| 10 | Progress level | `state/schemas.py` | 470 | none, low, medium, high, complete |
| 11 | Fatal error routing | `routing.py` | 42-67 | END on fatal |
| 12 | Checkpoint recovery | `strange_loop.py` | 170-244 | Resume, new goal, fresh |

---

## 14. Performance Considerations

### 14.1 Fast Path Optimization

Quiz intents bypass StrangeLoop for:

- Reduced latency (single CoreAgent call)
- Lower resource usage (no plan generation)
- Better user experience for simple queries

### 14.2 Loop Isolation

Per-loop queues ensure:

- No cross-loop interference
- Independent failure domains
- Controlled concurrency per loop

### 14.3 Runner Selection

| Runner | Use Case |
|--------|----------|
| Local | Single-user, simple deployment |
| Pool | Multi-user, shared resources |
| Ray | Distributed, high-scale |

---

## 15. References

| Document | Location |
|----------|----------|
| RFC-000 | System Conceptual Design |
| RFC-200 | Agentic Goal Execution |
| RFC-220 | Loop Graph topology |
| RFC-399 | Descriptive Progress Levels |
| RFC-302 | Daemon Communication Protocol |
| RFC-221 | Loop Runner Architecture |
| RFC-604 | Plan Phase Robustness (StatusAssessment) |

---

## Appendix A: Routing Flow Diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           USER QUERY                                      │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  ENTRY LAYER                                                              │
│  ┌─────────────┐    ┌─────────────┐                                       │
│  │ CLI (Typer) │    │ Daemon      │                                       │
│  │ - TUI mode  │    │ - WebSocket │                                       │
│  │ - Headless  │    │ - HTTP      │                                       │
│  └─────────────┘    └─────────────┘                                       │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  MESSAGE ROUTER                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Message Type → Handler                                              │  │
│  │ loop_input → LoopInputDispatcher                                   │  │
│  │ loop_new → Create loop                                             │  │
│  │ command → /cancel, /exit                                           │  │
│  │ invoke_skill → Skill composition                                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  QUERY ENGINE                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Capacity Check: max_concurrent_threads                          │  │
│  │ 2. Vision Preflight: Image enrichment                              │  │
│  │ 3. Runner Selection: Local | Pool | Ray                            │  │
│  │ 4. Mode Selection: autonomous | agentic                            │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  SOOTHE RUNNER                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Execution Mode Routing                                             │  │
│  │ autonomous=True → _run_autonomous() → GoalEngine                   │  │
│  │ Default → _run_strange_loop() → IntentClassifier                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  INTENT CLASSIFIER                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Intent → Route                                                      │  │
│  │ quiz → _run_quiz() → CoreAgent (FAST PATH)                         │  │
│  │ new_goal → StrangeLoop (FRESH)                                       │  │
│  │ continue_thread → StrangeLoop (RESUME)                               │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  AGENT LOOP                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Checkpoint Recovery                                                 │  │
│  │ - running → Resume iteration                                       │  │
│  │ - ready_for_next_goal → New goal in loop                           │  │
│  │ - other → Fresh checkpoint                                         │  │
│  │                                                                     │  │
│  │ Continue-Thread Mode                                                │  │
│  │ - Seed working_memory from prior goal                              │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LOOP GRAPH (RFC-220)                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ START → init_or_resume                                              │  │
│  │      → iteration_gate                                               │  │
│  │      → iteration_start                                              │  │
│  │      → bounded_evidence_gather                                      │  │
│  │      → plan_assess                                                  │  │
│  │      → [plan_generate | resolve_decision | goal_completion]        │  │
│  │      → validate_evidence_bindings                                   │  │
│  │      → execute → CoreAgent.astream()                                │  │
│  │      → record_iteration                                             │  │
│  │      → iteration_gate (LOOP)                                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  CORE AGENT                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ LangGraph CompiledStateGraph                                        │  │
│  │ - Reason→Act loop                                                   │  │
│  │ - Tool execution                                                    │  │
│  │ - Response generation                                               │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                           RESPONSE TO USER                                │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 17. Error Propagation and Recovery Paths

**Files**:
- `packages/soothe/src/soothe/core/loop/orchestrator/routing.py`
- `packages/soothe/src/soothe/core/loop/orchestrator/nodes/execute_steps.py`
- `packages/soothe/src/soothe/core/loop/engine/strange_loop.py`
- `packages/soothe/src/soothe/core/loop/state/manager.py`

### 17.1 Error Classification

The StrangeLoop categorizes errors into distinct types for appropriate handling:

| Error Type | Description | Handling Strategy |
|------------|-------------|-------------------|
| `fatal` | Unrecoverable execution failure | Abort loop, mark goal failed |
| `retryable` | Transient failure, can retry | Retry with backoff |
| `validation` | Schema/validation failure | Fallback to conservative defaults |
| `timeout` | Execution timeout | Cancel step, report timeout |

### 17.2 Fatal Error Propagation

Fatal errors propagate through the Loop Graph via `last_outcome` state:

```
Execute Phase
    ↓
Step execution detects fatal error
    ↓
Set goal_record.status = "failed"
    ↓
Set checkpoint.status = "ready_for_next_goal"
    ↓
Update thread_health_metrics.consecutive_goal_failures += 1
    ↓
Emit "fatal_error" event
    ↓
Return {"last_outcome": "fatal"}
    ↓
Routing functions detect "fatal" → route to END
```

**Routing Functions** (from `routing.py`):

| Function | Fatal Detection | Route on Fatal |
|----------|-----------------|----------------|
| `route_after_resolve_decision` | `state.get("last_outcome") == "fatal"` | END |
| `route_after_validate_evidence` | `state.get("last_outcome") == "fatal"` | END |
| `route_after_execute` | `state.get("last_outcome") == "fatal"` | END |

### 17.3 Checkpoint Recovery Scenarios

**File**: `strange_loop.py` (lines 170-244)

The StrangeLoop implements three checkpoint recovery scenarios:

```
Checkpoint Load
    ↓
┌─────────────────────────────────────────┐
│ Status == "running"                     │
│   → Valid resume scenario               │
│   → Restore iteration count             │
│   → Continue from saved state           │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Status == "ready_for_next_goal"         │
│   → Start new goal in same loop         │
│   → Preserve thread history             │
│   → Optional: seed from prior goal      │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Status == "completed"/"failed"/other    │
│   → Initialize fresh checkpoint         │
│   → Start new goal execution            │
└─────────────────────────────────────────┘
```

**Recovery Decision Logic**:

```python
if checkpoint.status == "running":
    if valid_goal_index:
        recovery_valid_resume = True
        iteration = goal_record.iteration  # Resume
    else:
        # Invalid checkpoint, re-initialize
        checkpoint = await state_manager.initialize(...)
elif checkpoint.status == "ready_for_next_goal":
    # Continue with new goal
    goal_record = state_manager.start_new_goal(goal, max_iterations)
else:
    # Fresh start
    checkpoint = await state_manager.initialize(...)
```

### 17.4 Thread Health Metrics

**File**: `checkpoint.py` - `ThreadHealthMetrics`

Track execution health for recovery decisions:

| Metric | Purpose | Action Trigger |
|--------|---------|----------------|
| `consecutive_goal_failures` | Detect failure patterns | Backoff/restructure |
| `last_goal_status` | Last execution outcome | Health assessment |
| `iteration_count` | Progress tracking | Max iteration guard |

### 17.5 Fallback Strategies

#### Layer 3 Fallback (RFC-604)

When StatusAssessment or PlanGeneration fails:

```
Structured Output Failure
    ↓
Tier 1: 3 retry attempts with structured output
    ↓
Tier 2: Regular model + manual JSON extraction/repair
    ↓
Tier 3: Conservative default PlanResult
    ↓
Continue execution with safe defaults
```

**Conservative Defaults**:
- `status`: "replan"
- `plan_action`: "new"
- `goal_progress`: "none"
- `next_action`: "I need to stop here before completion."

### 17.6 Error Event Propagation

Errors emit through the event stream for observability:

| Event Type | Emitted When | Data |
|------------|--------------|------|
| `fatal_error` | Fatal step failure | error, step_id |
| `step_failed` | Step execution failure | step_id, error |
| `checkpoint_saved` | State persisted | status, iteration |
| `goal_failed` | Goal marked failed | goal_id, reason |

**Event Flow**:

```
Node Execution
    ↓
Error Detected
    ↓
await ctx.emit("fatal_error", {...})
    ↓
Event streamed to Runner
    ↓
Runner surfaces to Daemon
    ↓
Daemon broadcasts to subscribed clients
    ↓
CLI/TUI displays error to user
```

### 17.7 Recovery Best Practices

1. **Always save checkpoint before fatal exit** - Ensures state is recoverable
2. **Update health metrics on failure** - Enables pattern detection
3. **Emit descriptive error events** - Aids debugging and user feedback
4. **Use conservative defaults in fallback** - Prevents cascading failures
5. **Validate checkpoint integrity on load** - Guards against corruption

---

*End of Report*