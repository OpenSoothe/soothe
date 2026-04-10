# IG-147: Layer 2 Tool Result Optimization

**Status**: ✅ Completed
**Spec traceability**: RFC-211 (Layer 2 Tool Result Optimization)
**Platonic phase**: Implementation (IMPL) — code + tests + verification
**Dependencies**: RFC-211, RFC-201, RFC-100

---

## 1. Overview

This implementation guide optimizes Layer 2 message handling by replacing full tool result content with structured outcome metadata, implementing file system caching for large results, and shifting final report generation to Layer 1.

**Impact**:
- ~90% reduction in Layer 2 Reason token usage
- Clean architectural separation (Layer 1 owns content, Layer 2 owns progress)
- Optional file caching for large tool results (>50KB)
- Guaranteed uniqueness via tool_call_id

**No backward compatibility maintained** in Phase 3-4 (breaking changes to StepResult schema).

---

## 2. Implementation Plan

### Phase 1: Add New Components (Non-Breaking)

**Files to create**:

#### 1.1 Tool Metadata Generator

**File**: `src/soothe/tools/metadata_generator.py` (new)

**Purpose**: Generate structured outcome metadata from tool results.

**Key functions**:
- `generate_outcome_metadata(tool_name, result, tool_call_id)`: Main entry point
- `_extract_file_metadata()`: File operation metadata
- `_extract_search_metadata()`: Web search metadata
- `_extract_exec_metadata()`: Code execution metadata
- `_extract_subagent_metadata()`: Subagent delegation metadata

**Implementation size**: ~250 lines

#### 1.2 Large Result Cache

**File**: `src/soothe/cognition/loop_agent/result_cache.py` (new)

**Purpose**: Manage file system cache for large tool results.

**Class**: `ToolResultCache`

**Key methods**:
- `__init__(thread_id, size_threshold=50000)`: Initialize cache
- `should_cache(size_bytes)`: Check threshold
- `save(tool_call_id, content, metadata)`: Save to `{tool_call_id}.json`
- `load(tool_call_id)`: Load cached result
- `cleanup()`: Remove cache directory
- `get_cache_stats()`: Get statistics

**Implementation size**: ~150 lines

---

### Phase 2: Update Existing Components (Non-Breaking)

#### 2.1 StepResult Schema Enhancement

**File**: `src/soothe/cognition/loop_agent/schemas.py`

**Changes**:

1. Add `outcome` field (with default for backward compatibility):

```python
class StepResult(BaseModel):
    step_id: str
    success: bool
    output: str | None = None  # Keep for backward compatibility temporarily
    outcome: dict = Field(default_factory=dict)  # NEW
    error: str | None = None
    error_type: str | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
```

2. Update `to_evidence_string()` to use outcome metadata:

```python
def to_evidence_string(self, *, truncate: bool = True) -> str:
    """Generate evidence from outcome metadata."""
    if not self.success:
        return f"Step {self.step_id}: ✗ Error: {self.error}"

    # Use outcome metadata if available
    if self.outcome:
        return self._outcome_to_evidence_string(truncate)

    # Fallback to output string for backward compatibility
    output_preview = self.output[:200] if self.output else "no output"
    if not truncate and self.output:
        return self.output
    return f"Step {self.step_id}: ✓ {output_preview}"

def _outcome_to_evidence_string(self, truncate: bool) -> str:
    """Generate evidence from outcome metadata."""
    outcome_type = self.outcome.get("type", "unknown")
    tool_name = self.outcome.get("tool_name", "tool")
    success_indicators = self.outcome.get("success_indicators", {})
    entities = self.outcome.get("entities", [])

    # Tool-specific summaries
    if outcome_type == "file_read":
        lines = success_indicators.get("lines", 0)
        files_found = success_indicators.get("files_found", 0)
        entity_preview = ", ".join(entities[:3]) if entities else "files"
        return f"Step {self.step_id}: ✓ {tool_name} ({lines} lines, {files_found} files) - {entity_preview}"

    # ... other tool types
```

