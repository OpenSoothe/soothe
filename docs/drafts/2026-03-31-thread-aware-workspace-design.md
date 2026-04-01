# Thread-Aware Workspace Design

**Date:** 2026-03-31
**Status:** Draft
**Author:** Design brainstorming session

## Problem Statement

WebSocket clients connect from different project directories (their cwd), but the daemon's tools use the workspace baked into the agent at startup time. The daemon already stores per-thread workspace in `_thread_workspaces[thread_id]`, but this value is never passed to tool execution.

**Scenario:** Thread-per-workspace. Workspace is stable within a thread, but different threads may have different workspaces. Clients expect tools to operate on their current project directory.

## Design Overview

Add workspace plumbing that flows thread-specific workspace from daemon to tools via `ContextVar` and `RunnableConfig.configurable`, without requiring tool implementation changes.

### Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Workspace switching layer | Tool level + FilesystemBackend | Both layers need workspace awareness |
| LangGraph mechanism | `configurable` + state mirror | Middleware reads configurable, tools can read state |
| Tool access pattern | InjectedToolArg (implicit) | Tools don't need signature changes |
| Backend integration | ContextVar | Async-safe, Python-native, minimal intrusion |

## Architecture

### Flow Diagram

```
Client Request (workspace: /path/to/proj)
    │
    ▼
Daemon Handler
    │ validates workspace
    │ stores in _thread_workspaces[thread_id]
    │ passes to runner.astream(workspace=...)
    ▼
SootheRunner
    │ builds RunnableConfig with configurable["workspace"]
    ▼
WorkspaceContextMiddleware (new)
    │ sets ContextVar from configurable
    │ mirrors workspace in state
    ▼
FrameworkFilesystem (modified)
    │ resolve_path() reads ContextVar
    │ returns path resolved against current workspace
    ▼
Tool Execution
    │ _resolve_path() calls FrameworkFilesystem
    │ file operations use correct workspace
```

### Components

#### 1. ContextVar Definition

**Location:** `src/soothe/safety/filesystem.py`

```python
from contextvars import ContextVar
from pathlib import Path

# Thread-safe workspace context for async execution
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)
```

#### 2. FrameworkFilesystem Modifications

**Location:** `src/soothe/safety/filesystem.py`

Add methods to the singleton class:

```python
@classmethod
def set_current_workspace(cls, workspace: Path | str) -> None:
    """Set workspace for current async context."""
    _current_workspace.set(Path(workspace) if isinstance(workspace, str) else workspace)

@classmethod
def get_current_workspace(cls) -> Path | None:
    """Get workspace for current async context."""
    return _current_workspace.get()

@classmethod
def resolve_path(cls, file_path: str) -> Path:
    """Resolve file path against current workspace or fallback.

    Resolution logic:
    1. If ContextVar has workspace, use it as root
    2. Else use cls._root_dir (daemon default)
    3. Apply virtual_mode semantics as before
    """
    workspace = cls.get_current_workspace() or cls._root_dir
    # ... resolution logic using workspace
```

The existing `FilesystemBackend` instance operations delegate to these methods for path resolution.

#### 3. WorkspaceContextMiddleware (New)

**Location:** `src/soothe/middleware/workspace_context.py`

```python
from langchain.agents.middleware import AgentMiddleware

class WorkspaceContextMiddleware(AgentMiddleware):
    """Set workspace context for tool execution.

    Reads workspace from config.configurable and:
    - Sets ContextVar for FrameworkFilesystem access
    - Mirrors in state for explicit tool access
    """

    async def process_agent_input(self, state: AgentState, config: RunnableConfig) -> None:
        workspace = config.get("configurable", {}).get("workspace")
        if workspace:
            FrameworkFilesystem.set_current_workspace(workspace)
            state["workspace"] = workspace  # Mirror in state

    async def process_agent_output(self, state: AgentState, config: RunnableConfig) -> None:
        # Clear context to prevent leaks across stream boundaries
        FrameworkFilesystem.set_current_workspace(None)
```

#### 4. SootheRunner Changes

**Location:** `src/soothe/core/runner/_runner_phases.py`

Modify `astream()` signature:

```python
async def astream(
    self,
    text: str,
    thread_id: str | None = None,
    workspace: str | None = None,  # New parameter
    **kwargs,
) -> AsyncGenerator[StreamChunk, None]:
    config = {"configurable": {"thread_id": thread_id}}
    if workspace:
        config["configurable"]["workspace"] = workspace
    # ... rest of implementation
```

#### 5. Daemon Handler Changes

**Location:** `src/soothe/daemon/_handlers.py`

In message handling (around line 800 where `runner.astream()` is called):

