# Layer 2 Context Isolation and Execution Bounds Design

**Status**: Approved for implementation
**Created**: 2026-04-07
**Updated**: 2026-04-07 (refactored with complete decisions)

## Overview

This design addresses four contamination problems in Layer 2 agentic loops through a unified strategy: clean delegation boundaries, bounded execution, metrics-driven Reason decisions, and output contract enforcement.

## Problem Statement

### Root Causes of Contamination

The duplicate output and cross-wave contamination problems stem from:

1. **L1 unbounded ReAct** — CoreAgent allows unlimited tool_call → think → tool_call cycles
2. **L2 multi-iteration** — AgentLoop Reason may `continue` after satisfactory Act output
3. **Full thread context** — Act steps share same thread, seeing all prior messages
4. **Main model repetition** — LLM tendency to paste tool output verbatim after delegation

### Active Problem Symptoms

| Problem | Example | Impact |
|---------|---------|--------|
| Same-wave duplicate calls | Step calls `subagent.claude`; LLM sees ToolMessage and calls again with different params | Wasted compute, duplicate content |
| Cross-wave contamination | Wave 1 `research` produces long output; Wave 2 `translate` sees it and misjudges language | Wrong behavior, re-invocation |
| Prior assistant confusion | User says "translate to Chinese" after English output; subagent sees prior Chinese from earlier turns | Language detection failure |
| Output duplication | Subagent output streamed to TUI; main model repeats it verbatim | User sees same content twice |
| Premature continue | Act produces 8000 char Chinese translation; Reason decides `continue` + summarize | Wasted iteration, duplicate effort |

---

## Architecture

### Core Strategy: Clean Delegation Boundaries

Four integrated mechanisms solve contamination:

1. **Thread isolation for delegation** (automatic, semantic rule)
2. **Bounded execution per wave** (soft prompt + hard cap)
3. **Metrics-driven Reason** (structured evidence for decisions)
4. **Output contract enforcement** (suffix + informed Reason)

Each mechanism reinforces the others: isolation prevents contamination, bounds prevent runaway loops, metrics help Reason make better decisions, output contract prevents duplication.

---

## Component 1: Payload Isolation System

### Isolation Mechanism

**Decision**: Thread isolation (fresh checkpoint branch)

**Rationale**:
- Already partially implemented (IG-131)
- Clearer semantics than message injection middleware
- Delegation is autonomous task execution on explicit input
- Tool-only steps naturally use full thread context

### Trigger Logic

**Decision**: Automatic when `StepAction.subagent` field is set

**Semantic rule**:
- Delegation steps (subagent specified) → isolated thread execution
- Non-delegation steps (tool-only) → full thread context
- No explicit isolation level field in schema needed

**Why this approach**:
- Subagent field already marks delegation intent in planner output
- Clear boundary: delegation is autonomous, tools are reasoning extensions
- Automatic - no configuration or planner decision overhead
- Aligns with existing executor pattern

### Implementation Pattern

**Thread naming**:
- Parallel steps: `{thread_id}__step_{i}` (existing pattern)
- Sequential delegation: `{thread_id}__l2act{uuid}` (new pattern from IG-131)
- Sequential tool-only: canonical `thread_id`

**Execution flow**:
1. Executor checks `step.subagent` field
2. If set: create isolated child thread `{thread_id}__l2act{uuid}`
3. Run CoreAgent on child thread
4. On success: merge messages back to canonical thread via `aupdate_state`
5. On failure: no merge, error propagates to Reason

**Merge behavior** (from IG-131):
```python
# Executor._merge_isolated_act_into_parent_thread
snap = await graph.aget_state({"configurable": {"thread_id": child_thread_id}})
msgs = snap.values.get("messages")
await graph.aupdate_state(
    {"configurable": {"thread_id": parent_thread_id}},
    {"messages": list(msgs)}
)
```

### Configuration