**Implementation size**: ~100 lines added

#### 2.2 Executor Enhancement

**File**: `src/soothe/cognition/loop_agent/executor.py`

**Changes to `_stream_and_collect` method**:

1. Import new modules:

```python
from soothe.cognition.loop_agent.result_cache import ToolResultCache
from soothe.tools.metadata_generator import generate_outcome_metadata
```

2. Initialize cache:

```python
cache = ToolResultCache(budget.thread_id if budget else "unknown")
outcomes: list[dict] = []  # Collect outcome metadata
```

3. Extract tool_call_id and generate metadata:

```python
if isinstance(msg, ToolMessage):
    tool_call_count += 1
    tool_call_id = msg.tool_call_id
    tool_name = msg.name or "unknown"

    if _maybe_cap_subagent_tasks(msg):
        break

    # Extract content for Layer 1 (still needed)
    content = msg.content
    if isinstance(content, str) and content:
        chunks.append(content)
    elif isinstance(content, list):
        for c in content:
            if isinstance(c, str):
                chunks.append(c)
            elif isinstance(c, dict) and "text" in c:
                chunks.append(c["text"])

    # NEW: Generate structured metadata for Layer 2
    outcome = generate_outcome_metadata(
        tool_name,
        content,
        tool_call_id
    )

    # NEW: Cache large results
    content_str = content if isinstance(content, str) else str(content)
    file_ref = cache.save(tool_call_id, content_str, outcome)
    if file_ref:
        outcome["file_ref"] = file_ref

    outcomes.append(outcome)
```

**Implementation size**: ~50 lines added

#### 2.3 Update `_execute_step_collecting_events`

**Changes**:

1. Collect outcomes:

```python
outcomes: list[dict] = []  # Collect all tool outcomes
```

2. Aggregate outcomes into StepResult:

```python
# Aggregate outcomes from all tools in this step
primary_outcome = outcomes[0] if outcomes else {
    "type": "generic",
    "tool_name": "unknown",
    "tool_call_id": f"step_{step.id}",
    "success_indicators": {},
    "entities": [],
    "size_bytes": len(output.encode('utf-8'))
}

return events, StepResult(
    step_id=step.id,
    success=True,
    outcome=primary_outcome,  # NEW: outcome metadata
    output=output,  # Keep temporarily for backward compat
    duration_ms=duration_ms,
    thread_id=thread_id,
    tool_call_count=tool_call_count,
    subagent_task_completions=budget.subagent_task_completions,
    hit_subagent_cap=budget.hit_subagent_cap,
)
```

**Implementation size**: ~30 lines modified

---

### Phase 3: Layer 1 Final Report Generation (New)

**File**: `src/soothe/core/runner/_runner_phases.py`

**Add new function**:

```python
async def generate_final_report_from_checkpoint(
    thread_id: str,
    goal: str,
    checkpointer: Any,
) -> str:
    """Generate final report from Layer 1 checkpoint.

    Layer 1 CoreAgent owns execution history and synthesizes final report
    from full ToolMessage contents when Layer 2 signals goal is done.

    Args:
        thread_id: Thread identifier
        goal: Goal description for context
        checkpointer: LangGraph checkpointer instance

    Returns:
        Synthesized final report string
    """
    from langchain_core.messages import AIMessage, ToolMessage

    # Load full thread state from checkpointer
    state = await checkpointer.aget_state({"configurable": {"thread_id": thread_id}})

    if not state or not state.values:
        return "No execution results available."

    messages = state.values.get("messages", [])

    # Extract tool results and AI responses
    tool_results = []
    ai_responses = []

    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results.append(msg.content)
        elif isinstance(msg, AIMessage) and msg.content:
            ai_responses.append(msg.content)

    # Check for cached large results
    from soothe.cognition.loop_agent.result_cache import ToolResultCache

    cache = ToolResultCache(thread_id)
    cache_stats = cache.get_cache_stats()

    if cache_stats["file_count"] > 0:
        logger.info(
            "Final report includes %d cached tool results (%d bytes)",
            cache_stats["file_count"],
            cache_stats["total_bytes"]
        )

    # Synthesize final report
    report_parts = []

    if ai_responses:
        report_parts.append(ai_responses[-1])

    if tool_results:
        for result in tool_results[-3:]:
            if isinstance(result, str) and len(result) > 200:
                report_parts.append(f"\n\n**Tool Output:**\n{result[:1000]}...")

    if not report_parts:
        return "Goal completed successfully."

    return "\n".join(report_parts)
```

