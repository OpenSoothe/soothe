# User Query Processing Flow

This document describes how a user query flows through Soothe from CLI entry to final response.

**Repository layout:** Daemon and AgentLoop live under `packages/soothe/src/soothe/` (notably `core/runner/`, `core/agent_loop/`). The CLI Typer app lives under `packages/soothe-cli/src/soothe_cli/`. Older `src/soothe/cognition/*` paths have been folded into `core/`.

## Overview

```
User Input → CLI Entry → Daemon → Runner → Planning → Agent Execution → Response
```

## 1. Entry Points

### CLI Entry

The CLI supports two primary modes:

```
soothe -p "query"     →  Headless mode (single query)
soothe                →  TUI mode (interactive)
```

**Flow:**
```
main.py:main()
    ↓
run_cmd.py:run_impl()
    ↓
┌─────────────┐
│ --no-tui?   │
└─────────────┘
    ↓           ↓
   YES         NO
    ↓           ↓
headless.py   run_tui()
    ↓
run_headless()
```

**Key files:**
- `packages/soothe-cli/src/soothe_cli/cli/main.py` — Typer app entry point
- `packages/soothe-cli/src/soothe_cli/cli/commands/run_cmd.py` — `run_impl()` routing logic
- `packages/soothe-cli/src/soothe_cli/cli/execution/headless.py` — Headless execution

### Daemon Connection

In headless mode, the system checks for a running daemon:

```
run_headless()
    ↓
SootheDaemon._is_socket_live()?
    ↓              ↓
   YES            NO
    ↓              ↓
Connect via    Auto-start daemon
DaemonClient      ↓
    ↓         daemon_cmd.py:daemon_start()
run_headless_via_daemon()
```

**Key files:**
- `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py` — Daemon client interaction

## 2. Daemon Processing

The daemon server handles incoming queries:

```
DaemonClient.send_new_thread(text, thread_id)
    ↓
DaemonServer._handle_transport_message()
    ↓
_handle_client_message()
    ↓
┌────────────────────┐
│ Message Type:       │
│ - "input"           │ → _run_query()
│ - "resume_thread"   │ → Resume existing thread
│ - "interrupt"       │ → Handle interrupt
└────────────────────┘
    ↓
_run_query()
    ↓
SootheRunner.astream(text, thread_id, ...)
    ↓
Broadcast events → EventBus → Subscribed clients
```

**Key files:**
- `packages/soothe/src/soothe/daemon/server.py` — `SootheDaemon` class
- `packages/soothe/src/soothe/daemon/_handlers.py` — Query handling logic
- `packages/soothe/src/soothe/daemon/event_bus.py` — Event routing

## 3. Runner Orchestration

`SootheRunner.astream()` is the central orchestration point:

```
SootheRunner.astream(text, thread_id, autonomous, subagent)
    ↓
┌─────────────────────────────────────┐
│         Initial Classification      │
│   UnifiedClassifier.classify()     │
└─────────────────────────────────────┘
                 ↓
    ┌────────────┼────────────┐
    ↓            ↓            ↓
chitchat    agentic      subagent?
    ↓            ↓            ↓
chitchat    default      direct
response    mode         execution
                ↓
        _run_agentic_loop()
```

**Routing Logic:**

| Condition | Path | Description |
|-----------|------|-------------|
| `subagent` specified | Direct | Route directly to subagent |
| `autonomous=True` | Autonomous | Goal-driven execution |
| Default | Agentic Loop | Iterative observe-act-verify |

**Key files:**
- `packages/soothe/src/soothe/core/runner/__init__.py` — Runner package entry
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py` — Agentic loop
- `packages/soothe/src/soothe/core/runner/_runner_autonomous.py` — Autonomous mode

## 4. Agentic Loop (RFC-200)

The default execution mode follows an iterative observe-act-verify cycle:

```
┌─────────────────────────────────────────────────────┐
│                  AGENTIC LOOP                       │
│           (max_iterations: default 3)              │
└─────────────────────────────────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
         ↓              ↓              ↓
    ┌─────────┐   ┌──────────┐   ┌───────────┐
    │ OBSERVE │ → │   ACT    │ → │  VERIFY   │
    └─────────┘   └──────────┘   └───────────┘
         │              │              │
         ↓              ↓              ↓
    - Context      - Plan         - Reflect
      projection     creation      on results
    - Memory        - Agent       - Should
      recall         execution     continue?
    - Classify     - Tools
