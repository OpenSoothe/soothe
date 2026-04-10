# IG-132: Layer 2 Context Isolation Completion

**Status:** Draft
**Spec traceability:** RFC-201 (Layer 2 Agentic Goal Execution), RFC-203 (Loop Working Memory)
**Platonic phase:** Implementation (IMPL) — code + tests + verification

---

## 1. Overview

This guide completes the three remaining implementation items for RFC-201 Layer 2 Context Isolation:

1. **Automatic isolation trigger logic** — Executor checks `step.subagent` field to apply thread isolation
2. **Metrics aggregation in executor** — Collect wave metrics after each Act wave
3. **Reason metrics-aware prompts** — Build `<SOOTHE_WAVE_METRICS>` section for Reason LLM calls

These features prevent cross-wave contamination, output duplication, and premature `continue` decisions.

---

## 2. Background

### 2.1 What's Already Implemented

| Feature | IG Reference | Status |
|---------|--------------|--------|
| Thread isolation pattern | IG-131 | ✅ Implemented |
| Subagent task cap tracking | IG-130 | ✅ Implemented |
| Output contract suffix | IG-119 | ✅ Implemented |
| Prior conversation for Reason | IG-128 | ✅ Implemented |

### 2.2 What's Missing

**Automatic isolation trigger**: IG-131 implemented the thread isolation mechanism but didn't complete the automatic trigger logic. The executor has `_should_use_isolated_sequential_thread()` but it checks config flags, not the semantic rule (step.subagent field).

**Metrics aggregation**: IG-130 added `last_wave_tool_call_count`, `last_wave_subagent_task_count`, `last_wave_hit_subagent_cap` to LoopState, but the executor doesn't aggregate `last_wave_output_length`, `last_wave_error_count`, or context window metrics.

**Reason prompts**: Reason phase doesn't build a `<SOOTHE_WAVE_METRICS>` section yet. It relies on truncated evidence summary only.

---

## 3. Implementation Plan

### Phase A: Automatic Isolation Trigger

**Goal**: Executor checks `step.subagent` field to decide thread isolation, not just config flags.

**Current behavior**: `_should_use_isolated_sequential_thread(steps)` checks config flags `sequential_act_isolated_thread` and `sequential_act_isolate_when_step_subagent_hint`, which requires a hint in the steps.

**Desired behavior**: Automatic semantic rule — if any step has `subagent` field set, isolate. No config dependency for the decision itself.

**Files affected**:
- `src/soothe/cognition/agent_loop/executor.py` — Simplify trigger logic

**Implementation**:

```python
def _should_use_isolated_sequential_thread(self, steps: list) -> bool:
    """Return True if any step has subagent delegation (semantic rule)."""
    if not self._config.agentic.sequential_act_isolated_thread:
        return False  # Feature disabled
    # Automatic: isolate if any step delegates to subagent
    return any(bool(getattr(s, "subagent", None)) for s in steps)
```

**Logic change**: Remove `sequential_act_isolate_when_step_subagent_hint` dependency. The presence of `step.subagent` IS the hint.

**Config impact**: Keep `sequential_act_isolated_thread` as master switch. Remove `sequential_act_isolate_when_step_subagent_hint` from config (unused).

---

### Phase B: Metrics Aggregation in Executor

**Goal**: Executor aggregates complete wave metrics after each Act wave.

**New LoopState fields**:
```python
class LoopState(BaseModel):
    # Existing (IG-130)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False

    # New (this IG)
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0
```

**Aggregation points**:

1. **After sequential wave** (`_execute_sequential_chunk`):
   - Sum `tool_call_count` from StepResult
   - Sum `subagent_task_completions` from StepResult
   - OR `hit_subagent_cap` from StepResult
   - Measure `output_length` from final output
   - Count errors (StepResult.success == False)

2. **After parallel wave** (`_execute_parallel`):
   - Aggregate across all step results
   - Total tool calls, subagent tasks, errors
   - Max output length (longest step output)

3. **Context window metrics**:
   - Extract from model response `usage_metadata` if available
   - Fallback: estimate from message lengths
   - Update `total_tokens_used` cumulatively
   - Calculate `context_percentage_consumed` (relative to model context limit)

**Files affected**:
- `src/soothe/cognition/agent_loop/schemas.py` — Add new LoopState fields
- `src/soothe/cognition/agent_loop/executor.py` — Aggregation logic
- `src/soothe/config/models.py` — Context window limit config (optional)

---

### Phase C: Reason Metrics-Aware Prompts

**Goal**: Build `<SOOTHE_WAVE_METRICS>` section in Reason prompt.

**Location**: `src/soothe/cognition/planning/simple.py` — `build_loop_reason_prompt()`

**Prompt section**:

```
<SOOTHE_WAVE_METRICS>
Last Act wave completed:
- Subagent calls: 1
- Tool calls: 2
- Output length: 8000 characters
- Errors: 0
- Cap hit: No
- Context used: 15% (30,000 / 200,000 tokens)
</SOOTHE_WAVE_METRICS>
```

