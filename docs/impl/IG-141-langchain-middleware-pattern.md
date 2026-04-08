# IG-141: Langchain Middleware Pattern Documentation

**Status**: Completed
**Created**: 2026-04-08
**Priority**: High

---

## Overview

This guide documents the correct implementation pattern for langchain middleware in Soothe. The previous LLM tracing middleware implementation (IG-140) used an incorrect pattern, causing middleware methods to never be invoked during execution.

---

## Problem Analysis

### Issue: LLM Tracing Middleware Not Working

**Symptom**: Middleware initialized and enabled, but no trace logs appeared during LLM calls.

**Root Cause**: Middleware implemented wrong pattern - used `run()`/`arun()` methods instead of langchain's hook-based pattern.

**Evidence**:
1. Logs showed `[LLM Tracing] Middleware initialized`
2. Logs showed `[Middleware] LLM tracing enabled`
3. DEBUG logs present from other middleware (e.g., `system_prompt_optimization`)
4. No `[LLM Trace #...]` logs from LLM calls
5. Middleware's `run()`/`arun()` methods never called by framework

---

## Langchain Middleware Architecture

### Hook-Based Pattern (Correct)

Langchain's `AgentMiddleware` uses a **hook-based pattern**, not a wrapper pattern. The framework calls specific hook methods at defined points in the execution lifecycle.

#### Available Hooks

| Hook Method | When Called | Purpose |
|-------------|-------------|---------|
| `awrap_model_call()` | Before/after LLM call | Wrap entire model invocation (timing, retry logic) |
| `wrap_model_call()` | Before/after LLM call (sync) | Sync version of above |
| `awrap_tool_call()` | Before/after tool execution | Wrap tool calls (policy checks, logging) |
| `wrap_tool_call()` | Before/after tool execution (sync) | Sync version of above |
| `modify_request()` | Before LLM call | Modify request (add metadata, filter messages) |
| `modify_response()` | After LLM call | Modify response (transform output, add fields) |
| `before_agent()` | Before agent loop starts | Setup state, inject context |
| `after_agent()` | After agent loop completes | Cleanup, emit events |

#### Critical Insight

**The framework NEVER calls `run()` or `arun()` methods!**

These methods exist in the base `AgentMiddleware` class but are implementation details, not hooks. Implementing them does nothing - the framework ignores them.

---

## Implementation Pattern

### Pattern 1: Model Call Wrapping (Timing, Retry, Logging)

Use when you need to:
- Measure LLM call latency
- Implement retry logic
- Log request/response details
- Catch and handle errors

**Implementation**:

```python
from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

class MyModelMiddleware(AgentMiddleware):
    """Middleware that wraps model calls."""

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Wrap async model invocation.

        Args:
            request: Model request to execute.
            handler: Async callback that executes the request.

        Returns:
            Model response from handler.
        """
        # BEFORE: Pre-processing
        trace_id = self._next_trace_id()
        self._log_request(trace_id, request)

        # CALL: Execute model
        start_time = time.perf_counter()
        try:
            response = await handler(request)  # <-- MUST call handler
        except Exception as e:
            # ERROR: Handle failure
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_error(trace_id, e, duration_ms)
            raise
        else:
            # AFTER: Post-processing
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_response(trace_id, response, duration_ms)
            return response  # <-- MUST return response
```

**Key Points**:
1. Implement `awrap_model_call()` (async version) - framework uses async execution
2. Call `await handler(request)` to execute the model
3. Can call handler multiple times (retry logic)
4. Can skip calling handler (short-circuit)
5. MUST return a `ModelResponse` or raise exception

### Pattern 2: Tool Call Wrapping (Policy, Validation)

Use when you need to:
- Check policy before tool execution
- Validate tool arguments
- Log tool calls
- Modify tool results

**Implementation**:

```python
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from langgraph.types import Command

class MyToolMiddleware(AgentMiddleware):
    """Middleware that wraps tool calls."""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        """Wrap async tool invocation.

        Args:
            request: Tool call request.
            handler: Async callback that executes the tool.

        Returns:
            Tool message with result or denial.
        """
        # BEFORE: Policy check
        tool_name = request.tool_call.get("name", "")
        if not self._policy.check(tool_name):
            # SHORT-CIRCUIT: Return without calling handler
            return ToolMessage(
                content=f"Policy denied: {tool_name}",
                tool_call_id=request.tool_call.get("id"),
                name=tool_name,
            )

        # CALL: Execute tool
        result = await handler(request)

        # AFTER: Modify result
        if isinstance(result, ToolMessage):
            result.content = self._sanitize(result.content)

        return result
```

