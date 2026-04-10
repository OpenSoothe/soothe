# RFC-211: Layer 2 Tool Result Optimization

**RFC**: 211
**Title**: Layer 2 Tool Result Optimization
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-10
**Dependencies**: RFC-201, RFC-100, RFC-205, RFC-207

## Abstract

This RFC optimizes Layer 2 message handling by minimizing data transfer between Layer 1 CoreAgent and Layer 2 Loop Agent. The design introduces a minimal data contract where Layer 2 receives structured outcome metadata instead of full tool result contents, shifts final report generation responsibility to Layer 1 (which owns execution history), and implements optional file system caching for large tool results using tool_call_id for unique identification.

## Problem Statement

Layer 2's current message handling has four critical inefficiencies:

1. **Layer 2 Reason context bloat**: Tool results (often 200KB+) passed to Reason phase cause token limit issues
2. **Storage duplication**: Same tool result stored in both Layer 1 checkpoint and Layer 2 checkpoint
3. **Network/memory transfer cost**: Moving large tool result strings between layers is slow
4. **Limited Layer 2 access**: Current truncation (200 chars) loses information needed for goal-level reasoning

**Root cause**: Layer 2 receives full tool result contents when it only needs progress indicators for goal assessment and step planning.

## Architectural Insight: Responsibility Shift

**Key realization**: Layer 1 CoreAgent owns execution history, therefore it should own final report generation.

**Current responsibility distribution**:
- Layer 2: Goal progress assessment + step planning + **final report generation** ❌ (misplaced)
- Layer 1: Tool execution + conversation management

**Proposed responsibility distribution**:
- Layer 2: Goal progress assessment + step planning only (no content aggregation)
- Layer 1: Tool execution + conversation management + **final report generation** ✅

**Impact**: Layer 2 becomes purely a **goal progress assessor and step planner**, never needing full tool result contents.

## Solution Architecture

### Core Principle

**Layer 2 needs outcome signals, not content details.**

### Minimal Data Contract

**StepResult schema update**:

```python
class StepResult(BaseModel):
    step_id: str
    success: bool
    outcome: dict  # NEW: Structured metadata (replaces output string)
    error: str | None = None
    error_type: str | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
```

**Outcome metadata schema**:

```python
{
    "type": "file_read" | "file_write" | "web_search" | "code_exec" | "subagent",
    "tool_call_id": "call_abc123",  # Unique identifier from LangChain
    "tool_name": "read_file",
    "success_indicators": {
        "lines": 245,
        "files_found": 3,
        "exit_code": 0,
    },
    "entities": ["config.yml", "async_patterns.py"],  # Key resources
    "size_bytes": 2048,
    "file_ref": "call_abc123.json" | None  # Only if result >50KB
}
```

### Data Flow

```
Tool Execution:
  → Tool generates structured outcome metadata
  ↓
Layer 1 CoreAgent:
  → ToolMessage(content="full result", tool_call_id="call_abc123")
  → LangGraph checkpoint (full content)
  → File cache (if >50KB): ~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json
  ↓
Layer 2 Loop Agent:
  → StepResult(outcome={...})
  → Layer 2 checkpoint (metadata only)
  → Reason phase uses outcome for decisions
  ↓
Final Report:
  → Layer 1 synthesizes from checkpoint when Layer 2 signals "done"
```

### Tool Call Uniqueness

**Mechanism**: LangChain's `tool_call_id` guarantees uniqueness per invocation.

**Example**:
```
AIMessage.tool_calls = [
    {name: "read_file", args: {path: "config.yml"}, id: "call_abc123"},
    {name: "read_file", args: {path: "other.txt"}, id: "call_def456"}
]

ToolMessage(tool_call_id="call_abc123", content="...", name="read_file")
ToolMessage(tool_call_id="call_def456", content="...", name="read_file")
```

**File naming**: `{tool_call_id}.json` ensures no collisions even for same tool called multiple times in parallel.

## Implementation Components

### 1. Tool Metadata Generator

**File**: `src/soothe/tools/metadata_generator.py` (new)

**Purpose**: Generate structured outcome metadata from tool results.

**Key function**:
```python
def generate_outcome_metadata(tool_name: str, result: Any, tool_call_id: str) -> dict:
    """Generate structured outcome metadata from tool result.

    Dispatches to tool-specific extractors for file operations,
    web search, code execution, and subagent delegations.
    """
```

**Tool-specific extractors**:
- `_extract_file_metadata()`: Lines, files found, file paths
- `_extract_search_metadata()`: Results count, domains, key terms
- `_extract_exec_metadata()`: Exit code, stdout lines, errors
- `_extract_subagent_metadata()`: Completion status, artifacts

### 2. Large Result Cache

**File**: `src/soothe/cognition/agent_loop/result_cache.py` (new)

**Purpose**: Cache large tool results (>50KB) to file system.

**Class**: `ToolResultCache`

**Key methods**:
- `should_cache(size_bytes)`: Check if result exceeds threshold
- `save(tool_call_id, content, metadata)`: Save to `{tool_call_id}.json`
- `load(tool_call_id)`: Load cached result by ID
- `cleanup()`: Remove cache directory after thread completion

**Cache location**: `~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json`

### 3. Executor Enhancement

**File**: `src/soothe/cognition/agent_loop/executor.py` (modify existing)

**Changes**:
- Extract `tool_call_id` from ToolMessage
- Generate outcome metadata via `generate_outcome_metadata()`
- Cache large results via `ToolResultCache`
- Populate `StepResult.outcome` instead of `StepResult.output`
- Still collect full content for Layer 1 final report generation

