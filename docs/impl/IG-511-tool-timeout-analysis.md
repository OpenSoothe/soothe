# IG-511 Appendix: Tool Timeout Architecture Analysis

**Purpose**: Analyze existing timeout mechanisms in CoreAgent, deepagents, and soothe to identify gaps and propose general solution.

---

## Current Timeout Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     THREAD POOL LEVEL                            │
│  thread_runner.py: request_timeout_seconds (default: 0=disabled)│
│  ↓ When enabled, asyncio.timeout wraps entire request           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     STRANGELOOP LEVEL                           │
│  executor.py: NO per-tool timeout wrapper                        │
│  graph_interrupt.py: Only cooperative cancellation (0.5s poll)  │
│  ↓ Tool calls execute without timeout guard                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     MIDDLEWARE LEVEL                             │
│  LLMRateLimitMiddleware: LLM API timeout + retry                │
│  FilesystemMiddleware (deepagents): GLOB_TIMEOUT = 20s          │
│  ↓ Per-middleware timeouts, NOT general tool timeout            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     TOOL LEVEL                                   │
│  run_command: subprocess.run(timeout=60s)                        │
│  execute (deepagents): timeout parameter (max 3600s)            │
│  MCP tools: tool_timeout_seconds = 600s                         │
│  grep: NO timeout (was unbounded) ← IG-510 fixed                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Timeout Mechanisms by Source

### 1. deepagents FilesystemMiddleware

| Tool | Timeout | Mechanism |
|------|---------|-----------|
| `glob` | 20s | `concurrent.futures.wait(timeout=GLOB_TIMEOUT)` with shared executor |
| `execute` | Per-call parameter (max 3600s) | `executable.execute(command, timeout=timeout)` |
| `read_file`, `write_file`, `list_directory` | No timeout | Direct backend call |

**Key Pattern**: Uses a shared `ThreadPoolExecutor` for sync tools to enforce timeout via `concurrent.futures.wait()`. Async tools use `asyncio.wait(timeout=...)`.

**File**: `deepagents/middleware/filesystem.py:1297-1426`

### 2. soothe Execution Toolkit

| Tool | Timeout | Mechanism |
|------|---------|-----------|
| `run_command` | 60s default | `subprocess.run(timeout=actual_timeout)` |
| `run_background` | No timeout | Background process, `kill_process` for cleanup |

**File**: `packages/soothe/src/soothe/toolkits/execution.py:186-218`

### 3. soothe MCP Registry

| Tool | Timeout | Mechanism |
|------|---------|-----------|
| MCP tools | 600s default | `emit_tool_timeout()` + `RuntimeError` |

**File**: `packages/soothe/src/soothe/mcp/registry.py:488-492`

### 4. soothe Thread Pool (Daemon)

| Layer | Timeout | Mechanism |
|-------|---------|-----------|
| Request | 0 (disabled) | `asyncio.timeout(timeout_seconds)` when enabled |
| Worker idle | 300s | `request_queue.get(timeout=idle_timeout_seconds)` |

**File**: `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py:185-264`

### 5. soothe StrangeLoop Executor

| Layer | Timeout | Mechanism |
|-------|---------|-----------|
| LLM calls | Middleware | `LLMRateLimitMiddleware` handles timeout + retry |
| Tool calls | **NONE** | No wrapper, relies on tool-level timeout |
| Stream chunk | 0.5s poll | Cooperative cancellation only (NOT timeout) |

**File**: `packages/soothe/src/soothe/foundation/loop/engine/executor.py`

---

## Gap Analysis

### Tools WITHOUT Timeout Guard

| Tool | Risk | Current State |
|------|------|---------------|
| `grep` | High (IG-509) | **Fixed by IG-510**: incremental batching |
| `read_file` (large files) | Medium | Backend may have limits, but no wrapper |
| `list_directory` (deep trees) | Medium | No timeout, could hang on network mounts |
| `glob` (local) | Low | deepagents has 20s timeout |
| Explore subagent | High | Could launch long-running searches |
| Custom plugin tools | Unknown | No standard timeout interface |

### Root Cause of IG-509 Hang

