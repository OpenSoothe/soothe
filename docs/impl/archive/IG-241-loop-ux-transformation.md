# Loop UX Transformation Implementation

> Implementation guide for loop-first user experience transformation (RFC-503 + RFC-504).
>
> **RFCs**: RFC-503 (Loop-First UX), RFC-504 (Loop Management CLI)
> **Dependencies**: IG-239 (Persistence), IG-240 (Checkpoint Tree)
> **Language**: Python 3.11+

---

## 1. Overview

Transform user experience from **thread-based** to **loop-based**. Remove thread-level CLI/TUI/Daemon APIs, add loop-level APIs. Users interact with loops, threads become internal.

## 2. CLI Commands Implementation

### 2.1 Create Loop Commands

**Location**: `packages/soothe-cli/src/soothe_cli/loop_commands.py`

Commands to implement:
- `soothe loop list [--status] [--limit]` - List loops
- `soothe loop describe <loop_id> [--verbose]` - Show loop details
- `soothe loop tree <loop_id> [--format ascii|json|dot]` - Visualize checkpoint tree
- `soothe loop prune <loop_id> [--retention-days] [--dry-run]` - Prune old branches
- `soothe loop delete <loop_id> [--force]` - Delete loop

Replace thread commands: `soothe thread` → `soothe loop`

### 2.2 Register Commands

**Location**: `packages/soothe-cli/src/soothe_cli/main.py`

```python
loop_app = typer.Typer(help="Manage AgentLoop instances")
app.add_typer(loop_app, name="loop")

loop_app.command("list")(list_loops)
loop_app.command("describe")(describe_loop)
loop_app.command("tree")(visualize_loop_tree)
loop_app.command("prune")(prune_loop_branches)
loop_app.command("delete")(delete_loop)
```

---

## 3. Daemon WebSocket Protocol Changes

### 3.1 Remove Thread APIs

**Remove from** `packages/soothe/src/soothe/daemon/websocket_handler.py`:
- Thread lifecycle commands: `thread_list`, `thread_describe`, `thread_delete`
- Thread subscriptions: `subscribe(thread_id)`, `unsubscribe(thread_id)`
- Thread-scoped input: `{"thread_id": "...", "content": "..."}`

### 3.2 Add Loop APIs

**Add to** `packages/soothe/src/soothe/daemon/websocket_handler.py`:
- Loop commands: `loop_list`, `loop_describe`, `loop_tree`, `loop_prune`, `loop_delete`
- Loop subscriptions: `subscribe(loop_id)`, `unsubscribe(loop_id)`
- Loop-scoped input: `{"loop_id": "...", "content": "..."}`

### 3.3 Update Event Routing

**Change** `packages/soothe/src/soothe/daemon/event_bus.py`:

```python
# OLD: thread-based topics
topic = f"thread:{thread_id}"  # ❌ Remove

# NEW: loop-based topics
topic = f"loop:{loop_id}"  # ✅ Add
```

---

## 4. TUI Refactoring

### 4.1 Replace Thread Selector

**Location**: `packages/soothe-cli/src/soothe_cli/tui/screens/loop_selector.py`

Replace thread dropdown with loop selector showing:
- Loop ID, Status, Goals completed, Threads (internal count)

### 4.2 Update Status Bar

**Location**: `packages/soothe-cli/src/soothe_cli/tui/widgets/status.py`

Replace:
```
Thread: thread_001 [running]  ❌
```

With:
```
Loop: loop_abc123 [ready_for_next_goal] | Goals: 5 | Threads: 3 (internal)  ✅
```

### 4.3 Thread Switch Notification

Change from:
```
Switched from thread_001 to thread_002  ❌
```

To:
```
Thread context refreshed (internal management)  ✅
```

---

## 5. Slash Commands Refactoring

### 5.1 Update Command Registry

**Location**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

Remove:
- `/thread list`, `/thread describe`, `/thread delete`, `/thread resume`

Add:
- `/loop list`, `/loop describe`, `/loop tree`, `/loop prune`, `/loop switch`, `/loop new`

---

## 6. SootheRunner Refactoring

### 6.1 Loop-Scoped Execution

**Location**: `packages/soothe/src/soothe/core/runner/__init__.py`

```python
class SootheRunner:
    def __init__(self, loop_id: str | None = None):  # ✅ Add loop_id
        self.loop_id = loop_id or self._generate_loop_id()
        self.loop_manager = AgentLoopManager(self.loop_id)
        self.thread_manager = ThreadManager()  # Internal
```

---

## 7. Client Session Management

### 7.1 Loop-Scoped Sessions

**Location**: `packages/soothe/src/soothe/daemon/client_session.py`

```python
class ClientSession:
    loop_id: str  # ✅ Add (primary)
    loop_subscription: str | None  # ✅ Add
    internal_thread_ids: set[str]  # Internal tracking
```

---

## 8. Testing

```bash
# CLI commands
soothe loop list
soothe loop describe test_loop
soothe loop tree test_loop --format ascii

# TUI verification
soothe "query" --tui  # Verify loop selector shows loops, not threads
```

---

## 9. Files to Modify

- `packages/soothe-cli/src/soothe_cli/main.py` (add loop commands)
- `packages/soothe/src/soothe/daemon/websocket_handler.py` (remove thread APIs, add loop APIs)
- `packages/soothe/src/soothe/daemon/event_bus.py` (change event routing)
- `packages/soothe-cli/src/soothe_cli/tui/widgets/status.py` (update status bar)
- `packages/soothe/src/soothe/core/runner/__init__.py` (loop-scoped execution)

---

**End of Phase 3 Implementation Guide (IG-241)**

