# Reason Phase Robustness Design (Three-Layer Defense)

**Date**: 2026-04-11
**Status**: Draft
**Scope**: Prevent JSON truncation in structured output via schema simplification, query splitting, and fallback

---

## Problem Statement

### JSON Truncation in Reason Phase

**Provider**: DashScope/Kimi (OpenAI-compatible endpoint)
**Model**: `kimi-k2.5`

**Symptoms**:
```
ValidationError: 1 validation error for ReasonResult
  Invalid JSON: EOF while parsing a string at line 1 column 2644
  [type=json_invalid, input_value='{"goal_progress":0.95,"e... Directory Structure\\n\\n', input_type=str]
```

**Root Cause Analysis**:
- ReasonResult schema is large: `reasoning` field unlimited, `decision.steps` can have many entries
- Estimated output tokens: 1500-3000 tokens (reasoning field alone ~500-2000 tokens)
- Provider truncates JSON at ~1500-5000 chars mid-string
- Current 3-tier retry + fallback fails to handle truncation

**Current ReasonResult Schema**:
```python
class ReasonResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    evidence_summary: str = ""                    # Optional
    goal_progress: float = Field(default=0.0)     # Required
    confidence: float = Field(default=0.8)        # Required
    reasoning: str = ""                           # Unlimited length ❌
    soothe_next_action: str = ""                  # Unlimited length ❌
    progress_detail: str | None = None            # Optional, rarely used ❌
    plan_action: Literal["keep", "new"]           # Required
    decision: AgentDecision | None                # Complex nested schema
    full_output: str | None = None                # Optional
```

**Problem**: Schema is too complex for single LLM call, exceeds provider token limits.

---

## Solution: Three-Layer Defense Strategy

### Layer 1: Schema Diet (Reduce Output Size)

**Goal**: Simplify ReasonResult schema to reduce token count by ~40-60%.

**Changes**:

1. **Truncate `reasoning` field** (largest contributor):
   ```python
   # Before: unlimited
   reasoning: str = ""
   
   # After: max 500 chars
   reasoning: str = Field(default="", max_length=500)
   ```
   
   **Justification**:
   - Currently used only for debug logging (truncated to 200 chars at line 1117)
   - Stored in checkpoint metadata (internal use)
   - No user-facing display
   - Token savings: ~1500-1800 tokens
   
2. **Remove `progress_detail` field**:
   ```python
   # Before: optional but in schema
   progress_detail: str | None = None
   
   # After: removed entirely
   # (field deleted from ReasonResult)
   ```
   
   **Justification**:
   - Optional field, rarely populated by model
   - User-facing but low value (`next_action` is primary)
   - No core logic depends on it
   - Token savings: ~100-300 tokens
   
3. **Rename and limit `next_action` field**:
   ```python
   # Before: unlimited, verbose name
   soothe_next_action: str = ""
   
   # After: max 100 chars, simpler name
   next_action: str = Field(default="", max_length=100)
   ```
   
   **Justification**:
   - User-visible action summary (CLI/TUI)
   - Short descriptions sufficient ("I will analyze the UX module")
   - Long descriptions are verbose, not helpful
   - Simpler field name (`next_action` vs `soothe_next_action`)
   - Token savings: ~100-200 tokens

**Total Token Reduction**:
- Before: ~2000-2500 tokens (worst case)
- After: ~800-1200 tokens (worst case)
- Reduction: ~40-60%

**Simplified Schema**:
```python
class ReasonResult(BaseModel):
    """Simplified Reason phase output for token efficiency."""
    
    status: Literal["continue", "replan", "done"]
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    
    reasoning: str = Field(default="", max_length=500)
    """Internal analysis, truncated to 500 chars for token efficiency."""
    
    next_action: str = Field(default="", max_length=100)
    """User-facing action summary, max 100 chars."""
    
    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None
    full_output: str | None = None
    evidence_summary: str = ""  # Kept (filled from state, not model output)
    
    # Removed: progress_detail (rarely used, saves tokens)
    # Renamed: soothe_next_action → next_action (simpler naming)
```

**Impact**:
- ✅ Reduces token budget significantly (proactive prevention)
- ✅ Works for all providers (universal solution)
- ✅ Minimal code changes (Pydantic field definitions)
- ⚠️ May lose verbose reasoning context (but not critical)