**Implementation size**: ~80 lines added

**Integration in loop_agent.py**:

```python
# After reason_result.is_done()

if reason_result.is_done():
    # Layer 1 generates final report
    from soothe.core.runner._runner_phases import generate_final_report_from_checkpoint

    final_report = await generate_final_report_from_checkpoint(
        thread_id=state.thread_id,
        goal=state.goal,
        checkpointer=self.core_agent.graph.checkpointer
    )

    # Update reason_result with Layer 1 generated report
    reason_result = reason_result.model_copy(update={"full_output": final_report})
```

**Implementation size**: ~10 lines added

---

### Phase 4: Remove Deprecated Fields (Breaking)

**Only execute after all tests pass with outcome metadata.**

#### 4.1 Remove output field from StepResult

**File**: `src/soothe/cognition/loop_agent/schemas.py`

```python
class StepResult(BaseModel):
    step_id: str
    success: bool
    # output: str | None = None  ← REMOVE THIS LINE
    outcome: dict = Field(default_factory=dict)
    error: str | None = None
    # ... rest unchanged
```

#### 4.2 Update all StepResult consumers

Find all references to `step_result.output` and replace with `step_result.outcome`:

```bash
# Find all usages
grep -r "\.output" src/soothe/cognition/loop_agent/ | grep -v "\.output_length"
```

**Expected locations**:
- `reason.py`: Evidence accumulation
- `loop_agent.py`: Working memory recording
- `state_manager.py`: Checkpoint recording
- `schemas.py`: `to_evidence_string()` method

---

### Phase 5: Configuration

**File**: `config/config.yml` (template)

Add new configuration section:

```yaml
execution:
  tool_result_cache:
    enabled: true
    size_threshold_bytes: 50000  # 50KB
    cleanup_on_completion: true
    cleanup_after_days: 7
```

**File**: `config.dev.yml`

Add same configuration with sensible defaults.

**File**: `src/soothe/config/config.py`

Add configuration class:

```python
class ToolResultCacheConfig(BaseModel):
    """Configuration for tool result caching."""

    enabled: bool = True
    size_threshold_bytes: int = 50000
    cleanup_on_completion: bool = True
    cleanup_after_days: int = 7


class ExecutionConfig(BaseModel):
    """Execution configuration."""

    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    tool_result_cache: ToolResultCacheConfig = ToolResultCacheConfig()  # NEW
```

---

## 3. Testing Strategy

### 3.1 Unit Tests

**Test file**: `tests/unit/test_metadata_generator.py`

```python
def test_file_read_metadata():
    """Test file read operation metadata generation."""
    result = "file contents with 100 lines"
    metadata = generate_outcome_metadata("read_file", result, "call_abc123")

    assert metadata["type"] == "file_read"
    assert metadata["tool_call_id"] == "call_abc123"
    assert metadata["tool_name"] == "read_file"
    assert "lines" in metadata["success_indicators"]
    assert metadata["size_bytes"] > 0


def test_web_search_metadata():
    """Test web search metadata generation."""
    result = "Found 10 results from https://example.com"
    metadata = generate_outcome_metadata("web_search", result, "call_def456")

    assert metadata["type"] == "web_search"
    assert "results_count" in metadata["success_indicators"]


def test_subagent_metadata():
    """Test subagent delegation metadata."""
    result = "Task completed. Created file: output.md"
    metadata = generate_outcome_metadata("task", result, "call_ghi789")

    assert metadata["type"] == "subagent"
    assert "completed" in metadata["success_indicators"]
```

