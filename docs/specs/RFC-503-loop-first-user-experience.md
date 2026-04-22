# Loop-First User Experience Architecture

> Design draft for user-facing loop-centric model with threads as internal implementation detail.
>
> **RFC Number**: RFC-503
> **Status**: Draft
> **Created**: 2026-04-22
> **Dependencies**: RFC-608 (Multi-Thread Lifecycle), RFC-450 (Daemon Communication), RFC-500 (CLI/TUI), RFC-454 (Slash Commands)
> **Author**: Claude Sonnet 4.6

---

## Abstract

This RFC defines the architectural shift from **thread-based user experience** to **loop-based user experience**. AgentLoop becomes the primary user-facing concept, while CoreAgent threads become internal implementation details invisible to users. This aligns with RFC-608's vision: loops span multiple threads, users interact with loops, threads are execution contexts managed internally.

---

## Motivation

### Current Problem

**Thread-centric user model** (current):
- CLI: `soothe --thread <thread_id> "query"`
- TUI: Thread selector dropdown
- Daemon: Thread-level WebSocket APIs, thread subscriptions
- User mental model: "I work with threads"

**Architectural mismatch**:
- RFC-608 defines loops as primary entity spanning threads
- Users see threads, but loops are the orchestrating entity
- Thread IDs exposed to users, but loop_id is internal
- Thread detachment keeps thread running, but loop context is lost

### Proposed Solution

**Loop-first user model**:
- CLI: `soothe --loop <loop_id> "query"` (or default: active loop)
- TUI: Loop selector dropdown
- Daemon: Loop-level WebSocket APIs, loop subscriptions
- User mental model: "I work with loops"
- Threads: Internal implementation detail (invisible to users)

**Key principle**: Users interact with loops. Threads are execution contexts managed by AgentLoop internally.

---

## Architectural Principle

### User Mental Model

**What users see**:
- **Loops**: Primary entity they create, manage, and interact with
- **Loop status**: `running`, `ready_for_next_goal`, `finalized`, `cancelled`
- **Loop goals**: Goals completed, goals in progress
- **Loop history**: Goal execution history across all threads

**What users don't see**:
- **Thread IDs**: Internal execution contexts
- **Thread switches**: Automatic (internal) when thread health degrades
- **Thread checkpoints**: Internal CoreAgent checkpoints
- **Thread lifecycle**: Managed internally by AgentLoop

**Example user interaction**:
```
User: "soothe loop list"
System: Shows loops (loop_abc123, loop_def456)

User: "soothe loop describe loop_abc123"
System: Shows loop details:
  - Status: ready_for_next_goal
  - Goals completed: 5
  - Threads: 3 (internal, shown for context)
  - Checkpoint tree: ...

User: "soothe --loop loop_abc123 translate to chinese"
System: Executes query on loop (thread managed internally)
```

---

## CLI Architecture

### Command Structure

**Parent command**: `soothe loop <subcommand>` (replaces `soothe thread <subcommand>`)

**Subcommands**:

| Command | Description | Replaces |
|---------|-------------|----------|
| `soothe loop list` | List all loops | `soothe thread list` |
| `soothe loop describe <loop_id>` | Show loop details | `soothe thread describe <thread_id>` |
| `soothe loop tree <loop_id>` | Visualize checkpoint tree | NEW |
| `soothe loop prune <loop_id>` | Prune old branches | NEW |
| `soothe loop delete <loop_id>` | Delete loop | `soothe thread delete <thread_id>` |
| `soothe loop switch <loop_id>` | Switch active loop | `soothe thread resume <thread_id>` |
| `soothe loop new` | Create new loop | NEW |
| `soothe loop status` | Quick status summary | NEW |

**Execution flags**:

| Flag | Description | Replaces |
|------|-------------|----------|
| `--loop <loop_id>` | Execute on specific loop | `--thread <thread_id>` |
| `--new-loop` | Create fresh loop for query | `--new-thread` (if existed) |
| `--loop-status` | Show loop status after execution | NEW |

**Default behavior**:
```bash
soothe "query"  # Uses active loop (or creates new loop if none active)
soothe --loop loop_abc123 "query"  # Execute on specific loop
soothe --new-loop "query"  # Create fresh loop for query
```

---

## TUI Architecture

### UI Components

**Welcome banner** (loop-based):
```
╭─────────────────────────────────────────────────────────────────╮
│  Welcome to Soothe                                              │
│                                                                 │
│  Active Loop: loop_abc123                                       │
│  Status: ready_for_next_goal                                    │
│  Goals: 5 completed, 1 in progress                              │
│  Threads: 3 (internal)                                          │
│                                                                 │
│  Commands:                                                      │
│    Ctrl+N - New loop          Ctrl+L - Switch loop              │
│    Ctrl+D - Detach loop       Ctrl+Q - Quit                     │
╰─────────────────────────────────────────────────────────────────╯
```