---

### Layer 2: Query Splitting (Two Simple Calls)

**Goal**: Split monolithic Reason phase into two focused LLM calls, each simpler.

**Current Approach** (Single Call):
```python
# LLMPlanner.reason() - One complex call
result = await structured_model.ainvoke(messages)
# Returns: full ReasonResult (status + progress + reasoning + decision)
```

**Problem**: Single call asks model to do too much:
1. Assess progress (status, goal_progress, confidence)
2. Reason about strategy (reasoning field)
3. Generate plan (decision.steps)
4. Describe next action (soothe_next_action)

All in one output → large schema → truncation risk.

**New Approach** (Two Calls):

#### Call 1: Status Assessment (Lightweight)

**Schema**:
```python
class StatusAssessment(BaseModel):
    """Phase 1: Quick progress/status check."""
    
    status: Literal["continue", "replan", "done"]
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    
    brief_reasoning: str = Field(default="", max_length=100)
    """1-2 sentence status justification."""
    
    next_action: str = Field(default="", max_length=100)
    """User-facing next step description."""
```

**Token estimate**: ~400-600 tokens (very light)

**CLI Display**: Both `brief_reasoning` and `next_action` shown to user after Phase 1.

**Invocation**:
```python
# Phase 1: Quick assessment
assessment = await structured_model.ainvoke(messages, StatusAssessment)

if assessment.status == "done":
    # Goal complete, no plan needed
    return ReasonResult(
        status="done",
        goal_progress=assessment.goal_progress,
        confidence=assessment.confidence,
        reasoning=assessment.brief_reasoning,
        full_output=state.evidence_summary,  # From Act phase
    )
```

#### Call 2: Plan Generation (Only if status != "done")

**Schema**:
```python
class PlanGeneration(BaseModel):
    """Phase 2: Generate execution plan (conditional)."""
    
    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision
    
    brief_reasoning: str = Field(default="", max_length=100)
    """Why this plan strategy was chosen."""
    
    next_action: str = Field(default="", max_length=100)
    """User-facing next step (plan-specific)."""
```

**Token estimate**: ~900-1300 tokens (focused on plan only)

**CLI Display**: Phase 2's `brief_reasoning` and `next_action` appended to display (both phases visible).

**Invocation**:
```python
# Phase 2: Generate plan (only if needed)
if assessment.status != "done":
    # Add assessment results to context
    plan_messages = messages + [
        SystemMessage(content=f"Current status: {assessment.status}, progress: {assessment.goal_progress:.0%}")
    ]
    
    plan_result = await structured_model.ainvoke(plan_messages, PlanGeneration)
    
    # Combine results - concatenate both phases' reasoning and action
    combined_reasoning = (
        f"[Assessment] {assessment.brief_reasoning}\n"
        f"[Plan] {plan_result.brief_reasoning}"
    )
    
    combined_next_action = (
        f"{assessment.next_action}\n"
        f"{plan_result.next_action}"
    )
    
    return ReasonResult(
        status=assessment.status,
        goal_progress=assessment.goal_progress,
        confidence=assessment.confidence,
        reasoning=combined_reasoning,  # Both phases' reasoning
        plan_action=plan_result.plan_action,
        decision=plan_result.decision,
        next_action=combined_next_action,  # Both phases' next_action
    )
```

**Benefits**:
- ✅ Each call has smaller schema (reduced truncation risk)
- ✅ First call very simple (often sufficient for "done" status)
- ✅ Second call only when needed (saves computation)
- ✅ Better separation of concerns (assessment vs planning)
- ✅ User sees both phases' reasoning and next_action (transparent execution)
- ⚠️ Two LLM calls (latency overhead: +5-10s for complex goals)
- ⚠️ State coordination needed (pass assessment to plan phase)

**CLI Display Enhancement**:
- Phase 1 complete: Display `brief_reasoning` + `next_action` immediately
- Phase 2 complete: Append Plan's `brief_reasoning` + `next_action` below
- User sees full reasoning chain: "Why status assessment → Why plan chosen"

