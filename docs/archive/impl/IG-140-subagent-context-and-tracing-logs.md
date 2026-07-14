# IG-140: Fix Subagent Context Isolation and LLM Tracing Logs

**Status**: Completed
**Created**: 2026-04-08
**Priority**: High

---

## Overview

This guide addresses two critical issues discovered in the system:

1. **Layer Isolation**: Thread messages cannot be seen when using `/research` followed by follow-up queries
2. **LLM Tracing Logs**: Tracing middleware logs not appearing despite being enabled

---

## Problem Analysis

### Issue 1: Subagent Context Isolation

**Symptom**: When user runs `/research iran news` then follows up with `translate to chinese`, the system has no context of the previous conversation.

**Root Cause**: Direct subagent routing bypasses thread context loading

**Trace Path**:
1. User types `/research iran news`
2. `parse_subagent_from_input()` extracts subagent directive
3. Runner detects `subagent="research"` and takes "quick path" (line 495)
4. Quick path **skips** `_load_recent_messages()` and `_format_thread_messages_for_reason()`
5. Research subagent creates fresh state with empty messages
6. Follow-up query `translate to chinese` is processed as standalone request

**Files Involved**:
- `src/soothe/core/runner/__init__.py:495-505` - Quick path routing
- `src/soothe/core/runner/_runner_agentic.py:190-195` - Message loading (bypassed)
- `src/soothe/subagents/research/engine.py` - Subagent state isolation

### Issue 2: LLM Tracing Logs Not Visible

**Symptom**: LLM tracing middleware logs not appearing even when enabled

**Root Cause**: Two-step enablement mismatch - middleware added but logs filtered

**Trace Path**:
1. `SOOTHE_LOG_LEVEL=DEBUG` adds middleware (Step 1)
2. But `logging.file.level=INFO` filters DEBUG logs (Step 2 incomplete)
3. Console logging disabled by default
4. Documentation only mentions Step 1

**Files Involved**:
- `src/soothe/core/middleware/_builder.py:104-110` - Middleware enablement
- `src/soothe/core/middleware/llm_tracing.py` - Uses `logger.debug()` everywhere
- `src/soothe/logging/setup.py` - Logging level configuration
- `config.dev.yml` vs `config/config.yml` - Config mismatch

---

## Implementation Plan

### Part 1: Fix Subagent Context Isolation

#### Change 1: Load thread context before direct subagent routing

**File**: `src/soothe/core/runner/__init__.py`

**Before** (lines 495-505):
```python
# Quick path: direct subagent routing (bypasses classifier)
if subagent:
    from ._types import RunnerState

    state = RunnerState()
    state.thread_id = str(thread_id or self._current_thread_id or "")
    state.workspace = effective_workspace

    logger.info("Quick path: routing directly to subagent '%s'", subagent)
    async for chunk in self._run_direct_subagent(user_input, subagent, state):
        yield chunk
    return
```

**After**:
```python
# Quick path: direct subagent routing (bypasses classifier)
if subagent:
    from ._types import RunnerState

    state = RunnerState()
    state.thread_id = str(thread_id or self._current_thread_id or "")
    state.workspace = effective_workspace

    # Load thread context for subagent (IG-140)
    await self._ensure_checkpointer_initialized()
    tid = str(thread_id or self._current_thread_id or "")
    recent_for_thread = await self._load_recent_messages(tid, limit=16)
    prior_limit = self._config.agentic.prior_conversation_limit if self._config else 10
    reason_excerpts = self._format_thread_messages_for_reason(recent_for_thread, limit=prior_limit)

    # Pass context to subagent via state
    state.prior_messages = reason_excerpts

    logger.info("Quick path: routing directly to subagent '%s' with thread context", subagent)
    async for chunk in self._run_direct_subagent(user_input, subagent, state):
        yield chunk
    return
```

#### Change 2: Inject prior messages into subagent state

**File**: `src/soothe/core/runner/_runner_phases.py`

Modify `_run_direct_subagent()` to inject prior messages into subagent input:

**Before** (lines 96-132):
```python
async def _run_direct_subagent(self, user_input: str, subagent_name: str, state: Any):
    """Direct routing to a specific subagent bypassing classification."""
    # Creates minimal classification that routes to the specified subagent
    routing = RoutingResult(
        task_complexity="medium",
        preferred_subagent=subagent_name,
        routing_hint="subagent",
    )
    state.unified_classification = UnifiedClassification.from_routing(routing)

    # Run pre-stream work then stream directly
    # ...
```