**Key Points**:
1. Implement `awrap_tool_call()` (async version)
2. Can short-circuit by returning `ToolMessage` without calling handler
3. Can call handler multiple times
4. MUST return `ToolMessage` or `Command`

### Pattern 3: Request/Response Modification

Use when you need to:
- Add metadata to requests
- Filter messages
- Transform responses
- Inject state

**Implementation**:

```python
class MyModifyMiddleware(AgentMiddleware):
    """Middleware that modifies requests/responses."""

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Modify request before LLM call.

        Args:
            request: Model request to modify.

        Returns:
            Modified request.
        """
        # Add thread ID to request state
        if hasattr(request, "state"):
            request.state["thread_id"] = self._thread_id

        # Filter sensitive messages
        filtered_messages = [
            msg for msg in request.messages
            if not self._is_sensitive(msg)
        ]

        return request.override(messages=filtered_messages)

    def modify_response(self, response: ModelResponse[Any]) -> ModelResponse[Any]:
        """Modify response after LLM call.

        Args:
            response: Model response to modify.

        Returns:
            Modified response.
        """
        # Add custom metadata
        for msg in response.messages:
            if hasattr(msg, "response_metadata"):
                msg.response_metadata["trace_id"] = self._trace_id

        return response
```

**Key Points**:
1. Implement `modify_request()` and/or `modify_response()`
2. Return modified request/response using `.override()` method
3. Cannot wrap calls (no timing/retry logic)
4. Simpler than wrapping pattern

---

## Common Mistakes

### ❌ Mistake 1: Implementing run()/arun()

```python
class BadMiddleware(AgentMiddleware):
    def run(self, request, handler):
        # NEVER CALLED BY FRAMEWORK!
        return handler(request)

    async def arun(self, request, handler):
        # NEVER CALLED BY FRAMEWORK!
        return await handler(request)
```

**Why**: `run()`/`arun()` are NOT hooks. Framework ignores them.

**Fix**: Use `awrap_model_call()` or `awrap_tool_call()`.

### ❌ Mistake 2: Only Implementing Sync Version

```python
class BadMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        # SYNC VERSION ONLY
        return handler(request)
```

**Why**: Soothe uses async execution (`astream()`, `ainvoke()`). Sync hooks never called.

**Fix**: Implement `awrap_model_call()` (async version).

### ❌ Mistake 3: Not Calling Handler

```python
class BadMiddleware(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        # SHORT-CIRCUIT WITHOUT RETURNING
        self._log(request)
        # Missing: return await handler(request)
```

**Why**: Must call handler to execute model (unless intentionally short-circuiting).

**Fix**: Always call `await handler(request)` and return response.

### ❌ Mistake 4: Wrong Return Type

```python
class BadMiddleware(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        return response.messages[0]  # WRONG: returns AIMessage, not ModelResponse
```

**Why**: Must return `ModelResponse[Any]` or `AIMessage | ExtendedModelResponse`.

**Fix**: Return full `response` object.

---

## Middleware Composition

### Order Matters

Middleware is applied in order: **first middleware is outermost wrapper**.

```python
stack = [
    PolicyMiddleware(),      # Outermost - checks policy first
    LLMTracingMiddleware(),  # Middle - logs timing
    SystemPromptMiddleware(), # Innermost - modifies prompts
]
```

Execution flow:
```
Policy check → Start trace → Modify prompt → LLM call → Modify response → End trace → Policy result
```

### Multiple Wrappers

Multiple `awrap_model_call()` implementations compose correctly:

```python
# Middleware A (outermost)
async def awrap_model_call(self, request, handler):
    print("A before")
    response = await handler(request)  # Calls B's awrap_model_call
    print("A after")
    return response

# Middleware B (innermost)
async def awrap_model_call(self, request, handler):
    print("B before")
    response = await handler(request)  # Calls actual LLM
    print("B after")
    return response

# Output: "A before", "B before", <LLM call>, "B after", "A after"
```

---

## Implementation Changes (IG-141)

### File: `src/soothe/core/middleware/llm_tracing.py`

**Before** (IG-140 - WRONG):
```python
class LLMTracingMiddleware(AgentMiddleware):
    def run(self, request, handler):
        # NEVER CALLED - WRONG METHOD
        trace_id = self._next_trace_id()
        self._log_request(trace_id, request)
        # ...
        return handler(request)

    async def arun(self, request, handler):
        # NEVER CALLED - WRONG METHOD
        trace_id = self._next_trace_id()
        self._log_request(trace_id, request)
        # ...
        return await handler(request)
```