**Latency Analysis**:
- Current single call: ~8-15s (complex reasoning)
- New two calls: 
  - Call 1 (status): ~3-5s (lightweight)
  - Call 2 (plan): ~5-10s (only when status!=done)
  - Total: ~8-15s (similar for complex, faster for simple goals that complete early)

**Optimization**: For "done" goals, only Call 1 needed → faster completion detection. User only sees Phase 1 output.

---

### Layer 3: Fallback Safety Net (Existing Logic)

**Goal**: Keep existing retry + fallback as final safety layer.

**Current Fallback Pipeline** (lines 1088-1189 in `llm.py`):

```python
# Tier 1: Retry with structured output (3 attempts)
for attempt in range(3):
    try:
        result = await structured_model.ainvoke(messages)
        break
    except ValidationError:
        if attempt < 2:
            logger.warning("Retrying...")
            continue
        # Tier 2: Manual JSON extraction
        logger.info("Trying fallback: regular model + manual JSON parsing")
        response = await model.ainvoke(messages)
        json_str = _extract_and_repair_json(response.content)
        result = ReasonResult.model_validate(json_dict)
```

**Changes**:
- **No changes needed** - existing logic works as safety net
- Works for both Layer 1 (simplified schema) and Layer 2 (split calls)
- If truncation still occurs (unlikely), fallback handles it

**Integration**: Fallback logic remains unchanged, but should be invoked less frequently due to proactive prevention (Layer 1 + Layer 2).

---

## Implementation Plan

### Phase 1: Schema Diet (Layer 1)

**Changes**:

1. Update `ReasonResult` schema (`src/soothe/cognition/agent_loop/schemas.py`):
   ```python
   # Add max_length constraints
   reasoning: str = Field(default="", max_length=500)
   next_action: str = Field(default="", max_length=100)  # Renamed from soothe_next_action
   
   # Remove progress_detail
   # (delete field entirely)
   ```

2. Update downstream usage:
   - `state_manager.py`: Remove `progress_detail`, rename `soothe_next_action` → `next_action`
   - `agent_loop.py`: Remove `progress_detail`, rename field in event emission
   - `events.py`: Remove `progress_detail` from ReasonPhaseCompleteEvent, rename field
   - `CLI/TUI`: Update display to show `next_action` (rename field reference)

3. Update prompt templates:
   - Inform model of field limits (e.g., "reasoning should be ≤500 chars, next_action ≤100 chars")
   - Remove progress_detail from expected output description
   - Rename soothe_next_action → next_action in prompt examples

4. Validation logic:
   - Pydantic automatically validates max_length
   - Model outputs exceeding limit → validation error → fallback

**Testing**:
- Unit test: Verify ReasonResult validates with long reasoning (rejects >500 chars)
- Integration test: Verify truncated reasoning still produces valid ReasonResult
- Integration test: Verify field rename doesn't break CLI display
- Manual test: Verify schema diet prevents truncation with DashScope

**Scope**: ~60 lines (schema + downstream changes + field renaming)

---

### Phase 2: Query Splitting (Layer 2)

**Changes**:

1. Create new schemas (`schemas.py`):
   ```python
   class StatusAssessment(BaseModel):
       """Phase 1: Quick progress/status check."""
       status: Literal["continue", "replan", "done"]
       goal_progress: float
       confidence: float
       
       brief_reasoning: str = Field(default="", max_length=100)
       """1-2 sentence status justification."""
       
       next_action: str = Field(default="", max_length=100)
       """User-facing next step description."""
   
   class PlanGeneration(BaseModel):
       """Phase 2: Generate execution plan (conditional)."""
       plan_action: Literal["keep", "new"]
       decision: AgentDecision
       
       brief_reasoning: str = Field(default="", max_length=100)
       """Why this plan strategy was chosen."""
       
       next_action: str = Field(default="", max_length=100)
       """User-facing next step (plan-specific)."""
   ```

2. Refactor `LLMPlanner.reason()` (`cognition/planning/llm.py`):
   ```python
   async def reason(...) -> ReasonResult:
       messages = self._prompt_builder.build_reason_messages(...)
       
       # Phase 1: Status assessment
       assessment = await self._assess_status(messages)
       
       if assessment.status == "done":
           return self._create_done_result(assessment)
       
       # Phase 2: Plan generation
       plan = await self._generate_plan(messages, assessment)
       
       return self._combine_results(assessment, plan)
   ```