**When to include**: Only if `last_wave_tool_call_count > 0` (wave executed).

**Integration**:
- Read from `state.last_wave_tool_call_count`, etc.
- Format as human-readable metrics block
- Insert before `<SOOTHE_PRIOR_CONVERSATION>` if present

**Files affected**:
- `src/soothe/cognition/planning/simple.py` — Prompt building
- Tests: `tests/unit/test_reason_prompt_metrics.py` — New test file

---

## 4. File Structure and Changes

| Area | Path | Change |
|------|------|--------|
| LoopState schema | `src/soothe/cognition/agent_loop/schemas.py` | Add `last_wave_output_length`, `last_wave_error_count`, `total_tokens_used`, `context_percentage_consumed` |
| Executor | `src/soothe/cognition/agent_loop/executor.py` | Simplify isolation trigger; add metrics aggregation after sequential/parallel waves |
| Reason prompt | `src/soothe/cognition/planning/simple.py` | Build `<SOOTHE_WAVE_METRICS>` section |
| Config | `src/soothe/config/models.py` | Remove `sequential_act_isolate_when_step_subagent_hint` (unused) |
| Tests | `tests/unit/test_executor_isolation_trigger.py` | New test: automatic trigger based on step.subagent |
| Tests | `tests/unit/test_executor_wave_metrics.py` | New test: metrics aggregation |
| Tests | `tests/unit/test_reason_prompt_metrics.py` | New test: metrics section in Reason prompt |

---

## 5. Detailed Implementation

### 5.1 Phase A: Automatic Isolation Trigger

**File**: `src/soothe/cognition/agent_loop/executor.py`

**Current code** (lines 88-94):
```python
def _should_use_isolated_sequential_thread(self, steps: list) -> bool:
    """True when this sequential wave should run on a fresh checkpoint branch (IG-131)."""
    if self._config is None or not self._config.agentic.sequential_act_isolated_thread:
        return False
    if self._config.agentic.sequential_act_isolate_when_step_subagent_hint:
        return any(bool(getattr(s, "subagent", None)) for s in steps)
    return True
```

**Updated code**:
```python
def _should_use_isolated_sequential_thread(self, steps: list) -> bool:
    """Return True if sequential wave should use isolated thread.

    Semantic rule: isolate when any step delegates to subagent.
    Rationale: delegation steps should work on explicit input, not prior thread history.

    Args:
        steps: List of StepAction objects to execute

    Returns:
        True if thread isolation should be applied
    """
    if self._config is None or not self._config.agentic.sequential_act_isolated_thread:
        return False  # Feature disabled
    # Automatic: isolate if any step has subagent delegation
    return any(bool(getattr(s, "subagent", None)) for s in steps)
```

**Config cleanup**: Remove `sequential_act_isolate_when_step_subagent_hint` from `AgenticLoopConfig` (no longer needed).

---

### 5.2 Phase B: Metrics Aggregation

**File**: `src/soothe/cognition/agent_loop/schemas.py`

**Add to LoopState** (after line 229):
```python
    # Additional wave metrics for Reason (RFC-201 completion)
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0
```

**File**: `src/soothe/cognition/agent_loop/executor.py`

**Add helper method**:
```python
def _aggregate_wave_metrics(
    self,
    step_results: list[StepResult],
    output: str,
    state: LoopState,
) -> None:
    """Aggregate metrics from wave execution into LoopState.

    Called after sequential or parallel wave completes.

    Args:
        step_results: List of step results from the wave
        output: Combined output text from the wave
        state: LoopState to update with aggregated metrics
    """
    # Sum tool calls and subagent tasks
    total_tool_calls = sum(r.tool_call_count for r in step_results)
    total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)

    # OR cap hit (any step hit cap)
    hit_cap = any(r.hit_subagent_cap for r in step_results)

    # Count errors
    error_count = sum(1 for r in step_results if not r.success)

    # Measure output length
    output_length = len(output) if output else 0

    # Update state
    state.last_wave_tool_call_count = total_tool_calls
    state.last_wave_subagent_task_count = total_subagent_tasks
    state.last_wave_hit_subagent_cap = hit_cap
    state.last_wave_output_length = output_length
    state.last_wave_error_count = error_count

    # Context window metrics (if available from model response)
    # This would be extracted from the last AIMessage usage_metadata
    # For now, we estimate from output length
    # TODO: Extract from model response metadata in future enhancement
```

**Integrate into `_execute_sequential_chunk`** (after line 420, before yielding StepResult):
```python
            # Aggregate metrics after successful wave
            self._aggregate_wave_metrics(
                step_results=[sr for sr in self._step_results_for_chunk(...)],
                output=output,
                state=state,
            )
```