**Status bar** (loop-based):
```
Loop: loop_abc123 [ready_for_next_goal] | Goals: 5 | Threads: 3 (internal) | Tokens: 125K | Duration: 3h 15m
```

**Loop selector modal** (replaces thread selector):
```
Select Loop:
  ○ loop_abc123  (active, 5 goals, 3 threads)  ← Enter to select
  ○ loop_def456  (running, 3 goals, 2 threads)
  ○ loop_ghi789  (finalized, 10 goals, 5 threads)
  
  [Ctrl+N] Create new loop
```

**Loop history cards** (replaces thread cards):
```
Loop: loop_abc123
  Created: 2026-04-22 10:30
  Goals: 5 completed, 1 in progress
  
  Goal 1: "analyze project structure" ✓
    Duration: 45s
    Threads: 1 (started on thread_001)
  
  Goal 2: "optimize database queries" ✓
    Duration: 2m 30s
    Threads: 2 (thread switch after iteration 3)
  
  Goal 3: "translate to chinese" ✓
    Duration: 1m 15s
    Threads: 3 (thread switch for fresh context)
  
  Goal 4: "write unit tests" ✓
    Duration: 5m 20s
    Threads: 3 (continued on thread_003)
  
  Goal 5: "generate documentation" ⏳ (in progress)
    Threads: 3 (current thread_003)
```

**Thread switch notification** (internal, minimal disclosure):
```
[Info] Thread context refreshed for better performance (internal thread management)
```

Note: No thread ID shown. Users see "context refreshed" without internal details.

---

## Daemon WebSocket Protocol

### Removed Thread-Level APIs

**Deprecated APIs** (removed from daemon):

```json
// REMOVED: Thread lifecycle APIs
{"type": "command_request", "command": "thread_list"}  // ❌ Remove
{"type": "command_request", "command": "thread_describe", "thread_id": "..."}  // ❌ Remove
{"type": "command_request", "command": "thread_delete", "thread_id": "..."}  // ❌ Remove
{"type": "command_request", "command": "thread_resume", "thread_id": "..."}  // ❌ Remove

// REMOVED: Thread subscription APIs
{"type": "subscribe", "thread_id": "..."}  // ❌ Remove
{"type": "unsubscribe", "thread_id": "..."}  // ❌ Remove

// REMOVED: Thread-scoped input
{"type": "input", "thread_id": "...", "content": "..."}  // ❌ Remove
```

---

### New Loop-Level APIs

**Loop lifecycle APIs**:

```json
// NEW: List loops
{
  "type": "command_request",
  "command": "loop_list",
  "params": {
    "status": "running",  // Optional filter
    "limit": 20
  }
}

// Response:
{
  "type": "command_response",
  "command": "loop_list",
  "data": {
    "loops": [
      {
        "loop_id": "loop_abc123",
        "status": "ready_for_next_goal",
        "threads": 3,  // Internal count (shown for context)
        "goals": 5,
        "created_at": "2026-04-22T10:30:00Z"
      }
    ]
  }
}

// NEW: Describe loop
{
  "type": "command_request",
  "command": "loop_describe",
  "params": {
    "loop_id": "loop_abc123",
    "verbose": true
  }
}

// Response includes:
{
  "type": "command_response",
  "command": "loop_describe",
  "data": {
    "loop_id": "loop_abc123",
    "thread_ids": ["thread_001", "thread_002", "thread_003"],  // Internal IDs (for debugging)
    "checkpoint_tree": {...}
  }
}

// NEW: Subscribe to loop (replaces thread subscription)
{
  "type": "subscribe",
  "loop_id": "loop_abc123"
}

// NEW: Loop-scoped input (replaces thread input)
{
  "type": "input",
  "loop_id": "loop_abc123",
  "content": "translate to chinese"
}

// NEW: Detach loop (replaces thread detach)
{
  "type": "command_request",
  "command": "detach",
  "params": {
    "loop_id": "loop_abc123"
  }
}
```

---

### Event Routing Changes

**Old routing** (thread-based) - removed:
```python
# REMOVED: Thread-scoped event topics
topic = f"thread:{thread_id}"  # ❌ Remove
await event_bus.publish(topic, event)
```

**New routing** (loop-based):
```python
# NEW: Loop-scoped event topics
topic = f"loop:{loop_id}"  # ✅ Add
await event_bus.publish(topic, event)

# Thread events are internal (not routed to clients)
# Only loop-level events are client-visible
```

