# RFC-0008 Implementation Status & Next Steps

## What I've Completed

### Phase 3: Event System ✅ DONE
1. ✅ LoopAgent events already defined in `loop_agent/core/events.py`
2. ✅ Added import to event_catalog.py for self-registration
3. ✅ Added self-registration function to events.py
4. ✅ Events will auto-register at module import time

**Files Modified:**
- `src/soothe/core/event_catalog.py` - Added loop_agent events import
- `src/soothe/cognition/loop_agent/core/events.py` - Added _register_events()

## What Remains: Phase 4-7

### Phase 4: Judge Integration (CURRENT)

**Goal:** Replace text pattern matching with LLM-based judgment

**This requires a major refactoring of `_runner_agentic.py`:**

#### Current Architecture (OLD):
```
_run_agentic_loop():
    while iteration < max_iterations:
        _agentic_observe()     # Gather context
        _agentic_act()          # Execute action
        _agentic_verify()       # Text pattern matching
        if should_continue:
            iteration++
```

#### New Architecture (RFC-0008):
```
_run_agentic_loop():
    Initialize LoopState, FailureDetector

    while iteration < max_iterations:
        # PLAN: LLM decides action
        decision = _agentic_plan(state)
        if decision.type == "final":
            return decision.answer

        # ACT: Execute tool
        result = _agentic_act(decision)

        # JUDGE: LLM evaluates result
        judgment = _agentic_judge(state, decision, result)

        # Update state
        state.record_step(decision, result, judgment)

        # Check guardrails
        failure = FailureDetector.check(state, decision, result)
        if failure:
            handle_failure()

        # Handle judgment
        if judgment.status == "done":
            return judgment.final_answer
        elif judgment.status == "retry":
            adjust_and_continue()
        elif judgment.status == "replan":
            trigger_replan()
```

**Key Changes Needed:**

1. **New `_agentic_plan()` method**:
   - Use LLM with structured output (AgentDecision)
   - Support tool calls and final answers
   - Emit PlanPhaseStartedEvent/CompletedEvent

2. **Update `_agentic_act()` method**:
   - Accept `AgentDecision` parameter (instead of planning internally)
   - Return `ToolOutput` (structured)
   - Simplify: just execute the tool

3. **Replace `_agentic_verify()` with `_agentic_judge()`**:
   - Use JudgeEngine instead of text patterns
   - Return structured `JudgeResult`
   - Support all statuses: continue/retry/replan/done

4. **Add FailureDetector integration**:
   - Initialize at loop start
   - Check before each iteration
   - Emit GuardrailTriggeredEvent

5. **State Management**:
   - Use `LoopState` from `loop_agent.core.state`
   - Track `StepRecord` for each iteration
   - Pass state to judge/failure detector

**Estimated Work:** 4-6 hours of focused implementation

### Phase 5: Tool Output Standardization
- Create middleware wrapper
- Convert string outputs to ToolOutput
- Backward compatibility

### Phase 6: Testing
- Unit tests for JudgeEngine
- Unit tests for FailureDetector
- Integration tests
- Verify all 900+ tests pass

## Recommendation

Given the scope of Phase 4, I recommend:

**Option 1: Incremental Implementation** (RECOMMENDED)
- Keep current `_run_agentic_loop()` as-is
- Create NEW method `_run_agentic_loop_v2()` with PLAN→ACT→JUDGE
- Add config flag to switch between old/new
- Gradually migrate and test
- Remove old version once validated

**Benefits:**
- Low risk: old implementation still works
- Easy to test new implementation
- Can A/B compare behavior
- Gradual rollout

**Option 2: Complete Refactor** (HIGHER RISK)
- Completely rewrite `_runner_agentic.py`
- Risk of breaking existing behavior
- Requires extensive testing
- All-or-nothing deployment

**Option 3: Parallel Implementation**
- Create new file `_runner_agentic_v2.py`
- Import and use based on config
- Keep old code untouched
- Delete old file when ready

## My Recommendation

I suggest **Option 1 (Incremental)** with this approach:

1. Add a boolean flag in config: `agentic.use_judge_engine: false`
2. Create `_agentic_plan()` and `_agentic_judge()` methods
3. Modify `_run_agentic_loop()` to branch based on flag
4. Test with flag=true in development
5. Enable by default after validation
6. Remove old code in next release

This allows us to complete the RFC-0008 implementation safely while maintaining system stability.

## Next Steps

Please let me know which approach you prefer:

A. **Incremental** - Add new logic alongside old (safest, recommended)
B. **Complete Refactor** - Replace everything now (riskier, faster)
C. **Pause** - Stop here and review what's done before continuing

What would you like me to do?