The grep Python fallback had **no timeout guard at ANY level**:
- Tool level: No timeout in `_grep_python_walk()`
- Executor level: No per-tool timeout wrapper
- Middleware level: soothe filesystem not wrapped by deepagents middleware
- Pool level: `request_timeout_seconds=0` (disabled)

---

## Proposed: General Tool Timeout Wrapper

### Option A: Executor-Level Wrapper

Wrap each tool invocation in executor with timeout:

```python
# executor.py

async def _execute_tool_call_with_timeout(
    tool_call: ToolCall,
    tool: BaseTool,
    timeout_s: float = 60.0,  # Default per-tool timeout
) -> ToolMessage:
    """Execute tool with timeout wrapper."""
    try:
        async with asyncio.timeout(timeout_s):
            result = await tool.ainvoke(tool_call.args)
            return ToolMessage(content=result, tool_call_id=tool_call.id)
    except TimeoutError:
        logger.warning("Tool %s timed out after %ds", tool.name, timeout_s)
        return ToolMessage(
            content=f"Error: Tool {tool.name} timed out after {timeout_s}s",
            tool_call_id=tool_call.id,
            status="error",
        )
```

**Pros**: Covers all tools uniformly, configurable timeout per tool type
**Cons**: Requires executor code changes, may race with tool's internal timeout

### Option B: ToolInterface Timeout Protocol

Define timeout as part of tool interface:

```python
# protocol.py

class ToolWithTimeout(BaseTool):
    """Tool interface with built-in timeout support."""

    default_timeout: float = 60.0

    def _run_with_timeout(self, *args, timeout: float | None = None, **kwargs) -> str:
        actual_timeout = timeout or self.default_timeout
        # ... implementation
```

**Pros**: Each tool controls its timeout semantics
**Cons**: Requires migrating all tools to new interface, inconsistent adoption

### Option C: Middleware Layer (Recommended)

Add a `ToolTimeoutMiddleware` similar to `LLMRateLimitMiddleware`:

```python
# middleware/tool_timeout.py

class ToolTimeoutMiddleware:
    """Wrap tool invocations with configurable timeout."""

    def __init__(
        self,
        default_timeout: float = 60.0,
        tool_timeouts: dict[str, float] | None = None,
    ):
        self._default_timeout = default_timeout
        self._tool_timeouts = tool_timeouts or {}

    async def wrap_tool_execution(
        self,
        tool: BaseTool,
        tool_call: ToolCall,
        execute_fn: Callable,
    ) -> ToolMessage:
        timeout_s = self._tool_timeouts.get(tool.name, self._default_timeout)

        try:
            async with asyncio.timeout(timeout_s):
                return await execute_fn(tool, tool_call)
        except TimeoutError:
            return ToolMessage(
                content=f"Error: Tool {tool.name} timed out after {timeout_s}s",
                tool_call_id=tool_call.id,
                status="error",
            )
```

**Pros**: Consistent with LLM middleware pattern, configurable per-tool, no executor changes
**Cons**: Requires middleware injection into tool execution path

---

## Recommended Approach

**Phase 1 (Implemented)**: Fix grep specifically with incremental batching (IG-510)

**Phase 2 (Future)**: Add `ToolTimeoutMiddleware` to CoreAgent middleware stack:
- Position after tool resolution, before execution
- Configuration: per-tool timeout overrides via config
- Default: 60s for sync tools, 120s for subagents
- Integration: wrap `tool.ainvoke()` calls in executor

---

## Configuration Schema (Proposed)

```yaml
# config/config.template.yml

agent:
  tool_timeout:
    default_seconds: 60.0
    per_tool:
      grep: 30.0
      glob: 20.0
      run_command: 120.0
      read_file: 30.0
      explore_subagent: 180.0
```

---

## References

- `deepagents/middleware/filesystem.py:1297` — glob timeout with shared executor
- `packages/soothe/src/soothe/toolkits/execution.py:186` — run_command timeout
- `packages/soothe/src/soothe/mcp/registry.py:488` — MCP tool timeout
- `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py:185` — request timeout
- `packages/soothe/src/soothe/foundation/loop/engine/graph_interrupt.py:22` — no chunk timeout (IG-506)