**Client-visible events** (loop-level):
```python
# Loop lifecycle events (NEW)
LOOP_CREATED = "soothe.lifecycle.loop.created"
LOOP_STARTED = "soothe.lifecycle.loop.started"
LOOP_DETACHED = "soothe.lifecycle.loop.detached"
LOOP_REATTACHED = "soothe.lifecycle.loop.reattached"
LOOP_COMPLETED = "soothe.lifecycle.loop.completed"

# Goal events (existing, loop-scoped)
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
GOAL_FAILED = "soothe.cognition.goal.failed"

# Branch events (NEW)
BRANCH_CREATED = "soothe.cognition.branch.created"
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"

# AgentLoop events (existing)
AGENT_LOOP_STARTED = "soothe.cognition.agent_loop.started"
AGENT_LOOP_COMPLETED = "soothe.cognition.agent_loop.completed"
```

**Internal events** (not client-visible):
```python
# Thread lifecycle (internal only)
THREAD_CREATED = "soothe.lifecycle.thread.started"  # Internal
THREAD_SWITCHED = "soothe.lifecycle.thread.switched"  # Internal (NEW)
THREAD_HEALTH_UPDATED = "soothe.lifecycle.thread.health.updated"  # Internal (NEW)

# Checkpoint anchors (internal)
CHECKPOINT_ANCHOR_CREATED = "soothe.lifecycle.checkpoint.anchor.created"  # Internal
```

---

## Slash Commands

### Removed Thread-Level Commands

**Deprecated commands** (removed from slash command registry):
```python
/thread list  # ❌ Remove
/thread describe <thread_id>  # ❌ Remove
/thread delete <thread_id>  # ❌ Remove
/thread resume <thread_id>  # ❌ Remove
```

---

### New Loop-Level Commands

**New commands** (added to slash command registry):
```python
/loop list  # REPLACES /thread list
/loop describe [loop_id]  # REPLACES /thread describe
/loop tree [loop_id]  # NEW: visualize checkpoint tree
/loop prune [loop_id]  # NEW: cleanup old branches
/loop switch <loop_id>  # REPLACES /thread resume
/loop new  # NEW: create fresh loop
/loop status  # NEW: quick status summary

# Existing commands (loop-scoped)
/cancel  # Loop-scoped (cancel loop execution)
/clear  # Loop-scoped (clear current thread internally)
/history  # Loop-scoped (show goal history)
/memory  # Loop-scoped
/config  # Loop-scoped
```

**Command routing** (RFC-454 Category 2):

| Command | Daemon Command | Params |
|---------|---------------|--------|
| `/loop list` | `loop_list` | `status`, `limit` |
| `/loop describe` | `loop_describe` | `loop_id` |
| `/loop tree` | `loop_tree` | `loop_id`, `format` |
| `/loop prune` | `loop_prune` | `loop_id`, `retention_days` |
| `/loop switch` | `loop_switch` | `loop_id` |
| `/loop new` | `loop_new` | None |
| `/loop status` | `loop_status` | `loop_id` |
| `/detach` | `detach` | `loop_id` |
| `/cancel` | `cancel` | `loop_id` |
| `/clear` | `clear` | `loop_id` |
| `/history` | `history` | `loop_id` |

---

## SootheRunner Refactoring

### Loop-Scoped Execution

**Old SootheRunner** (thread-scoped) - removed:
```python
# REMOVED: Thread-scoped runner
class SootheRunner:
    def __init__(self, thread_id: str):  # ❌ Remove thread_id
        self.thread_id = thread_id
```

**New SootheRunner** (loop-scoped):
```python
# NEW: Loop-scoped runner
class SootheRunner:
    def __init__(self, loop_id: str | None = None):  # ✅ Add loop_id
        self.loop_id = loop_id or self._generate_loop_id()
        self.loop_manager = AgentLoopManager(self.loop_id)
        self.thread_manager = ThreadManager()  # Internal
    
    async def run(self, query: str):
        """Run query on loop (manages threads internally)."""
        
        # Load loop checkpoint
        loop_checkpoint = await self.loop_manager.load_or_create()
        
        # Evaluate thread switch policy (internal)
        if self._should_switch_thread(loop_checkpoint):
            # Internal thread switch (invisible to user)
            new_thread_id = await self.thread_manager.create_thread()
            loop_checkpoint.thread_ids.append(new_thread_id)
            loop_checkpoint.current_thread_id = new_thread_id
            await self.loop_manager.save(loop_checkpoint)
        
        # Execute on current thread (internal)
        current_thread_id = loop_checkpoint.current_thread_id
        core_agent = await self._create_core_agent(current_thread_id)
        
        # Run with AgentLoop orchestration
        agentloop = AgentLoop(self.loop_id, loop_checkpoint)
        result = await agentloop.run_with_progress(
            core_agent=core_agent,
            query=query,
            thread_id=current_thread_id,  # Internal parameter
        )
        
        # Update loop checkpoint
        loop_checkpoint = await agentloop.finalize()
        await self.loop_manager.save(loop_checkpoint)
        
        return result
```

