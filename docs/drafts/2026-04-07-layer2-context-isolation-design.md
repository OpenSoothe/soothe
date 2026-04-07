# Layer 2 Context Isolation and Output Contract Design

## Problem Statement

### Root Causes of Duplicate Output

The duplicate output problem is not TUI-specific. It stems from the interaction of:

1. **L1 unbounded ReAct** — CoreAgent allows unlimited tool_call → think → tool_call cycles within one `astream()` invocation
2. **L2 multi-iteration** — LoopAgent Reason may `continue` after Act produces satisfactory output, triggering another wave
3. **Full thread context** — Act steps share the same LangGraph thread, seeing all prior messages including previous wave outputs
4. **Main model repetition** — LLM tendency to summarize/paste tool output verbatim after delegation completes

### Contamination Scenarios

| Scenario | Example | Impact |
|----------|---------|--------|
| Same-wave double call | Step 1 calls `subagent.claude`; LLM sees ToolMessage and calls it again with different params | Wasted compute, duplicate content |
| Cross-wave contamination | Wave 1 `research` produces long output; Wave 2 `translate` sees it and misjudges language | Wrong behavior, re-invocation |
| Prior assistant confusion | User says "translate to Chinese" after English output; subagent sees prior Chinese from earlier turns | Language detection failure |
| Output repetition | Main model pastes full tool output after it already streamed through TUI | User sees same content twice |

---

## Optimization Directions

### B. Layer 2 Step Semantics Contract

**Goal**: Tighten what "one step" can do — prevent unlimited subagent calls within a single Act wave.

**Current behavior**: Sequential wave is one `astream()` with unbounded internal rounds. Executor only counts, doesn't cap.

**Options**:

1. **Plan constraint (soft)** — Prompt/schema defines: delegation step = one call; retry/re-param = explicit second step with `depends_on`
2. **Execution cap (hard)** — `max_subagent_tasks_per_wave` budget per Act stream; hit cap → early termination, partial results to Reason
3. **Combined** — Soft constraint via prompt, hard cap as safety net

**Trade-offs**:
- Cap may truncate useful multi-step delegation (e.g., research → summarize)
- Requires Reason to handle "partial completion" gracefully
- Explicit second step improves observability but increases plan complexity

---

### C. Layer 1 Payload Isolation (Data Plane)

**Goal**: Delegated subagents receive only explicit task payload, not full thread history.

**Current behavior**: Subagent calls inherit entire thread messages from `RunnableConfig.thread_id`.

**Isolation levels** (discussed):

| Level | Content | Use case |
|-------|---------|----------|
| Minimal payload only | Explicit task input (e.g., "translate: ...") | Translation, short transforms |
| Minimal + step context | Payload + goal/expected_output metadata | Research with scope hints |
| Minimal + filtered thread | Payload + messages with content stripped to headers | Tasks needing conversation context |
| Configurable per-step | Each `StepSpec` declares isolation level | Unified mechanism, flexibility |

**Implementation vectors**:

1. **Thread isolation** — Already exists for parallel steps (`{tid}__step_{i}`) and optional sequential isolation (`{tid}__l2act{uuid}`)
2. **Message injection** — Middleware injects isolated `messages` list into config for delegation steps
3. **System prefix** — "This is the only input. Do not assume prior content in thread."

**Trade-offs**:
- Thread isolation creates orphaned checkpoint branches; requires merge logic
- Message injection works at middleware level but may conflict with existing `ExecutionHintsMiddleware`
- Subagent may legitimately need prior context (e.g., follow-up on earlier finding)

---

### D. Reason Evidence and Done Strategy

**Goal**: Reduce unnecessary `continue` after Act produces satisfactory output.

**Current behavior**: Reason receives truncated `evidence_summary` (600 chars), decides via LLM judgment.

**Improvement vectors**:

1. **Structured metrics** — Reason receives `last_wave_tool_call_count`, `last_wave_subagent_task_count`, `hit_subagent_cap`, output length
2. **Goal-type alignment** — Classifier tags goal (translate, research, generate); Reason prompt varies by type
3. **Done detection** — "translate → subagent returns Chinese" → prefer `done` over `continue`

**Example**:
```
Goal: "翻译为中文"
Wave 1: subagent.claude → 8000 char Chinese output
Metrics: tool_calls=1, subagent_tasks=1, output_len=8000, language_match=true
Reason decision: done (not continue + summary)
```

**Trade-offs**:
- Requires goal type classification (additional routing complexity)
- May prematurely terminate legitimate multi-phase goals
- Language/content matching adds validation cost

---

### E. Output Contract: Main Model vs Subagent

**Goal**: Define who "faces the user" for delegation steps.

**Current behavior**: Layer 2 output contract suffix discourages repetition, but main model may still paste.

**Options**:

1. **Subagent owns content** — ToolMessage/subagent result is user-visible; main model limited to one-sentence `user_summary`
2. **Post-process truncation** — Detect long AIMessage after ToolMessage; strip repeated content
3. **Similarity dedup** — Hash/LCS comparison between main output and last ToolMessage; suppress overlap

**Trade-offs**:
- Subagent ownership conflicts with deepagents behavior (main model always produces AIMessage)
- Post-process adds latency; may truncate legitimate synthesis
- Similarity dedup computationally expensive; works best as TUI fallback

---

## Key Architectural Decisions

### 1. Isolation Mechanism Choice

**Recommendation**: **Configurable per-step isolation level** with **minimal payload as default** for delegation steps.

- Delegation steps (subagent specified) default to payload-only
- Non-delegation steps inherit thread context
- `StepSpec.isolation_level: "payload" | "filtered" | "full"` overrides default

### 2. Implementation Location

**Payload isolation**: `ExecutionHintsMiddleware` or new `IsolationMiddleware` in Layer 1

**Step-level control**: Executor reads `StepSpec.isolation_level`, passes flag to `RunnableConfig.configurable`

**Thread isolation**: Existing mechanism for parallel; optional for sequential via `sequential_act_isolated_thread` config

### 3. Evidence Strategy

**Recommendation**: **Structured metrics + goal-type hint** to Reason

- Reason receives wave metrics (counts, cap hit, output length)
- Goal classifier tags intent (translate, research, generate, edit)
- Reason prompt template varies by goal type

### 4. Step Semantics Cap

**Recommendation**: **Combined soft + hard constraint**

- Plan schema: one delegation = one call; retry = new step
- Configurable `max_subagent_tasks_per_wave` cap (default 2)
- Cap hit → early termination, metrics signal to Reason

---

## Files Affected

| Module | Path | Changes |
|--------|------|---------|
| Executor | `cognition/loop_agent/executor.py` | Isolation level enforcement, cap handling |
| Reason | `cognition/loop_agent/reason.py` | Metrics collection, goal-type prompts |
| Schemas | `cognition/loop_agent/schemas.py` | `StepSpec.isolation_level`, `ReasonResult.metrics` |
| LoopAgent | `cognition/loop_agent/loop_agent.py` | Wave metrics aggregation |
| Middleware | `core/middleware/` | New isolation middleware or hints extension |
| Config | `config/models.py` | Isolation defaults, cap config |
| SimplePlanner | `backends/planning/simple.py` | Plan schema update, step isolation declaration |

---

## Verification

After implementation:
1. Translation goal → one subagent call, no prior context, Reason `done`
2. Research goal → subagent sees filtered context or minimal + metadata
3. Multi-step plan → cap hit handled gracefully, Reason can `replan`
4. TUI → no duplicate content between main stream and subagent embed

---

## Status

**Draft for future reference**. Not yet approved for implementation.

Next steps:
1. Validate isolation level granularity with concrete use cases
2. Design middleware implementation details
3. Plan Reason prompt templates for goal types
4. Prototype one scenario (e.g., translation payload isolation)