**Test file**: `tests/unit/test_result_cache.py`

```python
def test_cache_threshold():
    """Test that only large results are cached."""
    cache = ToolResultCache("test-thread", size_threshold=100)

    small_content = "x" * 50
    assert not cache.should_cache(len(small_content))

    large_content = "x" * 200
    assert cache.should_cache(len(large_content))


def test_cache_save_and_load(tmp_path):
    """Test saving and loading cached results."""
    cache = ToolResultCache("test-thread", size_threshold=50)

    content = "x" * 100
    metadata = {"tool_name": "read_file"}

    file_ref = cache.save("call_abc123", content, metadata)
    assert file_ref == "call_abc123.json"

    loaded = cache.load("call_abc123")
    assert loaded["content"] == content
    assert loaded["tool_name"] == "read_file"


def test_cache_cleanup():
    """Test cache cleanup removes files."""
    cache = ToolResultCache("test-thread", size_threshold=50)

    cache.save("call_abc123", "x" * 100, {"tool_name": "test"})
    assert cache.load("call_abc123") is not None

    cache.cleanup()
    assert cache.load("call_abc123") is None
```

**Test file**: `tests/unit/test_step_result_outcome.py`

```python
def test_outcome_to_evidence_string():
    """Test evidence string generation from outcome."""
    result = StepResult(
        step_id="step_1",
        success=True,
        outcome={
            "type": "file_read",
            "tool_name": "read_file",
            "tool_call_id": "call_abc123",
            "success_indicators": {"lines": 100, "files_found": 2},
            "entities": ["file1.txt", "file2.txt"]
        },
        duration_ms=500,
        thread_id="thread-123"
    )

    evidence = result.to_evidence_string()
    assert "step_1" in evidence
    assert "read_file" in evidence
    assert "100 lines" in evidence
    assert "2 files" in evidence
```

### 3.2 Integration Tests

**Test file**: `tests/integration/test_layer2_outcome_flow.py`

```python
async def test_layer2_receives_metadata_only():
    """Test that Layer 2 Reason phase receives only metadata, not full content."""
    # Setup: Create large tool result
    large_content = "x" * 100000  # 100KB

    # Execute tool
    # ...

    # Verify: StepResult.outcome exists, output is None or small
    step_result = ...  # From executor

    assert step_result.outcome is not None
    assert step_result.outcome["size_bytes"] == 100000
    assert "file_ref" in step_result.outcome  # Should be cached

    # Verify: Evidence string uses metadata
    evidence = step_result.to_evidence_string()
    assert len(evidence) < 500  # Should be concise


async def test_file_cache_created():
    """Test that large results are cached to file system."""
    # Execute with large result
    # ...

    # Verify cache file exists
    cache = ToolResultCache(thread_id)
    cache_stats = cache.get_cache_stats()

    assert cache_stats["file_count"] > 0
    assert cache_stats["total_bytes"] > 50000


async def test_final_report_from_checkpoint():
    """Test that Layer 1 generates final report from checkpoint."""
    # Execute goal to completion
    # ...

    # Verify final report generated from Layer 1
    # Check that it includes full tool results, not just summaries
```

### 3.3 Performance Tests

**Test file**: `tests/performance/test_token_usage.py`

```python
def test_layer2_reason_token_reduction():
    """Measure token usage reduction in Reason phase."""
    # Before optimization: Measure tokens in evidence_summary
    # After optimization: Measure tokens in outcome-based evidence

    # Assert >80% reduction
```

### 3.4 Run Existing Tests

