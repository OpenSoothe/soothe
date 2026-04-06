# RFC-103: Thread-Aware Workspace

**RFC Number**: RFC-103
**Kind**: Implementation Interface Design
**Status**: Draft
**Created**: 2026-03-31
**Author**: Design brainstorming session
**Design Draft**: [2026-03-31-thread-aware-workspace-design.md](../drafts/2026-03-31-thread-aware-workspace-design.md)
**Depends On**: RFC-102 (Security Filesystem Policy), RFC-400 (Daemon Communication), RFC-402 (Thread Management)

## Abstract

This RFC proposes a thread-aware workspace system that enables WebSocket clients connecting from different project directories to have their file operations resolve against their specific workspace, rather than the daemon's startup workspace. The design uses Python's `ContextVar` for async-safe thread isolation and flows workspace through `RunnableConfig.configurable` without requiring tool signature changes.

## Motivation

### Problem: Workspace Ignored at Execution

WebSocket clients send their current working directory (cwd) in `new_thread` and `resume_thread` messages. The daemon validates and stores this workspace in `_thread_workspaces[thread_id]`, but the value is never passed to tool execution.

**Current flow (broken)**:
```
Client connects from /project-a → sends workspace: "/project-a"
Daemon stores _thread_workspaces["thread-123"] = "/project-a"
User sends query "read config.yml"
Tool executes → uses daemon's startup workspace "/default-workspace"
File not found at /default-workspace/config.yml (wrong path)
```

**Expected flow**:
```
Client connects from /project-a → sends workspace: "/project-a"
Daemon stores _thread_workspaces["thread-123"] = "/project-a"
User sends query "read config.yml"
Tool executes → uses thread's workspace "/project-a"
File read from /project-a/config.yml (correct path)
```

### Design Goals

1. **Per-thread workspace isolation**: Each thread's tools operate in its designated workspace
2. **Async-safe**: Multiple concurrent threads with different workspaces must not interfere
3. **Minimal code changes**: No tool signature modifications required
4. **Backward compatible**: Existing behavior preserved when workspace not specified
5. **Transparent to tools**: Workspace resolution happens at backend layer

### Non-Goals

- **Mid-thread workspace switching**: Workspace is stable within a thread
- **Workspace from tool output**: Dynamic discovery not in scope
- **Multi-project single thread**: One workspace per thread

## Guiding Principles

### Principle 1: ContextVar for Async Safety

Python's `contextvars.ContextVar` provides async-safe context isolation. Each async task (thread execution) has its own context, preventing cross-thread contamination.

### Principle 2: Flow Through RunnableConfig

Workspace flows through LangGraph's standard mechanism: `RunnableConfig.configurable`. Middleware extracts and sets context at stream start.

### Principle 3: Singleton with Dynamic Root

`FrameworkFilesystem` remains a singleton but reads workspace dynamically from ContextVar, falling back to daemon default when unset.

### Principle 4: Fallback Safety

When ContextVar is empty (direct tool use, tests), tools fall back to their baked-in `work_dir`, preserving existing behavior.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Client Request                                                 │
│  websocket: {"type": "new_thread", "workspace": "/path/to/proj"}│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Daemon Handler (_handlers.py)                                  │
│  - Validates workspace via validate_client_workspace()          │
│  - Stores in _thread_workspaces[thread_id]                      │
│  - Passes to runner via stream_kwargs["workspace"]              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SootheRunner.astream(text, workspace="/path/to/proj")          │
│  - Builds RunnableConfig: configurable["workspace"] = workspace │
│  - Calls agent.astream(input, config)                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  WorkspaceContextMiddleware (new)                               │
│  - process_agent_input(): sets ContextVar                       │
│  - _current_workspace.set(workspace)                            │
│  - Mirrors workspace in state["workspace"]                      │
│  - process_agent_output(): clears ContextVar                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FrameworkFilesystem (modified)                                 │
│  - get_current_workspace(): reads ContextVar                    │
│  - resolve_path(path): uses current workspace if set            │
│  - Falls back to _root_dir (daemon default) if ContextVar empty │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool Execution                                                 │
│  - _resolve_path() calls FrameworkFilesystem.resolve_path()     │
│  - Path resolved against current thread's workspace             │
│  - self.work_dir becomes fallback/default only                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow Sequence

1. **Client connects** from `/home/user/project-a`
2. **Client sends `new_thread`** with `workspace: "/home/user/project-a"`
3. **Daemon validates** via `validate_client_workspace()`, stores in `_thread_workspaces["thread-123"]`
4. **User sends query** "read the config file"
5. **Daemon passes** `runner.astream("read the config file", thread_id="thread-123", workspace="/home/user/project-a")`
6. **Runner builds** `RunnableConfig: {"configurable": {"thread_id": "thread-123", "workspace": "/home/user/project-a"}}`
7. **WorkspaceContextMiddleware** sets `_current_workspace` to `/home/user/project-a`
8. **Agent processes** query, decides to call `read_file` tool
9. **Tool executes** `_resolve_path("config.yml")` → `FrameworkFilesystem.resolve_path()` → `/home/user/project-a/config.yml`
10. **Stream ends** → middleware clears `_current_workspace`