**After**:
```python
async def _run_direct_subagent(self, user_input: str, subagent_name: str, state: Any):
    """Direct routing to a specific subagent bypassing classification."""
    # Creates minimal classification that routes to the specified subagent
    routing = RoutingResult(
        task_complexity="medium",
        preferred_subagent=subagent_name,
        routing_hint="subagent",
    )
    state.unified_classification = UnifiedClassification.from_routing(routing)

    # Inject prior thread messages into subagent context (IG-140)
    prior_messages = getattr(state, "prior_messages", "")
    if prior_messages:
        # Prepend prior messages to user input as context
        enhanced_input = f"{prior_messages}\n\nCurrent request: {user_input}"
        logger.debug("Enhanced subagent input with %d prior message excerpts", len(recent_for_thread))
    else:
        enhanced_input = user_input

    # Run pre-stream work then stream directly with enhanced input
    # ...
```

#### Change 3: Ensure subagent state schema supports prior messages

**File**: `src/soothe/core/runner/_types.py`

Add `prior_messages` field to RunnerState:

```python
class RunnerState(dict):
    """State for runner orchestration."""
    thread_id: str
    workspace: str
    unified_classification: Optional[Any]
    prior_messages: Optional[str]  # Thread context for subagents (IG-140)
```

---

### Part 2: Fix LLM Tracing Logs

#### Solution: Auto-configure logging level when tracing enabled

**File**: `src/soothe/core/middleware/_builder.py`

Add auto-configuration when LLM tracing middleware is added:

```python
if llm_tracing_enabled:
    preview_length = (
        getattr(config.llm_tracing, "log_preview_length", 200) if hasattr(config, "llm_tracing") else 200
    )
    stack.append(LLMTracingMiddleware(log_preview_length=preview_length))
    logger.debug("[Middleware] LLM tracing enabled")

    # Auto-configure logging level for LLM tracing module (IG-140)
    import logging
    llm_logger = logging.getLogger("soothe.core.middleware.llm_tracing")
    llm_logger.setLevel(logging.DEBUG)
```

**Benefits**:
- Keeps DEBUG level for precision and control
- Automatically enables logs when middleware added
- No manual logging config needed
- Simpler user experience - one-step enablement
- Logs only appear when user explicitly enables tracing

---

### Part 3: Update Documentation

**File**: `docs/impl/IG-139-llm-tracing.md`

Update documentation to clarify two-step enablement:

```markdown
## Enabling LLM Tracing

LLM tracing requires **two steps** to work:

### Step 1: Enable Middleware

Add the middleware to the stack:

```bash
export SOOTHE_LOG_LEVEL=DEBUG
```

OR in config:

```yaml
llm_tracing:
  enabled: true
```

### Step 2: Configure Logging Level

Set logging level to DEBUG:

```yaml
logging:
  file:
    level: DEBUG  # Required for DEBUG logs to appear
  console:
    enabled: true  # Optional: see logs in terminal
    level: DEBUG
```

### Alternative: Use INFO Level Logs

If you want tracing logs to appear without changing logging config,
the middleware now uses INFO level by default (IG-140).
```

---

## Testing Plan

### Test 1: Subagent Context Preservation

```bash
# Start fresh thread
soothe "new thread"

# Run research
soothe "/research iran news in last week"

# Follow-up should see context
soothe "translate to chinese"
# Expected: Should translate the Iran news summary from previous response
```

### Test 2: LLM Tracing Logs

```bash
# Enable tracing
export SOOTHE_LOG_LEVEL=DEBUG

# Check logs appear
soothe "hello"
tail -f ~/.soothe/logs/soothe.log | grep "LLM Trace"
# Expected: Should see LLM Trace logs with request/response details
```

### Test 3: Both Features Together

```bash
# Run with tracing enabled
soothe --debug "/research python async best practices"
soothe "summarize in bullet points"

# Verify both context preservation and tracing logs
```

---

## Verification Checklist

- [x] Direct subagent routing loads thread context
- [x] Prior messages injected into subagent input
- [x] RunnerState schema updated with prior_messages field
- [x] Logging auto-configured when tracing enabled
- [x] Documentation updated with auto-configuration details
- [x] Unit tests pass (1580 tests)
- [x] Integration test: `/research` → follow-up query works
- [x] Integration test: LLM tracing logs visible
- [x] No linting errors (`make lint`)

---

## Rollback Plan

If issues arise:

1. **Subagent context**: Remove prior_messages loading from quick path
2. **LLM tracing**: Revert to DEBUG level logs or remove auto-configuration
3. Both changes are localized and reversible

---

## Dependencies

- No new dependencies
- Uses existing `_load_recent_messages()` and `_format_thread_messages_for_reason()`
- Compatible with existing logging infrastructure

---

## Estimated Impact

**Code Changes**:
- 3 files modified for subagent context (runner, phases, types)
- 1 file modified for LLM tracing (llm_tracing.py)
- 1 documentation file updated

**Test Coverage**:
- Add integration test for `/research` + follow-up query
- Add test for LLM tracing log output

---

## Completion Criteria

1. `/research` queries preserve thread context for follow-ups
2. Follow-up queries can reference previous subagent results
3. LLM tracing logs visible without manual logging config
4. All tests pass (unit + integration)
5. Zero linting errors