**Settings** (from IG-131, refined):
- `sequential_act_isolated_thread`: master switch (default `true`)
- `sequential_act_isolate_when_step_subagent_hint`: conditional logic (default `true`)
  - When `true`: isolate only if at least one step has subagent field
  - When `false`: isolate every sequential wave (over-isolation)

**Recommendation**: Enable both flags. Isolation should be selective based on delegation intent.

### What Subagent Receives

**Minimal payload content**:
- Step description text (explicit task)
- Expected output hint from `StepAction.expected_output`
- System prompt prefix (standard framework context)
- Working memory if enabled (RFC-203)

**What subagent does NOT receive**:
- Prior Human/Assistant turns from thread
- Previous wave outputs
- Earlier step results
- Checkpoint history

**Result**: Delegation is clean execution on explicit input without contamination from prior conversation.

---

## Component 2: Execution Wave Bounds

### Two-Layer Constraint

**Decision**: Combined soft + hard constraint

**Soft constraint (prompt/schema)**:
- Plan schema defines: "one delegation step = one subagent call"
- Retry/re-parameterization requires explicit second step with `depends_on`
- Improves observability: each subagent call is a distinct plan unit

**Hard constraint (execution limit)**:
- `max_subagent_tasks_per_wave` cap (default 2)
- Stops Act stream when root-level `task` tool completions exceed cap
- Safety net for runaway loops, model confusion, or retry storms

**Why combined**:
- Soft alone: model may ignore, unlimited calls possible
- Hard alone: opaque truncation, Reason doesn't understand why
- Combined: clear semantics + safety net + Reason awareness

### Cap Hit Behavior

**Metrics signal** (not error):
- Executor sets `StepResult.hit_subagent_cap=True`
- `subagent_task_completions` count recorded
- Metrics flow to Reason via `LoopState` fields
- Not treated as execution failure

**Reason decision with cap signal**:
- Reason sees `last_wave_hit_subagent_cap=True`
- Understands: wave was bounded, may have partial completion
- Options:
  - `replan`: adjust strategy, break into smaller steps
  - `continue`: accept partial results, proceed to next phase
  - `done`: if partial output satisfies goal despite cap

**Why metrics signal**:
- Graceful degradation, not hard failure
- Reason adapts strategy based on evidence
- Cap is safety net, not primary execution control

### Implementation Details

**Budget tracking** (from executor):
```python
class _ActStreamBudget:
    max_subagent_tasks_per_wave: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
```

**Stream interruption**:
- During `_stream_and_collect`, count root-level `task` tool ToolMessages
- When completions > cap: stop consuming stream, set `hit_subagent_cap=True`
- Return partial output collected so far

**StepResult propagation**:
- Only first step in sequential wave gets metrics (credit attribution)
- Other steps get zero counts (shared wave execution)

---

## Component 3: Reason Decision Enhancement

### Metrics-Driven Approach

**Decision**: Metrics-only (no goal-type classification)

**Rationale**:
- Soothe is a general agent framework
- Narrow categories (translate, research, generate) don't cover diverse scenarios
- Model can infer intent from goal text + metrics pattern
- More flexible than rigid routing

### Structured Metrics for Reason

**Wave execution metrics**:
- `last_wave_tool_call_count`: total tool invocations
- `last_wave_subagent_task_count`: subagent delegation depth
- `last_wave_hit_subagent_cap`: bounded execution signal
- `last_wave_output_length`: output magnitude (chars)
- `last_wave_error_count`: tool/subagent failures in wave

**Context window metrics**:
- `total_tokens_used`: cumulative usage
- `context_percentage_consumed`: budget awareness
- `incremental_percent`: wave-level cost

### Reason Prompt Enhancement

**Evidence presentation**:
```
<SOOTHE_WAVE_METRICS>
Last Act wave completed:
- Subagent calls: 1
- Tool calls: 2
- Output length: 8000 characters
- Errors: 0
- Context used: 15% (8,000 / 200,000 tokens)
- Cap hit: No
</SOOTHE_WAVE_METRICS>
```