3. Implement helper methods:
   ```python
   async def _assess_status(self, messages) -> StatusAssessment:
       """Phase 1: Quick status/progress check."""
       structured_model = self._model.with_structured_output(StatusAssessment)
       return await structured_model.ainvoke(messages)
   
   async def _generate_plan(self, messages, assessment) -> PlanGeneration:
       """Phase 2: Plan generation (conditional)."""
       # Add assessment context
       context_msg = SystemMessage(
           content=f"Status: {assessment.status}, Progress: {assessment.goal_progress:.0%}"
       )
       plan_messages = messages + [context_msg]
       
       structured_model = self._model.with_structured_output(PlanGeneration)
       return await structured_model.ainvoke(plan_messages)
   
   def _combine_results(self, assessment, plan) -> ReasonResult:
       """Merge Phase 1 + Phase 2 results, concatenate reasoning/action."""
       combined_reasoning = (
           f"[Assessment] {assessment.brief_reasoning}\n"
           f"[Plan] {plan.brief_reasoning}"
       )
       
       combined_next_action = (
           f"{assessment.next_action}\n"
           f"{plan.next_action}"
       )
       
       return ReasonResult(
           status=assessment.status,
           goal_progress=assessment.goal_progress,
           confidence=assessment.confidence,
           reasoning=combined_reasoning,
           plan_action=plan.plan_action,
           decision=plan.decision,
           next_action=combined_next_action,
       )
   ```

4. Update prompt builder:
   - Split prompts into two stages
   - Phase 1 prompt: Focus on progress assessment + brief reasoning + next_action
   - Phase 2 prompt: Focus on plan generation + strategy reasoning + next_action (given assessment)

5. Update CLI/TUI display:
   - Phase 1 complete: Emit event with `brief_reasoning` + `next_action` for immediate display
   - Phase 2 complete: Append `brief_reasoning` + `next_action` to display (show both phases)
   - Example output format:
     ```
     [Reason Phase 1 - Status Assessment]
     Reasoning: Goal is mostly complete, evidence shows UX module fully analyzed.
     Next action: I'll finalize the UX architecture summary.
     
     [Reason Phase 2 - Plan Generation]
     Reasoning: Since goal is complete, no new plan needed.
     Next action: I'll compile the final UX architecture report.
     ```

**Testing**:
- Unit test: Mock two calls, verify result combination
- Unit test: Verify combined reasoning concatenates both phases correctly
- Integration test: Verify "done" status skips plan generation
- Integration test: Verify CLI/TUI displays both phases' reasoning/action
- Manual test: Verify latency acceptable (measure call durations)

**Scope**: ~180 lines (schemas + reason() refactor + helpers + CLI display updates)

---

### Phase 3: Fallback (Layer 3)

**Changes**: None (existing logic unchanged)

**Testing**:
- Integration test: Verify fallback still triggers when schema validation fails
- Manual test: Verify truncation still handled by fallback (safety net)

**Scope**: 0 lines (existing code reused)

---

## Total Implementation Scope

- Phase 1 (Schema Diet): ~60 lines (schema + renaming + downstream updates)
- Phase 2 (Query Splitting): ~180 lines (schemas + refactor + helpers + CLI display)
- Phase 3 (Fallback): ~0 lines (existing code reused)
- Tests: ~120 lines

**Total**: ~360 lines (much simpler than previous 600-800 lines design)

---

## Expected Outcomes

### Token Budget Reduction

**Before** (Current ReasonResult):
```
reasoning:         ~500-2000 tokens (unlimited)
decision.steps:    ~50-100 tokens per step (5 steps = 250-500 tokens)
next_action:       ~50-150 tokens (unlimited)
progress_detail:    ~50-200 tokens (optional)

Total: ~2000-3000 tokens (worst case)
```