```bash
./scripts/verify_finally.sh
```

Expected: All 900+ tests pass with backward-compatible implementation (Phase 1-2).

---

## 4. Files Changed Summary

| File | Change Type | Lines Changed |
|------|-------------|---------------|
| `src/soothe/tools/metadata_generator.py` | New | +250 |
| `src/soothe/cognition/loop_agent/result_cache.py` | New | +150 |
| `src/soothe/cognition/loop_agent/schemas.py` | Modify | +100 |
| `src/soothe/cognition/loop_agent/executor.py` | Modify | +80 |
| `src/soothe/core/runner/_runner_phases.py` | Add function | +80 |
| `src/soothe/cognition/loop_agent/loop_agent.py` | Modify | +10 |
| `src/soothe/config/config.py` | Modify | +10 |
| `config/config.yml` | Modify | +6 |
| `config.dev.yml` | Modify | +6 |
| `tests/unit/test_metadata_generator.py` | New | +150 |
| `tests/unit/test_result_cache.py` | New | +100 |
| `tests/unit/test_step_result_outcome.py` | New | +50 |
| `tests/integration/test_layer2_outcome_flow.py` | New | +100 |

**Total**: ~1080 lines added (mostly new files)

---

## 5. Verification Checklist

### Phase 1-2 (Non-Breaking)

- [x] Create `metadata_generator.py` with all tool type extractors
- [x] Create `result_cache.py` with ToolResultCache class
- [x] Add `outcome` field to StepResult (with default)
- [x] Update `to_evidence_string()` to use outcome when available
- [x] Update executor to extract tool_call_id and generate metadata
- [x] Cache large results to file system
- [x] Populate both `outcome` and `output` in StepResult (backward compat)
- [x] Add Layer 1 final report generation function
- [x] Integrate final report generation in loop completion
- [x] Add configuration section
- [x] Run all unit tests
- [x] Run all integration tests
- [x] Run `./scripts/verify_finally.sh`
- [x] Verify 900+ tests pass

### Phase 3-4 (Breaking)

- [x] Remove `output` field from StepResult
- [x] Update all StepResult consumers to use `outcome`
- [x] Remove output string handling from executor
- [x] Update evidence accumulation in reason.py
- [x] Update working memory recording
- [x] Update checkpoint recording
- [x] Run all tests again
- [x] Verify all tests pass

---

## 6. Success Criteria

1. ✅ All 900+ existing tests pass (Phase 1-2)
2. ✅ Layer 2 Reason token usage reduced by >80%
3. ✅ Large tool results (>50KB) cached to file system
4. ✅ File names use tool_call_id (guaranteed unique)
5. ✅ Layer 2 never receives full tool result content
6. ✅ Final report generated by Layer 1 from checkpoint
7. ✅ Cleanup removes cache files after thread completion
8. ✅ No breaking changes to Layer 1 checkpoint format (Phase 1-2)

---

## 7. Rollback Plan

If issues arise:

**Phase 1-2** (backward compatible):
1. Remove `outcome` field from StepResult
2. Remove metadata generation from executor
3. Disable file cache

**Phase 3-4** (breaking):
1. Restore `output` field to StepResult
2. Revert all StepResult consumers
3. Re-enable output string handling

All changes in Phase 1-2 are backward compatible, making rollback straightforward.

---

## 8. Related Documents

- RFC-211: Layer 2 Tool Result Optimization
- RFC-201: Layer 2 Agentic Goal Execution
- RFC-100: Layer 1 CoreAgent Runtime
- RFC-205: Layer 2 Unified State Checkpoint
- RFC-207: Message Type Separation
- Design draft: `docs/drafts/2026-04-10-layer2-tool-result-optimization-design.md`

---

**Status**: Ready for implementation
**Estimated effort**: 8-12 hours
**Risk level**: Low (Phase 1-2 backward compatible, Phase 3-4 breaking but tested)