**Decision logic** (model-driven):
- Translation: sees "translate to Chinese" + 8000 char output + no cap + no errors → infers `done`
- Research: sees "research X" + 3 subagent calls + cap hit + partial output → infers `replan`
- Multi-phase: sees "implement feature" + 1 subagent call + 2000 char output + cap not hit → infers `continue`

### LoopState Integration

**Schema additions**:
```python
class LoopState(BaseModel):
    # Existing wave metrics (from IG-130)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False

    # New metrics (this design)
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0
```

**Executor aggregation**:
- After each Act wave, executor aggregates metrics from `StepResult` objects
- Updates `LoopState` before Reason phase
- Reason reads from state before LLM call

---

## Component 4: Output Contract System

### Current Implementation

**Layer 2 output contract suffix** (already implemented):
```xml
<SOOTHE_LAYER2_OUTPUT_CONTRACT>
- After tool or subagent results arrive, add at most two short wrap-up sentences.
- Do NOT paste the full tool/subagent output again.
- If the tool output already satisfies the user-visible deliverable, stop there.
</SOOTHE_LAYER2_OUTPUT_CONTRACT>
```

**Activation**: Config flag `layer2_output_contract_enabled` (default `true`)

### Enhancement via Better Reason Decisions

**Primary mechanism**: Metrics-driven Reason prevents premature `continue`

**Why this works**:
- Output duplication often happens when Reason decides `continue` after satisfactory output
- Model then produces summary that repeats streamed content
- Better metrics prevent premature continue → no duplication trigger

**Example**:
- Wave 1: subagent produces 8000 char Chinese translation
- Reason (old): truncated evidence only → decides `continue` + summarize → duplication
- Reason (enhanced): sees metrics (8000 chars, 1 subagent call, no cap) → decides `done` → no duplication

### Why Not Post-Process Dedup

**Post-process deduplication** (rejected):
- Reactive cleanup at TUI/CLI level
- Similarity comparison between main output and ToolMessage
- Computationally expensive, latency overhead
- May truncate legitimate synthesis

**Proactive prevention** (chosen):
- Better Reason decisions upstream
- Metrics inform done/continue choice
- Output contract suffix as baseline guard
- Cleaner than reactive patching

---

## Integration Architecture

### Data Flow

```
Planner → StepAction (subagent field)
           ↓
Executor → check subagent field
           ↓
    [delegation?] → isolate thread → execute → merge
    [tool-only?] → full thread → execute
           ↓
Executor → aggregate metrics → StepResult
           ↓
LoopState → wave metrics fields
           ↓
Reason → read metrics → build prompt → LLM decision
           ↓
ReasonResult → done/continue/replan
           ↓
AgentLoop → next iteration or exit
```

### Executor Changes

**Thread isolation trigger**:
```python
def _should_use_isolated_thread(self, steps: list) -> bool:
    if not self._config.sequential_act_isolated_thread:
        return False
    if self._config.sequential_act_isolate_when_step_subagent_hint:
        return any(step.subagent for step in steps)
    return True  # isolate all waves (over-isolation)
```

**Metrics aggregation**:
```python
async def _execute_sequential_chunk(self, steps, state):
    # ... execute wave ...
    for sr in self._step_results_for_chunk(
        steps,
        subagent_task_completions=budget.subagent_task_completions,
        hit_subagent_cap=budget.hit_subagent_cap,
        # ...
    ):
        yield sr

    # Update LoopState metrics after wave
    state.last_wave_output_length = len(output)
    state.last_wave_error_count = sum(1 for r in results if not r.success)
```

### Reason Changes

**Prompt building**:
```python
def build_loop_reason_prompt(goal, state, context):
    # ... existing logic ...

    if state.last_wave_tool_call_count > 0:
        metrics_text = f"""
<SOOTHE_WAVE_METRICS>
Last wave: {state.last_wave_tool_call_count} tool calls,
{state.last_wave_subagent_task_count} subagent calls,
{state.last_wave_output_length} chars output,
{state.last_wave_error_count} errors.
Cap hit: {state.last_wave_hit_subagent_cap}
Context: {state.context_percentage_consumed:.1%} used
</SOOTHE_WAVE_METRICS>
"""
        prompt_parts.append(metrics_text)

    # ... goal text, prior conversation ...
```