### 4. StepResult Schema Update

**File**: `src/soothe/cognition/agent_loop/schemas.py` (modify existing)

**Changes**:
- Replace `output: str | None` with `outcome: dict`
- Update `to_evidence_string()` to generate summaries from outcome metadata
- Tool-specific summary generation based on outcome type

### 5. Layer 1 Final Report Generation

**File**: `src/soothe/core/runner/_runner_phases.py` (add new function)

**Function**: `generate_final_report_from_checkpoint(thread_id, goal, checkpointer)`

**Purpose**: Synthesize final report from Layer 1 checkpoint when Layer 2 signals "done".

**Process**:
1. Load full thread state from checkpointer
2. Extract ToolMessage contents and AI responses
3. Load cached large results if needed
4. Synthesize comprehensive final report

### 6. Configuration

**File**: `config/config.yml` (add new section)

```yaml
execution:
  tool_result_cache:
    enabled: true
    size_threshold_bytes: 50000  # 50KB
    cleanup_on_completion: true
    cleanup_after_days: 7
```

## Benefits

### Performance

1. **Layer 2 context reduction**: ~90% reduction in Reason phase token usage
   - Before: 200KB+ tool results in evidence
   - After: ~1KB structured metadata per tool call

2. **Transfer cost elimination**: No large string movement between layers
   - Before: Full tool result copied to StepResult.output
   - After: Only metadata dict (10-20 fields)

3. **Storage optimization**: Large results cached separately
   - Before: All in LangGraph checkpoint
   - After: Checkpoint + optional file cache

### Architecture

1. **Clean separation**: Layer 1 owns content, Layer 2 owns progress
2. **Responsibility alignment**: Final report generated by Layer 1 (owns history)
3. **Scalability**: File cache handles arbitrarily large tool results
4. **Maintainability**: Structured metadata easier to reason about

### Functionality

1. **Better decisions**: Structured outcome data enables smarter reasoning
2. **No information loss**: File cache preserves full results when needed
3. **Unique identification**: tool_call_id guarantees no collisions
4. **Easy cleanup**: Cache directory per thread

## Migration Strategy

### Phase 1: Add New Components (Non-Breaking)
1. Implement `ToolResultCache` class
2. Implement `generate_outcome_metadata()` function
3. Add `outcome` field to `StepResult` (with default for backward compat)
4. Update `to_evidence_string()` to use outcome when available

### Phase 2: Update Executor (Non-Breaking)
1. Modify `_stream_and_collect()` to extract tool_call_id and generate metadata
2. Cache large results to file system
3. Populate `outcome` field in StepResult
4. Keep `output` field temporarily for backward compatibility

### Phase 3: Remove Deprecated Fields (Breaking)
1. Remove `output` field from StepResult
2. Update all StepResult consumers to use `outcome`
3. Remove output string handling from executor

### Phase 4: Layer 1 Final Report Generation
1. Implement `generate_final_report_from_checkpoint()`
2. Update Layer 2 loop completion to use Layer 1 report
3. Remove synthesis phase from Layer 2

## Testing Requirements

### Unit Tests
- Tool_call_id uniqueness across multiple invocations
- Outcome metadata generation for each tool type
- File cache behavior (threshold, save, load, cleanup)
- Evidence string generation from outcome metadata

### Integration Tests
- Layer 2 reasoning with outcome metadata only
- Final report generation from Layer 1 checkpoint
- Large result handling (100KB+ tool results)
- Parallel execution with correct tool_call_id correlation

### Performance Tests
- Measure Layer 2 Reason token usage (before/after)
- Measure StepResult creation time
- Measure cache hit rate and retrieval time
- Measure checkpoint size comparison

## Success Criteria

1. ✅ All 900+ existing tests pass
2. ✅ Layer 2 Reason token usage reduced by >80%
3. ✅ Large tool results (>50KB) cached to file system
4. ✅ File names use tool_call_id (guaranteed unique)
5. ✅ Layer 2 never receives full tool result content
6. ✅ Final report generated by Layer 1 from checkpoint
7. ✅ Cleanup removes cache files after thread completion
8. ✅ No breaking changes to Layer 1 checkpoint format (Phase 1-2)

## Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `execution.tool_result_cache.enabled` | bool | true | Enable file system caching |
| `execution.tool_result_cache.size_threshold_bytes` | int | 50000 | Minimum size to cache (50KB) |
| `execution.tool_result_cache.cleanup_on_completion` | bool | true | Remove cache after goal done |
| `execution.tool_result_cache.cleanup_after_days` | int | 7 | Remove old caches after N days |

## Future Enhancements

1. **Adaptive caching**: Predict which results will be needed
2. **Compression**: Compress cached results for storage savings
3. **Outcome schema standardization**: Formal JSON Schema per tool type
4. **Cross-thread caching**: Share common results across threads
5. **Streaming outcomes**: Generate metadata incrementally for long-running tools

## Changelog

### 2026-04-10
- Initial RFC draft from design brainstorming
- Defined minimal data contract with outcome metadata
- Specified tool_call_id uniqueness mechanism
- Designed dual storage strategy (checkpoint + file cache)
- Shifted final report generation to Layer 1

## References

- RFC-201: Layer 2 Agentic Goal Execution
- RFC-100: Layer 1 CoreAgent Runtime
- RFC-205: Layer 2 Unified State Checkpoint
- RFC-207: Message Type Separation
- RFC-209: Executor Thread Isolation Simplification
- RFC-210: Dynamic Tool System Context

---

*Layer 2 tool result optimization through structured metadata, file caching, and responsibility alignment.*