**After** (Layer 1 + Layer 2):
```
# Phase 1: StatusAssessment
brief_reasoning:   ~50-100 tokens (max 100 chars)
next_action:       ~50-100 tokens (max 100 chars)
status/progress:   ~10-20 tokens
Total Phase 1:     ~200-250 tokens ✅

# Phase 2: PlanGeneration (conditional)
brief_reasoning:   ~50-100 tokens (max 100 chars)
next_action:       ~50-100 tokens (max 100 chars)
decision.steps:    ~250-500 tokens (5 steps max)
Total Phase 2:     ~500-800 tokens ✅

Combined: ~700-1050 tokens (reduced by 50-65%)
```

**Note**: Combined reasoning in final ReasonResult concatenates both phases → ~100-200 chars total (still under 500 char limit).

### Truncation Risk Analysis

**DashScope Limits**: ~8000 output tokens (recommended 7372)

**Before**:
- Worst case: 3000 tokens → exceeds limit → truncation likely ❌
- Observed: Truncation at 1500-5000 chars (matches worst case)

**After**:
- Worst case: 1050 tokens → well under limit → truncation unlikely ✅
- Phase 1: < 250 tokens → very safe
- Phase 2: < 800 tokens → safe margin

**Conclusion**: Layer 1 + Layer 2 should prevent truncation for 95%+ cases.

---

## Design Trade-offs

### Schema Richness vs Token Efficiency

**Loss of reasoning context**:
- Before: Unlimited reasoning (detailed strategy analysis)
- After: 500 chars (brief summary), but split into two phases (Assessment + Plan)
- Impact: Less debugging context per phase, but combined shows full reasoning chain
- User sees both phases' reasoning (transparent execution)

**Loss of progress_detail**:
- Before: Optional user-friendly progress explanation
- After: Removed (save tokens)
- Impact: User sees progress via `next_action` instead (more actionable)

**Field rename**:
- Before: `soothe_next_action` (verbose)
- After: `next_action` (simpler, clearer)
- Impact: Cleaner API, easier to understand

**Mitigation**: `evidence_summary` field retained (filled from state, not model output) - user can still see accumulated evidence.

**Recommendation**: Accept loss of verbosity for reliability gain.

---

### Latency vs Reliability

**Single call vs Two calls**:
- Simple goals ("done" early): Faster (only Call 1)
- Complex goals (need plan): Similar latency (Call 1 + Call 2 ≈ single call)
- Edge case: Very complex goals → slower (two sequential calls)

**Measurement**: Need integration testing to compare actual latency.

**Recommendation**: Accept latency increase for truncation prevention.

---

### Universal vs Provider-Specific

**Universal approach**:
- ✅ Works for all providers (no registry/handler logic)
- ✅ Simpler architecture (no provider detection)
- ✅ Lower maintenance (no per-provider handlers)
- ⚠️ May over-simplify for reliable providers (Anthropic could handle full schema)
- ⚠️ May under-simplify for unknown providers (if limits unknown)

**Mitigation**: Conservative limits (500 chars reasoning) work for all providers. Reliable providers just produce shorter reasoning (acceptable).

**Recommendation**: Universal approach preferred for simplicity and maintainability.

---

## Alternative Approaches Considered

### Alternative 1: Provider-Aware Structured Output (Option A)

**Approach**: DashScope uses tool-based strategy, OpenAI/Anthropic use native.

**Pros**:
- Preserves full schema richness for reliable providers
- Provider-optimal performance

**Cons**:
- Complex architecture (registry + handlers + detection)
- Provider-specific logic (maintenance burden)
- Doesn't address root cause (large schema)

**Rejected**: Universal approach simpler, schema diet is acceptable.

---

### Alternative 2: Dynamic Token Budgeting (Option C Complex)

**Approach**: Estimate tokens per invocation, simplify schema dynamically based on budget.

**Pros**:
- Adaptive to actual needs (preserve richness when budget sufficient)
- Reusable for future use cases

**Cons**:
- Complex estimation logic (tiktoken + heuristics)
- Dynamic schema creation (Pydantic create_model overhead)
- Estimation inaccuracies (may over/under simplify)

**Rejected**: Static simplification simpler and sufficient.

---

### Alternative 3: Adaptive Simplification Depth

**Approach**: Goal complexity classification → simplification depth. Complex goals keep richness, simple goals reduce more.

**Pros**:
- Preserves richness for complex goals (where needed)
- Leverages existing classification system

**Cons**:
- Classification accuracy matters (wrong classification → wrong simplification)
- More complex logic (another decision layer)