---

## Client Session Management

### Loop-Scoped Sessions

**Old session** (thread-based) - removed:
```python
# REMOVED: Thread-scoped session
class ClientSession:
    thread_id: str  # ❌ Remove
    thread_subscriptions: set[str]  # ❌ Remove
```

**New session** (loop-based):
```python
# NEW: Loop-scoped session
class ClientSession:
    loop_id: str  # ✅ Add (primary user-facing identifier)
    loop_subscription: str | None  # ✅ Single loop subscription
    
    # Internal thread tracking (for cleanup)
    internal_thread_ids: set[str]  # Internal: threads owned by this loop
```

**Session lifecycle**:
```python
async def handle_loop_subscribe(client_id: str, loop_id: str):
    """Subscribe client to loop (replaces thread subscribe)."""
    
    session = session_manager.get_session(client_id)
    
    # Unsubscribe from old loop
    if session.loop_subscription:
        await event_bus.unsubscribe(session.loop_subscription, session.event_queue)
    
    # Subscribe to new loop
    topic = f"loop:{loop_id}"
    await event_bus.subscribe(topic, session.event_queue)
    
    # Update session
    session.loop_id = loop_id
    session.loop_subscription = topic
    
    # Reconstruct history (for TUI reattachment)
    loop_checkpoint = await loop_manager.load(loop_id)
    event_stream = reconstruct_event_stream(loop_checkpoint)
    
    # Send history replay
    await session.send_event({
        "type": "history_replay",
        "loop_id": loop_id,
        "events": event_stream,
    })
```

---

## Detachment Behavior

### Loop Detachment

**Old detachment** (thread-based) - removed:
```python
# REMOVED: Thread detachment
/detach thread_001  # ❌ Remove

# Behavior: Thread continues running, client unsubscribes from thread
```

**New detachment** (loop-based):
```python
# NEW: Loop detachment
/detach loop_abc123  # ✅ Add (or default: active loop)

# Behavior:
# - Loop continues running (all threads continue)
# - Client unsubscribes from loop (not individual threads)
# - Loop checkpoint saved at detachment point
# - On reattachment: reconstruct full history from loop checkpoint
```

**Reattachment workflow**:
```python
# Client reattaches to detached loop
await handle_loop_subscribe(client_id, loop_abc123)

# Daemon reconstructs history:
# 1. Load AgentLoop checkpoint (loop_abc123)
# 2. Load checkpoint tree (main_line + failed_branches)
# 3. Load CoreAgent checkpoints (internal)
# 4. Reconstruct event stream (goal history + checkpoint anchors)
# 5. Send history replay to client
# 6. Send current loop status
```

---

## Implementation Tasks

### Phase 1: CLI Refactoring
- Replace `soothe thread` → `soothe loop` commands
- Replace `--thread` → `--loop` flag
- Add new loop commands: `tree`, `prune`, `switch`, `new`, `status`
- Update default execution behavior (active loop)

### Phase 2: TUI Refactoring
- Replace thread selector → loop selector
- Replace thread status bar → loop status bar
- Replace thread history cards → loop history cards
- Update thread switch notification (internal disclosure)
- Update welcome banner (loop-based)

### Phase 3: Daemon Protocol Refactoring
- Remove thread-level WebSocket APIs
- Add loop-level WebSocket APIs
- Replace thread subscriptions → loop subscriptions
- Replace thread input → loop input
- Update event routing (thread topics → loop topics)

### Phase 4: Slash Commands Refactoring
- Remove `/thread` commands
- Add `/loop` commands
- Update existing commands to loop-scoped

### Phase 5: SootheRunner Refactoring
- Replace thread-scoped → loop-scoped execution
- Add loop_manager (primary)
- Keep thread_manager (internal)
- Update thread switch logic (internal decision)

### Phase 6: Session Management Refactoring
- Replace thread sessions → loop sessions
- Update subscription logic (loop topics)
- Update reattachment workflow (loop checkpoint reconstruction)

---

## Success Criteria

1. Users interact with loops (not threads) ✓
2. CLI commands are loop-based ✓
3. TUI displays loops (threads hidden) ✓
4. Daemon APIs are loop-level ✓
5. Slash commands are loop-scoped ✓
6. SootheRunner is loop-scoped ✓
7. Client sessions are loop-scoped ✓
8. Thread IDs are internal (not user-facing) ✓
9. Thread switches are invisible to users ✓
10. History reconstruction is loop-based ✓

---

## Related Specifications

- RFC-608: AgentLoop Multi-Thread Lifecycle
- RFC-450: Daemon Communication Protocol
- RFC-500: CLI/TUI Architecture
- RFC-454: Slash Command Architecture
- RFC-409: AgentLoop Persistence Backend
- RFC-411: Event Stream Replay

---

**End of RFC-612 Draft**