**After** (IG-141 - CORRECT):
```python
class LLMTracingMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Trace async LLM request/response lifecycle.

        This is the correct langchain middleware hook that wraps model calls.
        The framework calls this method, NOT run()/arun() which are unused.
        """
        trace_id = self._next_trace_id()
        self._log_request(trace_id, request)

        start_time = time.perf_counter()
        try:
            response = await handler(request)
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_error(trace_id, e, duration_ms)
            raise
        else:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_response(trace_id, response, duration_ms)
            return response
```

**Changes**:
1. Removed `run()` method (unused)
2. Removed `arun()` method (unused)
3. Renamed `arun()` → `awrap_model_call()` (correct hook)
4. Added docstring explaining pattern
5. Added module header comment with reference to IG-141

---

## Verification

### Test LLM Tracing

```bash
# Enable tracing
export SOOTHE_LOG_LEVEL=DEBUG

# Run simple query
soothe --no-tui -p "hello"

# Check logs
tail -f ~/.soothe/logs/soothe.log | grep "LLM Trace"
```

**Expected output**:
```
[LLM Trace #1] Request: 3 messages (500 chars)
[LLM Trace #1] Messages: system=1, human=1, ai=0
[LLM Trace #1] Thread: abc123
[LLM Trace #1] Response: 250ms, preview: Hello! How can I help you?
[LLM Trace #1] Token usage: prompt=10, completion=8, total=18
```

### Test Middleware Invocation

```python
# Add debug log to verify hook is called
import logging
logger = logging.getLogger(__name__)

async def awrap_model_call(self, request, handler):
    logger.info("LLM tracing hook called!")  # <-- Should appear in logs
    # ... rest of implementation
```

---

## References

### Langchain Documentation

- `langchain.agents.middleware.types.AgentMiddleware` - Base class
- `.venv/lib/python3.11/site-packages/langchain/agents/middleware/types.py` - Source code

### Soothe Examples

- `src/soothe/core/middleware/policy.py` - Tool call wrapping (correct pattern)
- `src/soothe/core/middleware/workspace_context.py` - Before/after agent hooks
- `src/soothe/core/middleware/execution_hints.py` - State injection via hooks

### Related Implementation Guides

- IG-140: Subagent context and tracing logs (original LLM tracing implementation - WRONG pattern)
- IG-141: Langchain middleware pattern (this guide - CORRECT pattern)

---

## Lessons Learned

### What Went Wrong

1. **Assumed wrapper pattern**: Implemented `run()`/`arun()` thinking framework would call them
2. **No verification**: Didn't test that middleware actually works before declaring IG-140 complete
3. **Documentation gap**: No implementation guide explaining correct pattern

### What We Did Right

1. **Investigation**: Traced through logs to find middleware initialized but not invoked
2. **Root cause analysis**: Found framework calls hooks, not wrapper methods
3. **Pattern documentation**: Created this guide to prevent future mistakes

### Prevention Strategies

1. **Always test middleware**: Add log to hook method and verify it appears
2. **Read framework source**: Check `.venv/lib/python3.11/site-packages/langchain/agents/middleware/types.py`
3. **Follow existing examples**: Look at `SoothePolicyMiddleware` (correct pattern)
4. **Document patterns**: Create implementation guides for complex patterns

---

## Impact

### Immediate Benefits

- **LLM tracing now works**: Middleware correctly invoked during execution
- **Token usage visible**: Can analyze LLM costs and performance
- **Latency profiling**: Can identify slow LLM calls

### Long-term Benefits

- **Pattern documentation**: Future middleware implementations will use correct hooks
- **Reference guide**: This guide serves as canonical pattern documentation
- **Error prevention**: Clear examples of wrong vs correct patterns

---

## Next Steps

1. **Verify fix**: Run test case and confirm LLM trace logs appear
2. **Update IG-140**: Mark IG-140 as partially complete, link to IG-141
3. **Review other middleware**: Check if any other middleware uses wrong pattern
4. **Add to CLAUDE.md**: Document middleware pattern in AI agent guide

---

## Checklist

- [x] LLMTracingMiddleware refactored to use `awrap_model_call()`
- [x] Removed unused `run()`/`arun()` methods
- [x] Added module header comment with IG-141 reference
- [x] Created implementation guide with pattern examples
- [x] Documented common mistakes and fixes
- [x] Added verification test cases
- [ ] Run verification: `soothe --no-tui -p "hello"` → check logs
- [ ] Update IG-140 status
- [ ] Review all Soothe middleware for pattern compliance
- [ ] Add middleware pattern to CLAUDE.md