**Rejected**: Static limits simpler, 500 chars sufficient for all cases.

---

## Success Criteria

### Must Have

- ✅ DashScope/Kimi structured output succeeds without truncation
- ✅ Schema diet reduces token budget by ≥40%
- ✅ Query splitting separates assessment vs planning cleanly
- ✅ All existing tests pass (no regressions)
- ✅ Manual testing confirms truncation prevented

### Should Have

- ✅ Latency within acceptable range (≤15s for complex goals)
- ✅ Fallback still works as safety net (validated)
- ✅ User experience unchanged (soothe_next_action sufficient)
- ✅ Schema simplification preserves critical fields (status, decision)

### Nice to Have

- ✅ Latency faster for simple goals (early "done" detection)
- ✅ Telemetry shows truncation failures reduced by ≥90%
- ✅ Reusable pattern for other large schemas (Plan schema diet?)

---

## Open Questions

### Q1: Should reasoning field be 500 chars or shorter?

**Options**:
- 500 chars: Reasonable context for combined reasoning (Assessment + Plan), ~125 tokens
- 200 chars: Very brief, ~50 tokens (same as current logging truncation)

**Consideration**: 
- Current logging truncates to 200 chars (line 1117)
- Combined reasoning concatenates two 100-char phases → 200 chars total
- Could align ReasonResult limit with combined length (200 chars)

**Recommendation**: Start with 500 chars (allows expansion if needed), reduce to 200 if budget still exceeds limits. Each phase's `brief_reasoning` at 100 chars is already sufficient.

---

### Q2: Should plan generation (Phase 2) reuse assessment in prompt?

**Current design**: Add assessment results as SystemMessage context.

**Alternative**: Include assessment in Phase 2 schema (as input field):
```python
class PlanGeneration(BaseModel):
    # Input fields (from Phase 1)
    current_status: Literal["continue", "replan"]
    current_progress: float
    
    # Output fields
    plan_action: Literal["keep", "new"]
    decision: AgentDecision
```

**Trade-off**:
- SystemMessage context: Clearer separation, no schema duplication
- Schema input fields: More structured, but duplicates StatusAssessment fields

**Recommendation**: Use SystemMessage context (cleaner separation).

---

### Q3: Should decision.steps have a max count limit?

**Current**: No limit, model can generate arbitrary number of steps.

**Proposal**: Cap at 5 steps max (force sequential/parallel, limit DAG complexity).

**Token savings**: Each step ~50-100 tokens → cap saves ~200-500 tokens if model tries to generate 10 steps.

**Impact**: May limit complex goal decomposition.

**Recommendation**: Start without cap, add if budget still exceeds limits.

---

### Q4: Should both phases display next_action to user?

**Current design**: Yes, concatenate both phases' `next_action`.

**Alternative**: Only display Plan phase's `next_action` (assessment phase is internal).

**Trade-off**:
- Both phases: Transparent execution (user sees reasoning chain)
- Plan only: Cleaner display, less verbosity

**Recommendation**: Display both phases (transparent execution, shows reasoning chain). Format with phase labels for clarity.

---

## References

**Related Files**:
- `src/soothe/cognition/agent_loop/schemas.py` (ReasonResult schema)
- `src/soothe/cognition/planning/llm.py` (LLMPlanner.reason())
- `src/soothe/cognition/agent_loop/state_manager.py` (checkpoint usage)
- `src/soothe/cognition/agent_loop/events.py` (ReasonPhaseCompleteEvent)

**Related RFCs**:
- RFC-200: Agentic Goal Execution (Reason phase architecture)
- RFC-603: Reasoning Quality & Progressive Actions

**Related Implementation Guides**:
- IG-043: Planning Unified Architecture Guide (fallback logic)

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-04-11 | Claude Sonnet 4.6 | Initial design (three-layer defense) |

---

## Next Steps

1. Review draft with user
2. Create implementation guide (`docs/impl/`)
3. Implement Phase 1 (Schema Diet)
4. Implement Phase 2 (Query Splitting)
5. Validate Phase 3 (Fallback still works)
6. Run tests + manual validation
7. Update documentation

**Implementation timeline estimate**: 1-2 days (~300 lines + tests)