**Evidence handling** (existing truncation logic from IG-128 preserved):
- Model-supplied evidence truncated to 600 chars
- Prefer compact step-derived evidence when model output is verbose

---

## Files Affected

| Module | Path | Changes |
|--------|------|---------|
| Executor | `cognition/agent_loop/executor.py` | Thread isolation trigger logic, metrics aggregation |
| Reason | `cognition/agent_loop/reason.py` | Metrics-aware prompt building |
| LoopState | `cognition/agent_loop/schemas.py` | New metric fields (output_length, error_count, context_window) |
| AgentLoop | `cognition/agent_loop/loop_agent.py` | Metrics aggregation coordinator |
| Config | `config/models.py` | Cap defaults, isolation flags refinement |
| Planner | `cognition/planning/simple.py` | Clear step semantics in schema/prompt |

---

## Implementation Status

### Already Implemented

| Component | IG Reference | Status |
|-----------|--------------|--------|
| Thread isolation pattern | IG-131 | ✅ Implemented |
| Subagent task cap tracking | IG-130 | ✅ Implemented |
| Output contract suffix | IG-119 | ✅ Implemented |
| Prior conversation for Reason | IG-128 | ✅ Implemented |
| TUI debug trace | IG-129 | ✅ Implemented |

### Remaining Work

| Task | Scope |
|------|-------|
| Automatic isolation trigger | Executor logic: check `step.subagent` field |
| Metrics aggregation in executor | Output length, error count, context window tracking |
| Reason metrics-aware prompts | Build `<SOOTHE_WAVE_METRICS>` section |
| LoopState schema additions | New metric fields |
| Step semantics documentation | Planner schema/prompt refinement (soft constraint) |

---

## Verification Scenarios

### Scenario 1: Translation with Isolation

**Goal**: "Translate this English text to Chinese"

**Expected behavior**:
1. Reason creates plan: one delegation step `subagent.claude` with task text
2. Executor sees `step.subagent` → isolates thread `{thread_id}__l2act{uuid}`
3. Subagent receives only translation task (no prior conversation)
4. Subagent produces 8000 char Chinese output
5. Executor aggregates: `output_length=8000`, `subagent_task_count=1`, `cap_hit=False`
6. Reason sees metrics + goal → decides `done` (no premature continue)
7. TUI shows subagent stream once, main model adds brief summary → no duplication

**Success criteria**: No cross-wave contamination, no duplicate output, clean done decision

---

### Scenario 2: Research with Cap Hit

**Goal**: "Research the latest developments in quantum computing"

**Expected behavior**:
1. Reason creates plan: delegation steps for research
2. Executor runs first wave: subagent calls (hits cap at 2)
3. Executor sets `hit_subagent_cap=True`, returns partial output
4. Metrics: `subagent_task_count=2`, `cap_hit=True`, `output_length=5000`
5. Reason sees cap signal → decides `replan` with adjusted strategy
6. Next iteration uses smaller steps, avoids cap
7. Eventually `done` with accumulated research

**Success criteria**: Cap prevents runaway loops, Reason adapts strategy gracefully

---

### Scenario 3: Multi-Step Plan with Mixed Isolation

**Goal**: "Analyze the data and generate a report"

**Expected behavior**:
1. Plan has 3 steps: analyze (subagent), format (tool-only), summarize (subagent)
2. Executor runs sequentially:
   - Step 1: `subagent` set → isolated thread → analyze data
   - Step 2: no `subagent` → full thread → format with analyze context
   - Step 3: `subagent` set → new isolated thread → summarize task
3. Step 2 sees Step 1 output (full thread), Step 3 doesn't see prior (isolated)
4. Each delegation is clean, tool-only step has context

**Success criteria**: Delegation isolated, tool steps have context, correct information flow

---

### Scenario 4: Follow-Up Goal

