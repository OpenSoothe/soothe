# IG-074: Claude-CLI-Style Agentic Loop Implementation

**Implementation Guide**: IG-074
**Title**: Implement Claude-CLI-Style Agentic Loop with PLAN → ACT → JUDGE
**Created**: 2026-03-27
**Status**: In Progress
**Related**: RFC-0008, RFC-0007, RFC-0012, RFC-0015

## Summary

This guide tracks the implementation of a Claude-CLI-style agentic loop (LoopAgent) that replaces the current `OBSERVE → ACT → VERIFY` sequence with `PLAN → ACT → JUDGE`. The key improvement is using **LLM-based judgment with structured output** instead of text pattern matching, enabling proper evaluation of tool success, goal completion, and strategy adjustment.

## Motivation

### Current Issues

1. **Text pattern matching is unreliable**: Current verification relies on detecting "done", "complete" in response text
2. **No explicit tool success/failure evaluation**: Judge cannot reliably determine if tools succeeded
3. **No strategy adjustment**: Can only continue or stop, not "retry" or "replan"
4. **No failure mode detection**: Missing repeated action detection, hallucination checks, silent failure detection
5. **No structured tool outputs**: Tools return plain strings, making judgment unreliable

### Goals

1. ✅ Replace `OBSERVE → ACT → VERIFY` with `PLAN → ACT → JUDGE`
2. ✅ Add structured schemas for all interactions
3. ✅ Implement LLM-based judge with structured output
4. ✅ Add failure mode detection (repeated actions, hallucinations, silent failures)
5. ✅ Require structured tool outputs
6. ✅ Document control layer as explicit control system

## Architecture

### Three-Layer Loop Model

```
Layer 3: Autonomous Loop (runner, RFC-0007)
  └─> Goal-driven iteration with GoalEngine, max 10 iterations

Layer 2: Agentic Loop (runner, RFC-0008) ← THIS IMPLEMENTATION
  └─> PLAN → ACT → JUDGE reflection loop, max 3 iterations

Layer 1: deepagents Tool Loop (graph, langchain)
  └─> Model → Tools → Model tool-calling loop, recursion_limit=1000
```

### New Control Flow

```python
state = LoopState(goal=user_goal, iteration=0, history=[])
while state.iteration < max_iterations:
    # PLAN: LLM decides next action
    decision = await llm.plan(state)
    if decision.type == "final":
        return decision.answer

    # ACT: Execute tool
    result = await execute_tool(decision.tool, decision.args)

    # JUDGE: LLM evaluates result
    judgment = await llm.judge(state.goal, decision, result)

    # Update state
    state.history.append({decision, result, judgment})
    state.iteration += 1

    # Decide next action based on judgment
    if judgment.status == "done":
        return judgment.final_answer
    elif judgment.status == "retry":
        # Retry with adjustment (use next_hint)
        continue
    elif judgment.status == "replan":
        # Trigger higher-level replan
        continue
    # else: continue loop
```

## Implementation Tasks

### Phase 1: Schema Definitions ✅

**Files**: `src/soothe/core/loop_state.py` (new)

**Tasks**:
- [x] Define `AgentDecision` model (tool call or final answer)
- [x] Define `JudgeResult` model (continue/retry/replan/done)
- [x] Define `ToolOutput` model (success/data/error)
- [x] Define `LoopState` model (goal/iteration/history)
- [x] Define `StepRecord` model (decision/result/judgment)
- [x] Add validation methods
- [x] Add serialization methods

**Acceptance Criteria**:
- ✅ All models pass Pydantic validation
- ✅ Models serialize/deserialize correctly
- ✅ Unit tests pass for all models (25/25 tests passing)

### Phase 2: RFC-0008 Update ✅

**Files**: `docs/specs/RFC-0008-agentic-loop-execution.md`

**Tasks**:
- [x] Replace phase sequence: `OBSERVE → ACT → VERIFY` → `PLAN → ACT → JUDGE`
- [x] Add section: Interfaces & Data Models
- [x] Add section: Control Flow & State Machine
- [x] Add section: Guardrails & Failure Modes
- [x] Add section: Tool Interface Requirements
- [x] Update section: Memory Architecture
- [x] Update section: Event System
- [x] Add section: Control Layer Architecture
- [x] Update diagrams and examples
- [x] Update performance metrics
- [x] Add example execution traces
- [x] Add failure mode examples

**Acceptance Criteria**:
- ✅ RFC clearly documents new loop design
- ✅ All schemas documented with examples
- ✅ Control flow diagrams updated
- ✅ Event system documented
- ✅ Three-layer architecture explained

### Phase 3: Judge Implementation

**Files**: `src/soothe/core/runner/_runner_agentic.py`

**Tasks**:
- [ ] Create `_agentic_judge()` method
- [ ] Design judge prompt template
- [ ] Add structured output parsing with LLM
- [ ] Replace `_evaluate_continuation()` with judge decision
- [ ] Update `_agentic_verify()` to use judge
- [ ] Add judge event emission
- [ ] Handle all judgment statuses (continue/retry/replan/done)

**Acceptance Criteria**:
- Judge uses LLM with structured output
- Text pattern matching removed
- All judgment statuses handled correctly
- Events emitted correctly

### Phase 4: Failure Detection

**Files**: `src/soothe/core/failure_detector.py` (new)

**Tasks**:
- [ ] Implement `FailureDetector` class
- [ ] Add repeated action detection (same tool+args 3x)
- [ ] Add tool hallucination validation
- [ ] Add silent failure detection
- [ ] Add error classification (transient/permanent/user_error)
- [ ] Integrate with agentic loop runner
- [ ] Add failure event emission