```python
# Get workspace for this thread
thread_workspace = self._thread_workspaces.get(thread_id, self._daemon_workspace)

# Pass to runner
async for chunk in self._runner.astream(text, thread_id=thread_id, workspace=str(thread_workspace)):
    # ... process chunk
```

#### 6. Tool Path Resolution Changes

**Location:** `src/soothe/tools/file_ops/implementation.py`, similar in `execution/`, `code_edit/`

Change `_resolve_path()` method to use FrameworkFilesystem:

```python
def _resolve_path(self, file_path: str) -> Path:
    """Resolve file path against current workspace."""
    from soothe.safety import FrameworkFilesystem

    # Use dynamic workspace if available, else fall back to self.work_dir
    current_ws = FrameworkFilesystem.get_current_workspace()
    if current_ws:
        return FrameworkFilesystem.resolve_path(file_path)

    # Fallback: existing behavior using self.work_dir
    return expand_path(file_path, base=self.work_dir)
```

The `work_dir` field remains on tools for:
- Backward compatibility
- Fallback when ContextVar is empty
- Edge cases (direct tool instantiation outside framework)

## Data Flow Sequence

1. **Client connects** from `/home/user/project-a`
2. **Client sends `new_thread`** with `workspace: "/home/user/project-a"`
3. **Daemon validates** via `validate_client_workspace()`, stores in `_thread_workspaces["thread-123"]`
4. **User sends query** "read the config file"
5. **Daemon passes** `runner.astream("read the config file", thread_id="thread-123", workspace="/home/user/project-a")`
6. **Runner builds** `RunnableConfig: {"configurable": {"thread_id": "thread-123", "workspace": "/home/user/project-a"}}`
7. **WorkspaceContextMiddleware.set** `_current_workspace` to `/home/user/project-a`
8. **Agent processes** query, decides to call `read_file` tool
9. **Tool executes** `_resolve_path("config.yml")` → `FrameworkFilesystem.resolve_path()` → `/home/user/project-a/config.yml`
10. **Stream ends** → middleware clears `_current_workspace`

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No workspace in request | Falls back to daemon's `_daemon_workspace` |
| Invalid workspace path | Validated before storage, rejected with error |
| Workspace outside allowed paths | Policy middleware denies (existing behavior) |
| Absolute path in tool arg | If inside workspace: allowed. Outside: policy check |
| Multiple concurrent threads | ContextVar provides async context isolation |
| Thread resumed after restart | Workspace persisted with thread, restored on load |

## Security Model

The existing security model remains intact:

1. **Workspace validation** at entry (`validate_client_workspace()` blocks system directories)
2. **Policy middleware** checks operations against workspace boundaries
3. **virtual_mode** in FilesystemBackend sandboxed paths when `allow_paths_outside_workspace=False`

ContextVar adds:
- Async-safe isolation (no cross-thread contamination)
- Workspace cannot be spoofed mid-execution (set once per stream)

## Testing Strategy

### Unit Tests

- `test_context_var_set_get_clear()` - ContextVar lifecycle
- `test_framework_filesystem_resolve_with_workspace()` - Path resolution with ContextVar set
- `test_framework_filesystem_resolve_without_workspace()` - Fallback to default
- `test_workspace_context_middleware()` - Middleware configurable/state handling

### Integration Tests

- `test_concurrent_threads_different_workspaces()` - Two threads, verify isolation
- `test_thread_workspace_persistence()` - Workspace persists across multiple astream calls
- `test_daemon_to_tool_flow()` - Full flow from daemon handler to tool execution

### Manual Verification

1. Connect from `/project-a`, run `read_file("src/main.py")`, verify correct path
2. Connect from `/project-b` in separate thread, verify isolation
3. Resume thread after daemon restart, verify workspace restored

## Implementation Scope

| Component | Change Type | Complexity |
|-----------|-------------|------------|
| `filesystem.py` ContextVar + methods | Add | Low |
| `workspace_context.py` middleware | New file | Low |
| `_runner_phases.py` astream signature | Modify | Low |
| `_handlers.py` pass workspace | Modify | Low |
| `file_ops/implementation.py` _resolve_path | Modify | Low |
| `execution/` tools | Modify | Low |
| `code_edit/` tools | Modify | Low |

Total estimated changes: ~150-200 lines across 6-7 files.

## Open Questions

None. All decisions finalized through brainstorming session.

## References

- RFC-0003: SootheRunner architecture
- RFC-0007: Protocol orchestration
- RFC-0016: Consolidated tool refactoring
- `src/soothe/safety/workspace.py`: Workspace validation
- `src/soothe/daemon/_handlers.py`: Thread workspace storage