**Goal**: First conversation: "Write a Python function for X", second: "Translate the function comments to Chinese"

**Expected behavior**:
1. First goal completes: Python code in thread
2. Second goal starts: Reason sees prior conversation excerpts (IG-128)
3. Plan: delegation step for translation
4. Executor isolates thread → subagent sees only "translate these comments: ..."
5. Subagent doesn't see full prior Python code (clean delegation)
6. Translation succeeds without prior assistant confusion

**Success criteria**: Follow-up delegation isolated from earlier turns

---

## Configuration Reference

```yaml
agentic:
  # Thread isolation for sequential Act
  sequential_act_isolated_thread: true
  sequential_act_isolate_when_step_subagent_hint: true

  # Execution bounds
  max_subagent_tasks_per_wave: 2  # safety cap

  # Output contract
  layer2_output_contract_enabled: true
```

**Recommended defaults**: All enabled, cap=2, isolation conditional on subagent hint.

---

## Caveats and Trade-offs

### Thread Isolation Overhead

**Impact**: Orphan child checkpoints accumulate until cleanup job exists

**Mitigation**: SQLite checkpoint storage handles reasonable volume. Future: periodic cleanup task.

### Cap May Truncate Legitimate Multi-Step

**Impact**: Complex delegation (research → summarize) may hit cap mid-flow

**Mitigation**: Cap is safety net, not primary control. Reason sees cap signal and replans. Soft constraint (explicit steps) should be primary mechanism.

### Metrics Collection Cost

**Impact**: Token counting adds overhead to each wave

**Mitigation**: Use model response `usage_metadata` when available. Otherwise estimate from message lengths. Lightweight aggregation.

### Subagent May Need Context

**Impact**: Some delegation tasks legitimately need prior conversation

**Mitigation**:
- Planner can pass context via step description: "Given prior analysis X, now do Y"
- Working memory (RFC-203) provides scoped context injection
- Rare cases: use tool-only step instead of delegation

---

## Design Rationale Summary

### Why Thread Isolation

- Clear semantics: delegation is autonomous execution
- Already implemented: IG-131 provides infrastructure
- Avoids message injection complexity
- Contamination prevention is architectural, not reactive

### Why Combined Cap

- Soft constraint: observability and plan clarity
- Hard cap: safety net for edge cases
- Metrics signal: graceful degradation, Reason adapts

### Why Metrics-Only Reason

- General agent: no narrow goal-type categories
- Flexible: model infers intent from goal text + metrics pattern
- Evidence-driven: structured metrics beyond truncated summary

### Why Output Contract + Metrics

- Proactive: better Reason decisions prevent duplication trigger
- Baseline: suffix provides guard rail
- Cleaner: no reactive post-process dedup

---

## Next Steps

1. Implement executor thread isolation trigger logic
2. Add metrics aggregation in executor (output_length, error_count, context)
3. Extend LoopState schema with new metric fields
4. Build metrics-aware Reason prompt section
5. Document step semantics in planner schema/prompt
6. Verification: run scenarios and confirm contamination solved

---

## Related Specifications

| RFC/IG | Relevance |
|--------|-----------|
| RFC-200 | Layer 2 agentic goal execution |
| IG-131 | Sequential Act isolated thread pattern |
| IG-130 | Subagent task cap tracking |
| IG-128 | Prior conversation for Reason |
| IG-119 | Output contract and duplicate stdout |
| RFC-203 | Loop working memory (scoped context injection) |

---

## Changelog

**2026-04-07 (refactored)**:
- Completed missing design decisions across all four components
- Clarified isolation trigger logic (automatic via subagent field)
- Removed goal-type classification, adopted metrics-only approach
- Defined Reason metrics set including error count and context window
- Documented integration architecture and data flow
- Added verification scenarios with success criteria
- Clarified remaining implementation work vs already completed

**2026-04-07 (initial draft)**:
- Identified contamination problems and optimization directions
- Discussed trade-offs without final decisions
- Noted implementation work in progress