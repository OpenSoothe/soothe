# IG-136: Module Consolidation and LLM Tracing

**Implementation Guide**: 0136
**Title**: Module Consolidation and LLM Request/Response Tracing
**RFC**: N/A (Internal refactoring and debugging enhancement)
**Status**: Completed
**Created**: 2026-04-08
**Dependencies**: None

---

## Overview

This implementation guide documents two major improvements:

1. **Module Consolidation**: Merged duplicate modules to reduce code duplication and improve maintainability
   - Merged `src/soothe/cognition/loop_working_memory/` into `loop_agent/`
   - Merged `src/soothe/core/prompts/` into `prompts/`

2. **LLM Tracing**: Added comprehensive debugging for LLM request/response lifecycle
   - New `LLMTracingMiddleware` for tracing all LLM calls
   - Detailed logging of requests, responses, token usage, and errors
   - Enabled via `SOOTHE_LOG_LEVEL=DEBUG` environment variable

---

## Part 1: Module Consolidation

### 1.1 Loop Working Memory Merge

**Problem**: `loop_working_memory` module was separate from `loop_agent` but only used by `loop_agent`, creating unnecessary indirection.

**Solution**: Merged `LoopWorkingMemory` class into `loop_agent` module.

**Changes**:

1. **Moved implementation**:
   - `src/soothe/cognition/loop_working_memory/memory.py` → `src/soothe/cognition/loop_agent/working_memory.py`

2. **Updated imports**:
   - `loop_agent/__init__.py` - Added `LoopWorkingMemory` to exports
   - `loop_agent/loop_agent.py` - Changed import to local
   - `loop_agent/state_manager.py` - Updated TYPE_CHECKING import
   - `tests/unit/test_loop_working_memory.py` - Updated imports and mock paths

3. **Removed old module**: Deleted `src/soothe/cognition/loop_working_memory/` directory

4. **Protocol preserved**: `LoopWorkingMemoryProtocol` remains in `protocols/loop_working_memory.py`

**Files Changed**:
- `src/soothe/cognition/loop_agent/__init__.py`
- `src/soothe/cognition/loop_agent/loop_agent.py`
- `src/soothe/cognition/loop_agent/state_manager.py`
- `src/soothe/cognition/loop_agent/working_memory.py` (new)
- `tests/unit/test_loop_working_memory.py`
- `src/soothe/cognition/loop_working_memory/` (deleted)

### 1.2 Prompts Module Merge

**Problem**: Two separate prompts directories (`core/prompts` and `prompts`) created confusion about where prompt-related code should live.

**Solution**: Consolidated all prompt functionality into single `prompts/` module.

**Changes**:

1. **Moved implementation**:
   - `src/soothe/core/prompts/context_xml.py` → `src/soothe/prompts/context_xml.py`

2. **Updated imports**:
   - `prompts/__init__.py` - Added all context_xml exports
   - `prompts/builder.py` - Changed to local imports
   - `core/middleware/system_prompt_optimization.py`
   - `backends/planning/claude.py`
   - `backends/planning/simple.py`
   - `tests/unit/test_dynamic_system_context.py`

3. **Removed old module**: Deleted `src/soothe/core/prompts/` directory

4. **Unified exports**: Updated `prompts/__init__.py` to export:
   - `PromptBuilder` (builder.py)
   - All context XML functions: `build_soothe_environment_section`, `build_soothe_workspace_section`, etc.

**Files Changed**:
- `src/soothe/prompts/__init__.py`
- `src/soothe/prompts/builder.py`
- `src/soothe/prompts/context_xml.py` (new)
- `src/soothe/core/middleware/system_prompt_optimization.py`
- `src/soothe/backends/planning/claude.py`
- `src/soothe/backends/planning/simple.py`
- `tests/unit/test_dynamic_system_context.py`
- `src/soothe/core/prompts/` (deleted)

---

## Part 2: LLM Request/Response Tracing

### 2.1 Motivation

Debugging LLM behavior was difficult without visibility into:
- What prompts are being sent to the LLM
- How tokens are being consumed
- What the latency is for each LLM call
- What errors occur and when

### 2.2 Implementation

**New File**: `src/soothe/core/middleware/llm_tracing.py`

**Class**: `LLMTracingMiddleware`

**Features**:

1. **Request Tracing**:
   - Message count and total character count
   - Message breakdown by type (system, human, AI)
   - System prompt preview (first 200 chars by default)
   - Thread ID from request state

2. **Response Tracing**:
   - Response latency (milliseconds)
   - Response content preview
   - Token usage (prompt, completion, total)
   - Tool call detection and logging

3. **Error Tracing**:
   - Error type and message
   - Time to failure
   - Exception details