**Integrate into `_execute_parallel`** (after gathering results, before yielding):
```python
        # Aggregate metrics from parallel execution
        successful_results = [step_result for events, step_result in results if not isinstance(step_result, Exception)]
        if successful_results:
            # For parallel, output is distributed across steps
            # Use max output length as proxy
            max_output_len = max(len(r.output or "") for r in successful_results)
            self._aggregate_wave_metrics(
                step_results=successful_results,
                output="",  # No combined output for parallel
                state=state,
            )
            state.last_wave_output_length = max_output_len
```

---

### 5.3 Phase C: Reason Metrics-Aware Prompts

**File**: `src/soothe/cognition/planning/simple.py`

**Add to `build_loop_reason_prompt()`** (after line ~200, before rendering prior conversation):

```python
    # Add wave metrics section if wave was executed
    if state.last_wave_tool_call_count > 0:
        cap_status = "Yes" if state.last_wave_hit_subagent_cap else "No"
        context_pct = f"{state.context_percentage_consumed:.1%}" if state.context_percentage_consumed > 0 else "N/A"
        context_tokens = f"{state.total_tokens_used:,}" if state.total_tokens_used > 0 else "N/A"

        metrics_section = f"""
<SOOTHE_WAVE_METRICS>
Last Act wave completed:
- Subagent calls: {state.last_wave_subagent_task_count}
- Tool calls: {state.last_wave_tool_call_count}
- Output length: {state.last_wave_output_length:,} characters
- Errors: {state.last_wave_error_count}
- Cap hit: {cap_status}
- Context used: {context_pct} ({context_tokens} tokens)
</SOOTHE_WAVE_METRICS>
"""
        prompt_parts.append(metrics_section)
```

**Position in prompt**: After goal statement, before prior conversation (if present).

---

## 6. Testing Strategy

### Unit Tests

**Test 1**: Automatic isolation trigger
- File: `tests/unit/test_executor_isolation_trigger.py`
- Cases:
  - Steps with subagent → isolation enabled
  - Steps without subagent → isolation disabled
  - Mixed steps → isolation enabled
  - Config disabled → isolation disabled (even with subagent)

**Test 2**: Metrics aggregation
- File: `tests/unit/test_executor_wave_metrics.py`
- Cases:
  - Sequential wave with 2 tool calls, 1 subagent, no errors
  - Sequential wave with cap hit
  - Sequential wave with errors
  - Parallel wave aggregation
  - Output length measurement

**Test 3**: Reason prompt metrics section
- File: `tests/unit/test_reason_prompt_metrics.py`
- Cases:
  - Wave with metrics → section included
  - No wave executed → section omitted
  - Cap hit status displayed
  - Context percentage formatted

### Integration Tests

**Scenario 1**: Translation goal with isolation
- Goal: "Translate to Chinese"
- Step has subagent → isolated thread
- Metrics: 1 subagent call, 8000 char output
- Reason sees metrics → decides `done`

**Scenario 2**: Research goal with cap hit
- Goal: "Research quantum computing"
- Multiple subagent calls → cap hit
- Metrics: cap_hit=True
- Reason sees cap → decides `replan`

---

## 7. Verification

Run verification after implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- Code formatting check passes
- Linting passes (zero errors)
- All tests pass (including new tests)
- Type checking passes

---

## 8. Implementation Notes

### Context Window Metrics

**Challenge**: Extracting token counts from model responses.

**Current approach**: Estimate from output length (rough proxy).

**Future enhancement**: Extract from AIMessage `usage_metadata` when available. LangChain models provide this in the response object.

**Implementation point**: When CoreAgent returns final AIMessage, extract `usage_metadata.total_tokens` and update state.

### Metrics Accuracy

**Tool calls vs subagent tasks**: Tool calls count all ToolMessage instances. Subagent tasks count root-level `task` tool completions only (as implemented in IG-130).

**Output length**: For sequential waves, combined output length. For parallel waves, max individual step output length (no combined output).

**Error counting**: Failed steps (success=False). Doesn't distinguish error severity.

### Backward Compatibility

**Schema extension**: Adding new optional fields to LoopState with defaults maintains compatibility.

**Prompt changes**: Adding metrics section is additive, doesn't break existing prompt structure.

---

## 9. Success Criteria

After implementation, verify:

1. **Isolation**: Delegation steps automatically isolate, tool-only steps don't
2. **Metrics**: Reason receives structured wave metrics in every iteration
3. **Decisions**: Translation goals complete after one wave (not premature continue)
4. **Tests**: All new tests pass, existing tests unchanged
5. **Verification**: `./scripts/verify_finally.sh` passes

---

## 10. Related Specifications

| RFC/IG | Relevance |
|--------|-----------|
| RFC-201 | Layer 2 agentic goal execution |
| IG-131 | Sequential Act isolated thread pattern |
| IG-130 | Subagent task cap tracking |
| IG-128 | Prior conversation for Reason |
| RFC-203 | Loop working memory (future context window integration) |

---

## 11. Changelog

**2026-04-07 (created)**:
- IG-132 initial draft for RFC-201 completion
- Three phases: isolation trigger, metrics aggregation, Reason prompts
- Detailed implementation plan with code examples
- Test strategy for unit and integration tests