**Acceptance Criteria**:
- Repeated actions detected and logged
- Tool hallucinations prevented
- Silent failures caught
- Error types classified correctly

### Phase 5: Tool Output Standardization

**Files**: `src/soothe/tools/base.py` (new)

**Tasks**:
- [ ] Create `SootheToolResult` wrapper class
- [ ] Add middleware to validate tool outputs
- [ ] Add backward compatibility wrapper for string outputs
- [ ] Document tool output requirements in guide
- [ ] Update example tools to use structured output

**Acceptance Criteria**:
- All tools return structured output
- Legacy tools wrapped automatically
- Validation working before judge evaluation

### Phase 6: Event System Update

**Files**: `src/soothe/core/event_catalog.py`, `src/soothe/core/base_events.py`

**Tasks**:
- [ ] Add `AgenticPlanStartedEvent` / `AgenticPlanCompletedEvent`
- [ ] Add `AgenticActStartedEvent` / `AgenticActCompletedEvent`
- [ ] Add `AgenticJudgeStartedEvent` / `AgenticJudgeCompletedEvent`
- [ ] Add `AgenticIterationCompletedEvent`
- [ ] Add `AgenticErrorEvent` (guardrail triggered)
- [ ] Register events in event catalog

**Acceptance Criteria**:
- All new events defined
- Events registered in catalog
- Events emitted at correct phases
- Event fields populated correctly

### Phase 7: Testing & Verification

**Files**: `tests/unit/test_loop_state.py`, `tests/unit/test_failure_detector.py`

**Tasks**:
- [ ] Create unit tests for schema models
- [ ] Create unit tests for failure detector
- [ ] Update agentic loop integration tests
- [ ] Test judge with mock LLM
- [ ] Test failure modes
- [ ] Run `./scripts/verify_finally.sh`
- [ ] Ensure all 900+ tests pass

**Acceptance Criteria**:
- All new code has unit tests
- Integration tests updated
- `./scripts/verify_finally.sh` passes
- Zero linting errors

## Key Design Decisions

### 1. Judge Implementation

**Decision**: Use LLM-based judge with structured output

**Rationale**:
- Text patterns unreliable ("done" can appear in any context)
- LLM can evaluate tool success AND goal completion AND strategy
- Structured output enables proper control flow

**Implementation**:
```python
judge_prompt = f"""
You are the judge for an agent's action.

Goal: {state.goal}
Action taken: {decision}
Result: {result}

Decide whether the agent should continue, retry, replan, or finish.
Output JSON with:
- status: "continue" | "retry" | "replan" | "done"
- reason: explanation
- next_hint: (optional) hint for retry
- final_answer: (if done)
- confidence: 0.0-1.0
"""

judgment = await llm.with_structured_output(JudgeResult).ainvoke(judge_prompt)
```

### 2. Tool Output Schema

**Decision**: Require structured `ToolOutput` for all tools

**Rationale**:
- Judge needs reliable success/failure info
- Silent failures detectable
- Error classification enables retry logic

**Implementation**:
```python
class ToolOutput(BaseModel):
    success: bool
    data: Any
    error: Optional[str] = None
    error_type: Optional[Literal["transient", "permanent", "user_error"]] = None
```

### 3. Failure Detection

**Decision**: Add explicit failure mode detection in control layer

**Rationale**:
- Prevents degenerate loops
- Catches hallucinations
- Enables graceful degradation

**Implementation**:
```python
class FailureDetector:
    def detect_degenerate_retry(self, action_history: list[str]) -> bool:
        """Same action repeated 3+ times."""
        if len(action_history) < 3:
            return False
        last_3 = action_history[-3:]
        return len(set(last_3)) == 1
```

## Verification Checklist

- [ ] RFC-0008 updated with PLAN → ACT → JUDGE
- [ ] Structured schemas defined and validated
- [ ] Judge implementation replaces text pattern matching
- [ ] Failure detection working (repeated actions, hallucinations)
- [ ] Tool output standardization complete
- [ ] All tests passing (`./scripts/verify_finally.sh`)
- [ ] Event emission verified
- [ ] Guardrails tested (max iterations, retries)
- [ ] Zero linting errors
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Judge LLM call adds latency | Medium | Cache judge results, use fast model |
| Tool migration effort | High | Provide backward compatibility wrapper |
| Breaking existing tests | Medium | Update tests incrementally |
| Event schema changes | Low | New events don't conflict with old |

## Success Metrics

- **Judge accuracy**: >90% correct continuation decisions
- **Failure detection**: 100% of degenerate loops caught
- **Tool output compliance**: 100% tools return structured output
- **Test coverage**: >95% for new code
- **Latency**: Judge adds <500ms per iteration

## References

- RFC-0008: Agentic Loop Execution Architecture
- Draft: `docs/drafts/004-rfc-0008-polish-agentic-loop.md`
- Analysis: `/Users/xiamingchen/.claude/plans/polymorphic-sparking-pascal.md`
- DeepAgents docs: Tool execution, memory, events

## Next Steps

1. ✅ Create schema definitions (Phase 1)
2. 🚧 Update RFC-0008 (Phase 2) ← CURRENT
3. Implement judge (Phase 3)
4. Add failure detection (Phase 4)
5. Standardize tool outputs (Phase 5)
6. Update events (Phase 6)
7. Test and verify (Phase 7)

---

**Status Legend**: ✅ Complete | 🚧 In Progress | ⏸️ Pending | ❌ Blocked