# RFC-0008 Implementation Plan

## Current State
- ✅ RFC-0008: Complete specification
- ✅ IG-074: Implementation guide (Phases 1-2 done)
- ✅ Schemas: LoopState, AgentDecision, JudgeResult, ToolOutput
- ✅ JudgeEngine: Implementation exists
- ✅ FailureDetector: Implementation exists
- ✅ Events: Defined in loop_agent/core/events.py
- ❌ **NOT INTEGRATED**: No runtime usage

## Implementation Strategy

### Phase 3: Event System Registration (CURRENT)
**Goal**: Register LoopAgent events in catalog

**Tasks:**
1. Import LoopAgent events into event_catalog.py
2. Register event type constants
3. Update __all__ exports
4. Emit events from runner

**Files:**
- `src/soothe/core/event_catalog.py` (update)
- `src/soothe/cognition/loop_agent/core/events.py` (already exists)

### Phase 4: Runner Integration - PLAN → ACT → JUDGE
**Goal**: Replace OBSERVE → ACT → VERIFY with new loop

**Architecture:**
```python
# Current (old)
_agentic_observe() → _agentic_act() → _agentic_verify()

# New (RFC-0008)
_agentic_loop():
    while iteration < max_iterations:
        # PLAN: LLM decides action
        decision = await _agentic_plan()

        if decision.type == "final":
            return decision.answer

        # ACT: Execute tool
        result = await _agentic_act(decision)

        # JUDGE: Evaluate result
        judgment = await _agentic_judge(decision, result)

        # Update state
        state.record_step(decision, result, judgment)

        # Handle judgment
        if judgment.status == "done":
            return judgment.final_answer
        elif judgment.status == "retry":
            # Adjust and retry
            continue
        elif judgment.status == "replan":
            # Trigger replan
            continue
```

**Tasks:**
1. Create `_agentic_plan()` method
   - Use LLM with structured output (AgentDecision)
   - Emit PlanPhaseStartedEvent/CompletedEvent
   - Handle tool vs final decision

2. Update `_agentic_act()` method
   - Accept AgentDecision parameter
   - Execute tool with structured output
   - Emit ActPhaseStartedEvent/CompletedEvent
   - Return ToolOutput

3. Create `_agentic_judge()` method
   - Use JudgeEngine with structured output
   - Emit JudgePhaseStartedEvent/CompletedEvent
   - Return JudgeResult

4. Add FailureDetector integration
   - Check before each iteration
   - Emit GuardrailTriggeredEvent
   - Handle degenerate retries

5. Update state management
   - Use LoopState from loop_agent
   - Track history with StepRecord
   - Emit IterationStartedEvent/CompletedEvent

**Files:**
- `src/soothe/core/runner/_runner_agentic.py` (major refactor)

### Phase 5: Tool Output Standardization
**Goal**: All tools return ToolOutput

**Tasks:**
1. Create `SootheToolMiddleware` wrapper
2. Convert string outputs to ToolOutput
3. Validate structured outputs
4. Add backward compatibility

**Files:**
- `src/soothe/middleware/tool_output.py` (create)
- `src/soothe/core/agent.py` (integrate middleware)

### Phase 6: Testing
**Goal**: Comprehensive test coverage

**Tasks:**
1. Unit tests for schemas (existing)
2. Unit tests for JudgeEngine
3. Unit tests for FailureDetector
4. Integration tests for runner
5. Mock LLM for judge tests
6. Verify all 900+ tests pass

**Files:**
- `tests/unit/test_loop_agent_schemas.py` (update)
- `tests/unit/test_judge_engine.py` (create)
- `tests/unit/test_failure_detector.py` (create)
- `tests/integration/test_agentic_loop.py` (create)

## Execution Order
1. ✅ Create implementation plan
2. 🚧 Register events (Phase 3) ← CURRENT
3. Integrate JudgeEngine and FailureDetector (Phase 4)
4. Refactor runner to PLAN → ACT → JUDGE (Phase 4)
5. Add tool output middleware (Phase 5)
6. Write tests (Phase 6)
7. Run `./scripts/verify_finally.sh`
8. Document changes

## Success Criteria
- ✅ RFC-0008 fully implemented
- ✅ PLAN → ACT → JUDGE replaces OBSERVE → ACT → VERIFY
- ✅ JudgeEngine integrated with structured output
- ✅ FailureDetector prevents degenerate loops
- ✅ All events use `soothe.cognition.loop.*` namespace
- ✅ All 900+ tests pass
- ✅ Zero linting errors
- ✅ Judge accuracy >90% (validated in tests)