```

### Observe Phase

```python
# _agentic_observe()
- Context projection from context ledger
- Memory recall from memory backend
- Unified classification of task
```

### Act Phase

```python
# _agentic_act()
- Delegate to `AgentLoop` (`packages/soothe/src/soothe/core/agent_loop/core/agent_loop.py`)
- Plan via `LLMPlanner` (`packages/soothe/src/soothe/core/agent_loop/core/planner.py`, RFC-604 two-phase assess + generate)
- Execute plan (single step or multi-step DAG via `packages/soothe/src/soothe/core/agent_loop/core/executor.py`)
```

### Verify Phase

```python
# _agentic_verify()
- Planner reflection on results
- Decision: continue to next iteration or complete
```

**Key files:**
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py` — Agentic loop
- `packages/soothe/src/soothe/core/runner/_runner_phases.py` — Phase helpers

## 5. Planning (AgentLoop + LLMPlanner)

Planning is implemented inside **AgentLoop**, not a separate `cognition/planning` package. **`LLMPlanner`** (`packages/soothe/src/soothe/core/agent_loop/core/planner.py`, RFC-604) performs:

1. **StatusAssessment** — structured `status`, `goal_progress`, `confidence`, `require_goal_completion`
2. **PlanGeneration** (when not `done`) — `plan_action`, `AgentDecision` steps, `next_action`

Routing (chitchat vs agentic vs subagent) happens earlier in **`SootheRunner`** / unified classification. Historical **AutoPlanner / SimplePlanner / ClaudePlanner** routers have been removed (IG-150 consolidation).

### Plan structure (conceptual)

`PlanResult` / `AgentDecision` still expose DAG-shaped work:

```python
class Plan(BaseModel):
    steps: list[PlanStep]

class PlanStep(BaseModel):
    id: str
    description: str
    execution_hint: str | None
    depends_on: list[str] = []  # DAG dependencies
```

**Key files:**
- `packages/soothe/src/soothe/core/agent_loop/core/planner.py` — `LLMPlanner`
- `packages/soothe/src/soothe/core/agent_loop/core/plan_phase.py` — Plan phase wiring
- `packages/soothe/src/soothe/core/prompts/builder.py` — `PromptBuilder` for assess/generate prompts

## 6. Step Execution (DAG-based)

For multi-step plans, execution follows DAG dependencies:

```
_run_step_loop()
    ↓
StepScheduler(plan)  →  Build DAG from depends_on
    ↓
┌─────────────────────────────────────┐
│           BATCH LOOP                │
└─────────────────────────────────────┘
    ↓
ready_steps = scheduler.ready_steps(limit, parallelism)
    ↓
┌────────────────┐
│ Single step?   │
└────────────────┘
    ↓           ↓
   YES         NO
    ↓           ↓
Sequential   asyncio.gather()
             (parallel execution)
    ↓
_execute_step()
    ↓
_stream_phase() → agent.astream()
    ↓
PlanStepCompletedEvent / PlanStepFailedEvent
```

### Parallel Execution

Steps with no dependencies run in parallel:

```
Step A (no deps) ─┬─→ Step C (depends on A, B)
Step B (no deps) ─┘

Execution: A + B parallel, then C
```

**Key files:**
- `packages/soothe/src/soothe/core/runner/_runner_steps.py` — Step orchestration (`StepScheduler` for DAG batches)
- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py` — `AgentDecision`, `StepAction`, dependency metadata

## 7. Agent Execution

### Stream Phase

The `_stream_phase()` runs the LangGraph compiled agent:

```python
# _stream_phase() in _runner_phases.py

async def _stream_phase(self, ...):
    # Build enriched input
    stream_input = {
        "messages": messages,
        "context_projection": context,
        "recalled_memories": memories,
    }

    # Stream from agent
    async for chunk in agent.astream(
        stream_input,
        stream_mode=["messages", "updates", "custom"],
        subgraphs=True
    ):
        # Handle HITL interrupts
        if is_interrupt(chunk):
            # Auto-approve or wait for human
            await handle_interrupt(chunk)

        yield chunk