4. **Correlation**:
   - Unique sequential trace IDs
   - Matches requests with responses

**Example Log Output**:

```
[LLM Trace #1] Request: 3 messages (1.2K chars)
[LLM Trace #1] Messages: system=1, human=1, ai=1
[LLM Trace #1] System prompt (preview): You are a helpful assistant...
[LLM Trace #1] Thread: thread-123
[LLM Trace #1] Response: 340ms, preview: Here's the analysis...
[LLM Trace #1] Token usage: prompt=256, completion=128, total=384
```

### 2.3 Integration

**Middleware Stack Position** (updated in `src/soothe/core/middleware/_builder.py`):

1. Policy enforcement
2. System prompt optimization
3. **LLM tracing** ← NEW
4. Execution hints
5. Workspace context
6. Subagent context

**Enabling LLM Tracing**:

Option 1 - Environment Variable (recommended for debugging):
```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "your query"
```

Option 2 - Configuration File:
```yaml
llm_tracing:
  enabled: true
```

### 2.4 Configuration Options

```python
LLMTracingMiddleware(log_preview_length=200)
```

Parameters:
- `log_preview_length`: Maximum characters for message previews (default: 200)

### 2.5 Files Changed

**New Files**:
- `src/soothe/core/middleware/llm_tracing.py`
- `docs/llm_tracing.md`

**Modified Files**:
- `src/soothe/core/middleware/__init__.py` - Added exports
- `src/soothe/core/middleware/_builder.py` - Added to middleware stack

---

## Testing

### Verification Results

All changes passed the complete verification suite:

```
✓ Format check: PASSED
✓ Linting: PASSED
✓ Unit tests: PASSED (1580 passed, 2 skipped, 1 xfailed)
✓ Module import boundaries: PASSED
```

### Test Coverage

- Existing tests continue to pass with updated imports
- No new tests added (middleware is for debugging only)
- Manual testing of LLM tracing performed

---

## Migration Guide

### For Module Consolidation

**No action required** - imports are updated automatically.

If you were importing from old locations:

**Old** (removed):
```python
from soothe.cognition.loop_working_memory import LoopWorkingMemory
from soothe.core.prompts.context_xml import build_soothe_environment_section
```

**New**:
```python
from soothe.cognition.loop_agent import LoopWorkingMemory
from soothe.prompts import build_soothe_environment_section
```

### For LLM Tracing

**To enable**:
```bash
export SOOTHE_LOG_LEVEL=DEBUG
soothe "your query"
```

**To filter logs**:
```bash
soothe "query" 2>&1 | grep "\[LLM Trace"
```

---

## Benefits

### Module Consolidation

1. **Reduced complexity**: Fewer directories to navigate
2. **Clearer structure**: Related code grouped together
3. **Easier maintenance**: Single location for working memory and prompts
4. **Better discoverability**: Intuitive import paths

### LLM Tracing

1. **Better debugging**: Visibility into LLM behavior
2. **Performance profiling**: Measure LLM latency
3. **Token analysis**: Understand token consumption patterns
4. **Error diagnosis**: Faster identification of LLM issues
5. **Prompt optimization**: See actual prompts being sent

---

## Architecture Impact

### Module Structure

**Before**:
```
src/soothe/
├── cognition/
│   ├── loop_agent/
│   └── loop_working_memory/  ← Separate module
├── core/
│   └── prompts/              ← Separate module
└── prompts/                  ← Confusing duplication
```

**After**:
```
src/soothe/
├── cognition/
│   └── loop_agent/
│       └── working_memory.py ← Consolidated
└── prompts/                  ← Single unified module
    ├── builder.py
    └── context_xml.py
```

### Middleware Stack

Added LLM tracing as layer 3 in the middleware stack, positioned after system prompt optimization to trace the final prompts being sent to the LLM.

---

## Future Work

### Potential Enhancements

1. **Configurable preview length** via config file
2. **Structured logging** (JSON format) for log aggregation
3. **Token budget tracking** across conversation turns
4. **Performance metrics export** (Prometheus, etc.)
5. **Request/response sampling** for high-volume scenarios

### Documentation

- User guide update with LLM tracing examples
- Performance debugging guide using LLM traces

---

## References

- RFC-203: Loop Working Memory Protocol
- RFC-104: Dynamic System Context
- RFC-0012: Performance Optimization
- `docs/llm_tracing.md`: User-facing documentation

---

## Conclusion

Successfully consolidated duplicate modules and added comprehensive LLM tracing capability. The changes improve code maintainability while providing powerful debugging tools for understanding LLM behavior.

**Status**: ✅ Completed and verified