## Specification

### 1. ContextVar Definition

**Location**: `src/soothe/safety/filesystem.py`

```python
from contextvars import ContextVar
from pathlib import Path

# Thread-safe workspace context for async execution
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)
```

### 2. FrameworkFilesystem Modifications

**Location**: `src/soothe/safety/filesystem.py`

Add methods to the singleton class:

```python
@classmethod
def set_current_workspace(cls, workspace: Path | str) -> None:
    """Set workspace for current async context.

    Args:
        workspace: Workspace path (Path or str).
    """
    _current_workspace.set(Path(workspace) if isinstance(workspace, str) else workspace)

@classmethod
def get_current_workspace(cls) -> Path | None:
    """Get workspace for current async context.

    Returns:
        Current workspace Path, or None if not set.
    """
    return _current_workspace.get()

@classmethod
def resolve_path_dynamic(cls, file_path: str) -> Path:
    """Resolve file path against current workspace or fallback.

    Resolution order:
    1. If ContextVar has workspace, resolve against it
    2. Else use cls._root_dir (daemon default)
    3. Apply existing path resolution logic (relative/absolute handling)

    Args:
        file_path: File path to resolve.

    Returns:
        Resolved absolute path.
    """
    workspace = cls.get_current_workspace() or cls._root_dir
    # Apply existing resolution logic with dynamic workspace
    path = Path(file_path)
    if path.is_absolute():
        return path
    return workspace / file_path
```

### 3. WorkspaceContextMiddleware (New)

**Location**: `src/soothe/core/agent/middleware/workspace_context.py`

```python
from langchain.agents.middleware import AgentMiddleware
from soothe.safety import FrameworkFilesystem

class WorkspaceContextMiddleware(AgentMiddleware):
    """Set workspace context for tool execution.

    Reads workspace from config.configurable and:
    - Sets ContextVar for FrameworkFilesystem access
    - Mirrors in state for explicit tool access

    Ensures ContextVar is cleared on stream completion to prevent
    context leaks across stream boundaries.
    """

    async def process_agent_input(
        self,
        state: AgentState,
        config: RunnableConfig,
    ) -> None:
        """Set workspace context at stream start.

        Args:
            state: Agent state (will be modified).
            config: Runnable config with workspace in configurable.
        """
        workspace = config.get("configurable", {}).get("workspace")
        if workspace:
            FrameworkFilesystem.set_current_workspace(workspace)
            state["workspace"] = workspace  # Mirror in state

    async def process_agent_output(
        self,
        state: AgentState,
        config: RunnableConfig,
    ) -> None:
        """Clear workspace context at stream end.

        Args:
            state: Agent state.
            config: Runnable config.
        """
        FrameworkFilesystem.set_current_workspace(None)
```

### 4. SootheRunner Changes

**Location**: `src/soothe/core/runner/_runner_phases.py`

Modify `astream()` signature to accept workspace parameter:

```python
async def astream(
    self,
    text: str,
    thread_id: str | None = None,
    workspace: str | None = None,  # NEW: Thread-specific workspace
    autonomous: bool = False,
    max_iterations: int | None = None,
    **kwargs: Any,
) -> AsyncGenerator[StreamChunk, None]:
    """Stream agent response with optional thread-specific workspace.

    Args:
        text: User input text.
        thread_id: Thread ID for checkpointing.
        workspace: Thread-specific workspace path.
        autonomous: Enable autonomous iteration mode.
        max_iterations: Maximum iterations for autonomous mode.
        **kwargs: Additional parameters.

    Yields:
        StreamChunk tuples (namespace, mode, data).
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    if workspace:
        config["configurable"]["workspace"] = workspace
    # ... rest of implementation
```

### 5. Daemon Handler Changes

**Location**: `src/soothe/daemon/_handlers.py`

Pass stored workspace to runner when executing queries:

```python
# Around line 800 in handle_client_message()
thread_workspace = self._thread_workspaces.get(thread_id, self._daemon_workspace)

async for chunk in self._runner.astream(
    text,
    thread_id=thread_id,
    workspace=str(thread_workspace),
    autonomous=autonomous,
    max_iterations=max_iterations,
):
    # Process chunk...
```

### 6. Tool Path Resolution Changes

**Location**: `src/soothe/tools/file_ops/implementation.py`, similar changes in `execution/`, `code_edit/`

Modify `_resolve_path()` to use dynamic workspace:

```python
def _resolve_path(self, file_path: str) -> Path:
    """Resolve file path against current workspace.

    Resolution order:
    1. Dynamic workspace from ContextVar (if set)
    2. Fallback to self.work_dir (existing behavior)

    Args:
        file_path: File path to resolve.

    Returns:
        Resolved absolute path.
    """
    from soothe.safety import FrameworkFilesystem

    current_ws = FrameworkFilesystem.get_current_workspace()
    if current_ws:
        return FrameworkFilesystem.resolve_path_dynamic(file_path)

    # Fallback: existing behavior using self.work_dir
    return self._resolve_path_static(file_path)
```

The `work_dir` field remains on tool classes for backward compatibility.

### 7. Agent Factory Changes

**Location**: `src/soothe/core/agent.py`

Register WorkspaceContextMiddleware in the middleware stack:

```python
# After ExecutionHintsMiddleware (line ~471)
from soothe.core.agent.middleware import WorkspaceContextMiddleware
default_middleware.append(WorkspaceContextMiddleware())
logger.debug("[Init] Workspace context middleware enabled")
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No workspace in request | Falls back to daemon's `_daemon_workspace` |
| Invalid workspace path | Validated before storage, rejected with error |
| Workspace outside allowed paths | Policy middleware denies (existing behavior) |
| Absolute path in tool arg | If inside workspace: allowed. Outside: policy check |
| Multiple concurrent threads | ContextVar provides async context isolation |
| Thread resumed after restart | Workspace persisted with thread, restored on load |
| Direct tool instantiation | Falls back to `work_dir` (existing behavior) |

## Security Model

The existing security model (RFC-102) remains intact:

1. **Workspace validation** at entry (`validate_client_workspace()` blocks system directories)
2. **Policy middleware** checks operations against workspace boundaries
3. **virtual_mode** in FilesystemBackend sandboxed paths when `allow_paths_outside_workspace=False`

ContextVar adds:
- Async-safe isolation (no cross-thread contamination)
- Workspace cannot be spoofed mid-execution (set once per stream by middleware)

## Implementation Requirements

### File Structure

```
src/soothe/
├── safety/
│   └── filesystem.py              # MODIFY: Add ContextVar + methods
├── middleware/
│   └── workspace_context.py       # NEW: WorkspaceContextMiddleware
├── core/
│   ├── agent.py                   # MODIFY: Register middleware
│   └── runner/
│       └── _runner_phases.py      # MODIFY: astream workspace param
├── daemon/
│   └── _handlers.py               # MODIFY: Pass workspace to runner
└── tools/
    ├── file_ops/
    │   └── implementation.py      # MODIFY: _resolve_path
    ├── execution/
    │   └── implementation.py      # MODIFY: workspace_root handling
    └── code_edit/
        └── implementation.py      # MODIFY: work_dir handling
```

### Test Coverage

1. **ContextVar Tests**:
   - Set/get/clear lifecycle
   - Async context isolation
   - Concurrent task isolation

2. **FrameworkFilesystem Tests**:
   - Path resolution with ContextVar set
   - Path resolution without ContextVar (fallback)
   - Dynamic workspace switching

3. **Middleware Tests**:
   - Workspace extraction from configurable
   - State mirroring
   - ContextVar cleanup on stream end

4. **Integration Tests**:
   - Two threads with different workspaces, concurrent execution
   - File operations in thread A don't leak to thread B
   - Workspace persists across multiple astream calls in same thread
   - Full daemon → tool flow

## Migration Path

1. **Phase 1**: Add ContextVar and FrameworkFilesystem methods (backward compatible)
2. **Phase 2**: Create WorkspaceContextMiddleware and register in agent factory
3. **Phase 3**: Modify SootheRunner to accept workspace parameter
4. **Phase 4**: Update daemon handler to pass workspace
5. **Phase 5**: Update tool `_resolve_path` methods
6. **Phase 6**: Add comprehensive tests

All phases are backward compatible. Existing behavior preserved when workspace not specified.

## Success Criteria

- [ ] WebSocket client workspace correctly passed to tools
- [ ] Concurrent threads with different workspaces operate in isolation
- [ ] Fallback to daemon default when no workspace specified
- [ ] ContextVar properly cleared after stream completion
- [ ] All existing tests continue to pass
- [ ] New test coverage for thread workspace isolation

## Open Questions

None. All decisions finalized through design brainstorming session.

## References

- Design Draft: [2026-03-31-thread-aware-workspace-design.md](../drafts/2026-03-31-thread-aware-workspace-design.md)
- RFC-102: Secure Filesystem Path Handling
- RFC-400: Daemon Communication Protocol
- RFC-402: Unified Thread Management
- Python `contextvars` documentation
- LangGraph `RunnableConfig.configurable` pattern

---

*This RFC enables per-thread workspace isolation while maintaining backward compatibility with existing systems.*