```

### Event Types

| Mode | Content |
|------|---------|
| `messages` | AI messages, tool calls |
| `updates` | State updates |
| `custom` | Protocol events |

**Key files:**
- `packages/soothe/src/soothe/core/runner/_runner_phases.py` — Phase execution
- `packages/soothe/src/soothe/core/agent.py` — CoreAgent factory

## 8. Response Streaming

Events flow back to the client through the daemon:

```
agent.astream() yields (namespace, mode, data)
    ↓
Runner yields events
    ↓
Daemon._run_query() receives events
    ↓
_broadcast(event_msg)
    ↓
EventBus.publish(topic="thread:{thread_id}")
    ↓
Subscribed client sessions receive event
    ↓
Transport.send() to client
    ↓
CLI EventProcessor + Renderer
    ↓
Output to stdout/stderr
```

### Client Event Handling

```python
# In CLI/TUI
async for event in daemon_client.subscribe_thread(thread_id):
    match event["type"]:
        case "status":
            # idle, running, stopped
        case "event":
            namespace = event["namespace"]
            mode = event["mode"]
            data = event["data"]
            # Render based on event type
```

## 9. Autonomous Mode (RFC-200)

When `autonomous=True`, the system uses explicit goal-driven execution:

```
_run_autonomous()
    ↓
_goal_engine.create_goal(user_input)
    ↓
GoalCreatedEvent
    ↓
┌─────────────────────────────────────┐
│      GOAL EXECUTION LOOP            │
└─────────────────────────────────────┘
    ↓
ready_goals = goal_engine.ready_goals()
    ↓
_execute_autonomous_goal() per goal
    ↓
- Plan creation
- Step loop execution
- Reflection
- Goal directives processing
    ↓
GoalCompletedEvent / GoalFailedEvent
    ↓
FinalReportEvent
```

**Key files:**
- `packages/soothe/src/soothe/core/runner/_runner_autonomous.py`
- `packages/soothe/src/soothe/core/goal_engine/engine.py`

## 10. Event Flow Summary

```
User Query
    │
    ▼
┌─────────────┐
│ CLI Entry   │  main.py → run_impl()
└─────────────┘
    │
    ▼
┌─────────────┐
│ Daemon      │  Client → Server → _run_query()
└─────────────┘
    │
    ▼
┌─────────────┐
│ Runner      │  SootheRunner.astream()
└─────────────┘
    │
    ▼
┌─────────────┐
│ Classify    │  Unified routing (intent, complexity, workspace, …)
└─────────────┘
    │
    ▼
┌─────────────┐
│ Plan        │  `LLMPlanner` / AgentLoop Plan phase
└─────────────┘
    │
    ▼
┌─────────────┐
│ Execute     │  Single step or DAG parallel
└─────────────┘
    │
    ▼
┌─────────────┐
│ Stream      │  agent.astream() → events
└─────────────┘
    │
    ▼
┌─────────────┐
│ Respond     │  EventBus → Client → stdout
└─────────────┘
```

## Quick Reference

### Key files (quick reference)

| Area | File | Purpose |
|------|------|---------|
| CLI | `packages/soothe-cli/src/soothe_cli/cli/main.py` | Entry point |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/commands/run_cmd.py` | Run command |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/execution/headless.py` | Headless mode |
| Daemon | `packages/soothe/src/soothe/daemon/server.py` | Daemon server |
| Daemon | `packages/soothe/src/soothe/daemon/_handlers.py` | Query handling |
| Runner | `packages/soothe/src/soothe/core/runner/__init__.py` | Runner package |
| Runner | `packages/soothe/src/soothe/core/runner/_runner_agentic.py` | Agentic loop |
| Runner | `packages/soothe/src/soothe/core/runner/_runner_phases.py` | Phase execution |
| Runner | `packages/soothe/src/soothe/core/runner/_runner_steps.py` | Step orchestration |
| Planning | `packages/soothe/src/soothe/core/agent_loop/core/planner.py` | `LLMPlanner` (RFC-604) |
| Agent | `packages/soothe/src/soothe/core/agent.py` | CoreAgent factory |

### RFC References

- [RFC-201](../specs/RFC-201-agentloop-plan-execute-loop.md) — AgentLoop plan–execute (observe / act / verify)
- [RFC-200](../specs/RFC-200-autonomous-goal-management.md) — Autonomous goal management
- [RFC-604](../specs/RFC-604-reason-phase-robustness.md) — Two-phase plan assess and generation (`LLMPlanner`)
- [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) — Daemon communication