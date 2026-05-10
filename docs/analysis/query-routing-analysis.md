# Query Routing Analysis Report

> **Purpose**: Document how user queries flow through the Soothe system across different scenarios.
> **Date**: 2026-05-10
> **Updated**: 2026-05-10 (removed legacy input handler, added direct_execute optimization)
> **Scope**: CLI → Daemon → Runner → AgentLoop → CoreAgent

---

## 1. Overview

Soothe routes queries through a multi-layer architecture with decision points at each layer. The routing determines:

- **Execution mode**: Autonomous vs. agentic
- **Intent handling**: Fast path (chitchat/quiz) vs. full AgentLoop
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
│     - Default → _run_agentic_loop()                             │
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

### 6.1 Execution Mode Routing (lines 505-580)

```python
async def astream(self, request):
    if request.autonomous and self._goal_engine:
        # Goal-driven iteration
        return self._run_autonomous(request)
    else:
        # Default Reason→Act loop
        return self._run_agentic_loop(request)
```

### 6.2 Initialization (lines 84-199)

Runner initializes:

- `CoreAgent` via `create_soothe_agent()`
- Checkpointer, memory, planner, policy, durability
- `IntentClassifier` for unified intent classification

---

## 7. Intent Classification

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

### 7.1 Classification (lines 280-310)

`IntentClassifier.classify_intent()` determines:

| Intent Type | Route | Description |
|-------------|-------|-------------|
| `chitchat` | `_run_chitchat()` | Fast path, skip AgentLoop |
| `quiz` | `_run_quiz()` | Fast path, skip AgentLoop |
| `new_goal` | AgentLoop | Full loop execution, fresh goal |
| `continue_thread` | AgentLoop | Reuse working memory from prior goal |

### 7.2 Fast Path Execution

Fast path (chitchat/quiz) skips the AgentLoop orchestrator:

```
IntentClassifier → "chitchat" → _run_chitchat()
                → CoreAgent.astream() directly
                → Return response
```

---

## 8. AgentLoop Orchestrator

**File**: `packages/soothe/src/soothe/core/loop/engine/agent_loop.py`

### 8.1 run_with_progress() (lines 102-342)

```
┌─────────────────────────────────────────────────────────────────┐
│  run_with_progress(goal, thread_id, workspace)                  │
│    ↓                                                            │
│  1. Checkpoint recovery (lines 173-244)                         │
│     - Load from AgentLoopStateManager                           │
│     - Determine recovery scenario                               │
│    ↓                                                            │
│  2. Continue-thread mode (lines 153-162)                        │
│     - If intent_type=="continue_thread"                         │
│     - Seed ledger from prior goal                               │
│    ↓                                                            │
│  3. Loop Graph execution (lines 294-342)                        │
│     - Create LoopRuntimeContext                                 │
│     - invoke_agent_loop_graph(ctx)                              │
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
| `route_after_init` | Fast-path intent (chitchat/quiz) | END |
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
│  execute_goal() → AgentLoop.run_with_progress()                 │
│    ↓                                                            │
│  complete_goal() / fail_goal() → Mark status                    │
│    ↓                                                            │
│  Repeat until all goals terminal                                │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Backoff Reasoning (RFC-200, lines 430-447)

On failure, `GoalBackoffReasoner` suggests DAG restructuring:

- Analyzes failure context
- Suggests dependency adjustments
- Resets backoff target to pending for retry

---

## 11. CoreAgent Execution

**File**: `packages/soothe/src/soothe/core/agent/_core.py`

### 11.1 astream() (lines 163-224)

CoreAgent normalizes input and delegates to LangGraph:

```python
async def astream(self, input, config):
    state = normalize_to_state_dict(input)
    return self._graph.astream(state, config)
```

### 11.2 Layer 2 Hints in Config

The `config.configurable` contains execution hints:

| Key | Purpose |
|-----|---------|
| `thread_id` | LangGraph checkpoint thread |
| `workspace` | Execution workspace |
| `soothe_step_subagent` | Enforce task delegation |
| `soothe_step_expected_output` | Advisory output type |

---

## 12. Complete Routing Scenarios

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
_run_agentic_loop()
    ↓
AgentLoop.run_with_progress()
    ↓
LoopGraph.invoke_agent_loop_graph()
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
AgentLoop.run_with_progress(continue_thread_mode=True)
    ↓
Seeds working_memory from prior goal
    ↓
Reuses existing checkpoint state
    ↓
LoopGraph proceeds with accumulated context
```

### Scenario 3: Fast Path (Chitchat/Quiz)

```
User Query (simple question)
    ↓
IntentClassifier → "chitchat" or "quiz"
    ↓
_run_chitchat() or _run_quiz()
    ↓
CoreAgent.astream() directly
    ↓
Return response (skip AgentLoop)
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
AgentLoop.run_with_progress() for that goal
    ↓
GoalEngine.complete_goal() / fail_goal()
    ↓
Repeat until all goals terminal
```

### Scenario 5: Resume from Checkpoint

```
User Query (loop_id with existing checkpoint)
    ↓
AgentLoop loads checkpoint from AgentLoopStateManager
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

---

## 13. Key Routing Decision Points Summary

| # | Decision Point | File | Lines | Routes |
|---|----------------|------|-------|--------|
| 1 | Message type | `message_router.py` | 119-280 | `loop_input`, `loop_new`, `command`, etc. |
| 2 | Capacity check | `query_engine.py` | 159-198 | Reject or proceed |
| 3 | Runner selection | `runner/factory.py` | - | Local, Pool, Ray |
| 4 | Execution mode | `runner/__init__.py` | 505-580 | Autonomous or Agentic |
| 5 | Intent classification | `_runner_agentic.py` | 280-310 | chitchat, quiz, new_goal, continue_thread |
| 6 | Checkpoint status | `agent_loop.py` | 173-244 | Resume, new goal, fresh start |
| 7 | Plan routing | `routing.py` | 12-67 | goal_completion, execute, END |
| 8 | Goal completion | `plan_assess.py` | - | PLAN_ROUTE_GOAL_DONE signal |

---

## 14. Performance Considerations

### 14.1 Fast Path Optimization

Chitchat and quiz intents bypass AgentLoop for:

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
| RFC-400 | Daemon Communication Protocol |
| RFC-221 | Loop Runner Architecture |

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
│  │ Default → _run_agentic_loop() → IntentClassifier                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  INTENT CLASSIFIER                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Intent → Route                                                      │  │
│  │ chitchat → _run_chitchat() → CoreAgent (FAST PATH)                 │  │
│  │ quiz → _run_quiz() → CoreAgent (FAST PATH)                         │  │
│  │ new_goal → AgentLoop (FRESH)                                       │  │
│  │ continue_thread → AgentLoop (RESUME)                               │  │
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

*End of Report*