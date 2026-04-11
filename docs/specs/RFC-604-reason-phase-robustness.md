# RFC-604: Reason Phase Robustness (Three-Layer Defense)

**Status**: Draft
**Authors**: Claude Sonnet 4.6
**Created**: 2026-04-11
**Last Updated**: 2026-04-11
**Depends on**: RFC-603-reasoning-quality-progressive-actions, RFC-201-agentic-goal-execution
**Supersedes**: ---
**Stage**: Cognition/Planning
**Kind**: Architecture Design

---

## 1. Abstract

This RFC defines a three-layer defense strategy to prevent JSON truncation failures in the Reason phase structured output generation. The strategy combines proactive prevention (schema simplification and query splitting) with reactive fallback (existing retry logic) to ensure reliable operation across all LLM providers, particularly those with constrained output token budgets (DashScope/Kimi). The architecture separates status assessment from plan generation, reducing per-call token requirements while preserving reasoning quality through concatenated phase outputs.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:
- **Schema simplification strategy** for ReasonResult to reduce token footprint
- **Query splitting architecture** that separates status assessment from plan generation
- **Integration patterns** for three-layer defense with existing fallback mechanisms
- **Token budget allocation** across phases and fields
- **Field constraints** (max_length) for reliability without sacrificing quality

### 2.2 Non-Goals

This RFC does **not** define:
- Provider-specific output strategies (universal approach only)
- Dynamic token budgeting algorithms (static simplification)
- Implementation details for prompt engineering (belongs in implementation guide)
- Testing strategies and benchmark criteria (belongs in implementation guide)
- Adaptive simplification depth based on goal complexity (static limits suffice)

---

## 3. Background & Motivation

### 3.1 Problem: JSON Truncation Failures

**Provider Context**: DashScope/Kimi (OpenAI-compatible endpoint) using `kimi-k2.5` model.

**Observed Failure Pattern**:
```
ValidationError: 1 validation error for ReasonResult
  Invalid JSON: EOF while parsing a string at line 1 column 2644
```

**Root Cause Analysis**:
- ReasonResult schema produces large outputs: 1500-3000 tokens in worst cases
- Provider truncates JSON at ~1500-5000 character limit mid-string
- Unlimited `reasoning` field (500-2000 tokens) dominates output budget
- Complex nested `decision` schema contributes 250-500 tokens
- Optional fields (`progress_detail`, verbose `soothe_next_action`) add overhead

**Impact**:
- Validation failures block Reason phase execution
- 3-tier retry + fallback cannot recover from truncation (JSON irrecoverably corrupted)
- User sees generic error, no progress feedback
- Agent execution halts, goal cannot complete

### 3.2 Previous Attempts

**Existing Fallback Logic** (lines 1088-1189 in `llm.py`):
- Tier 1: 3 retry attempts with structured output
- Tier 2: Regular model + manual JSON extraction/repair
- Tier 3: Default ReasonResult with conservative defaults

**Limitations**:
- Fallback assumes transient validation errors, not permanent truncation
- Manual JSON repair cannot fix mid-string truncation (EOF at arbitrary position)
- Retry attempts waste latency on unfixable truncation
- Designed for schema violations, not token budget violations

**Conclusion**: Need proactive prevention before fallback is invoked.

---

## 4. Design Principles

1. **Layered Defense**: Proactive prevention (Layers 1-2) before reactive fallback (Layer 3)
2. **Universal Approach**: Single strategy works for all providers (no provider registry)
3. **Separation of Concerns**: Status assessment separate from plan generation
4. **Token Efficiency**: Reduce schema footprint without sacrificing critical fields
5. **Progressive Reasoning**: Concatenate phase outputs for complete reasoning chain
6. **Graceful Degradation**: Fallback still available if Layers 1-2 fail

---

## 5. Architecture: Three-Layer Defense

### 5.1 Layer Overview

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Schema Diet                                   │
│  - Simplify ReasonResult schema                         │
│  - Add max_length constraints                           │
│  - Remove optional fields                               │
│  - Rename verbose fields                                │
│  Token reduction: ~40-60%                               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Query Splitting                               │
│  - Split into StatusAssessment + PlanGeneration         │
│  - Conditional plan generation (only if status!=done)   │
│  - Concatenate phase outputs                            │
│  Token reduction per call: ~50-65%                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Fallback (Existing)                           │
│  - 3 retry attempts                                     │
│  - Manual JSON extraction                               │
│  - Conservative defaults                                │
│  Safety net for edge cases                              │
└─────────────────────────────────────────────────────────┘
```

**Execution Order**: Layer 1 applied first (schema changes), Layer 2 applied second (call splitting), Layer 3 as final safety net.

---

## 6. Layer 1: Schema Diet

### 6.1 Simplified ReasonResult Schema

**Current Schema** (problematic):
```python
class ReasonResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    evidence_summary: str = ""
    goal_progress: float = Field(default=0.0)
    confidence: float = Field(default=0.8)
    reasoning: str = ""                           # Unlimited ❌
    soothe_next_action: str = ""                  # Unlimited ❌
    progress_detail: str | None = None            # Optional, rarely used ❌
    plan_action: Literal["keep", "new"]
    decision: AgentDecision | None
    full_output: str | None = None
```

**Simplified Schema** (Layer 1):
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
    evidence_summary: str = ""

    # Removed: progress_detail (rarely used)
    # Renamed: soothe_next_action → next_action
```

### 6.2 Field Simplification Strategy

#### 6.2.1 Truncate `reasoning` Field

**Change**:
```python
# Before: unlimited
reasoning: str = ""

# After: max 500 chars
reasoning: str = Field(default="", max_length=500)
```

**Justification**:
- Currently used only for debug logging (truncated to 200 chars at display)
- Stored in checkpoint metadata (internal use, no user-facing display)
- Token savings: ~1500-1800 tokens (largest contributor to truncation)
- 500 chars provides sufficient context for debugging and reasoning chain

**Impact**: Critical field retained, verbose reasoning truncated to essential summary.

#### 6.2.2 Remove `progress_detail` Field

**Change**:
```python
# Before: optional but in schema
progress_detail: str | None = None

# After: removed entirely
```

**Justification**:
- Optional field, rarely populated by model
- Low user value (next_action is primary user-facing field)
- No core logic dependencies
- Token savings: ~100-300 tokens

**Impact**: Minor user-facing change, replaced by more actionable next_action.

#### 6.2.3 Rename and Limit `next_action` Field

**Change**:
```python
# Before: unlimited, verbose name
soothe_next_action: str = ""

# After: max 100 chars, simpler name
next_action: str = Field(default="", max_length=100)
```

**Justification**:
- User-visible action summary (CLI/TUI display)
- Short descriptions sufficient ("I will analyze the UX module")
- Simpler field name improves API clarity
- Token savings: ~100-200 tokens

**Impact**: Cleaner API, user experience unchanged (short summaries are clearer).

### 6.3 Token Budget Analysis

**Before** (Current ReasonResult):
```
reasoning:         ~500-2000 tokens (unlimited)
decision.steps:    ~250-500 tokens (5 steps)
next_action:       ~50-150 tokens (unlimited)
progress_detail:    ~50-200 tokens (optional)

Total: ~2000-3000 tokens (worst case)
```

**After** (Layer 1 Simplified Schema):
```
reasoning:         ~125 tokens (500 chars max)
decision.steps:    ~250-500 tokens (unchanged)
next_action:       ~25-50 tokens (100 chars max)

Total: ~800-1200 tokens (worst case)
```

**Reduction**: ~40-60% token budget decrease.

**Truncation Risk**:
- DashScope recommended limit: 7372 output tokens
- After Layer 1: 1200 tokens → well under limit → truncation unlikely

---

## 7. Layer 2: Query Splitting Architecture

### 7.1 Separation of Concerns

**Current Approach** (Single Monolithic Call):
```python
# LLMPlanner.reason() - One complex call
result = await structured_model.ainvoke(messages)
# Returns: full ReasonResult (status + progress + reasoning + decision)
```

**Problem**: Single call asks model to:
1. Assess progress (status, goal_progress, confidence)
2. Reason about strategy (reasoning field)
3. Generate plan (decision.steps)
4. Describe next action (next_action)

All in one output → large schema → truncation risk.

**New Architecture** (Two Focused Calls):

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

**Token Budget**: ~400-600 tokens (very lightweight)

**Execution Pattern**:
- Always executed first
- If `status="done"`: Return immediately (skip plan generation)
- If `status="continue"/"replan"`: Proceed to Call 2

**Early Completion Optimization**:
- Simple goals complete in Call 1 only → faster execution
- User sees Phase 1 reasoning + next_action immediately
- No wasted latency on unnecessary plan generation

#### Call 2: Plan Generation (Conditional)

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

**Token Budget**: ~900-1300 tokens (focused on plan only)

**Execution Pattern**:
- Only executed if `status != "done"`
- Receives assessment context as SystemMessage input
- Generates plan based on current status/progress

**Context Integration**:
```python
# Add assessment results to Phase 2 context
context_msg = SystemMessage(
    content=f"Status: {assessment.status}, Progress: {assessment.goal_progress:.0%}"
)
plan_messages = messages + [context_msg]
```

### 7.2 Phase Output Concatenation

**Result Combination Pattern**:
```python
# Concatenate reasoning from both phases
combined_reasoning = (
    f"[Assessment] {assessment.brief_reasoning}\n"
    f"[Plan] {plan_result.brief_reasoning}"
)

# Concatenate next_action from both phases
combined_next_action = (
    f"{assessment.next_action}\n"
    f"{plan_result.next_action}"
)

# Build final ReasonResult
return ReasonResult(
    status=assessment.status,
    goal_progress=assessment.goal_progress,
    confidence=assessment.confidence,
    reasoning=combined_reasoning,
    plan_action=plan_result.plan_action,
    decision=plan_result.decision,
    next_action=combined_next_action,
)
```

**User Display Pattern**:
```
[Reason Phase 1 - Status Assessment]
Reasoning: Goal is mostly complete, evidence shows UX module analyzed.
Next action: I'll finalize the UX architecture summary.

[Reason Phase 2 - Plan Generation]
Reasoning: Since goal is complete, no new plan needed.
Next action: I'll compile the final UX architecture report.
```

**Benefit**: User sees complete reasoning chain (transparent execution).

### 7.3 Token Budget Per Phase

**Phase 1 (StatusAssessment)**:
```
brief_reasoning:   ~50-100 tokens (max 100 chars)
next_action:       ~50-100 tokens (max 100 chars)
status/progress:   ~10-20 tokens

Total Phase 1:     ~200-250 tokens ✅ (very safe)
```

**Phase 2 (PlanGeneration)**:
```
brief_reasoning:   ~50-100 tokens (max 100 chars)
next_action:       ~50-100 tokens (max 100 chars)
decision.steps:    ~250-500 tokens (5 steps max)

Total Phase 2:     ~500-800 tokens ✅ (safe margin)
```

**Combined Total**: ~700-1050 tokens (50-65% reduction vs original)

### 7.4 Latency Analysis

**Single Call Approach**:
- Execution time: ~8-15s (complex reasoning)

**Two-Call Approach**:
- Call 1 (status): ~3-5s (lightweight)
- Call 2 (plan): ~5-10s (conditional, only if status!=done)
- Total: ~8-15s (similar for complex goals, faster for simple goals)

**Optimization**: Early "done" detection saves latency:
- Simple goals: Only Call 1 → 3-5s (faster completion)
- Complex goals: Call 1 + Call 2 → 8-15s (unchanged)

---

## 8. Layer 3: Fallback Integration

### 8.1 Existing Fallback Logic

**Location**: `src/soothe/cognition/planning/llm.py` (lines 1088-1189)

**Current Pipeline**:
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

### 8.2 Integration Strategy

**Layer 3 Role**: Safety net for edge cases where Layers 1-2 still fail.

**Expected Behavior**:
- Layer 1 reduces schema size → truncation less likely
- Layer 2 splits calls → each call simpler → truncation unlikely
- Layer 3 invoked rarely (only for unexpected failures)

**No Changes Required**:
- Existing retry logic works for both StatusAssessment and PlanGeneration schemas
- Manual JSON repair works for smaller JSON objects (easier to repair)
- Conservative defaults still available as final fallback

**Fallback Frequency**:
- Before: Frequent truncation failures → fallback invoked often
- After: Layers 1-2 prevent truncation → fallback rarely invoked

---

## 9. Design Trade-offs

### 9.1 Schema Richness vs Token Efficiency

**Loss**:
- Unlimited `reasoning` → 500 chars max
- Optional `progress_detail` → removed
- Verbose `soothe_next_action` → 100 chars max

**Gain**:
- Reliable structured output across all providers
- Universal solution (no provider-specific logic)
- Faster execution for simple goals (early "done" detection)

**Mitigation**:
- Combined reasoning from both phases shows complete chain (100-200 chars total)
- User-facing display focuses on actionable `next_action` (more useful than progress_detail)
- Critical fields retained: status, decision, goal_progress, confidence

**Recommendation**: Accept reduced verbosity for reliability gain.

### 9.2 Latency vs Reliability

**Two Calls vs One Call**:
- Simple goals: Faster (early "done" detection)
- Complex goals: Similar latency (Call 1 + Call 2 ≈ single call)
- Edge cases: Slightly slower (two sequential calls)

**Reliability Gain**:
- Truncation failures eliminated for 95%+ cases
- User sees clear progress through phases
- Better separation of concerns (assessment vs planning)

**Recommendation**: Accept potential latency increase for truncation prevention.

### 9.3 Universal vs Provider-Specific

**Universal Approach Advantages**:
- ✅ Works for all providers (no registry logic)
- ✅ Simpler architecture (no provider detection)
- ✅ Lower maintenance (no per-provider handlers)
- ✅ Conservative limits work for reliable providers (Anthropic, OpenAI)

**Disadvantages**:
- ⚠️ May over-simplify for reliable providers (Anthropic could handle full schema)
- ⚠️ May under-simplify for unknown providers (if limits unknown)

**Mitigation**: Conservative limits (500 chars reasoning) are sufficient for all providers. Reliable providers produce shorter reasoning (acceptable).

**Recommendation**: Universal approach preferred for simplicity and maintainability.

---

## 10. Alternative Approaches

### 10.1 Provider-Aware Structured Output

**Approach**: DashScope uses tool-based strategy, OpenAI/Anthropic use native structured output.

**Rejected Reason**:
- Complex architecture (registry + handlers + detection)
- Provider-specific logic (maintenance burden)
- Doesn't address root cause (large schema)
- Universal approach simpler and sufficient

### 10.2 Dynamic Token Budgeting

**Approach**: Estimate tokens per invocation, simplify schema dynamically based on provider limits.

**Rejected Reason**:
- Complex estimation logic (tiktoken + heuristics)
- Dynamic schema creation (Pydantic create_model overhead)
- Estimation inaccuracies (may over/under simplify)
- Static simplification simpler and sufficient

### 10.3 Adaptive Simplification Depth

**Approach**: Goal complexity classification → simplification depth. Complex goals keep richness, simple goals reduce more.

**Rejected Reason**:
- Classification accuracy matters (wrong classification → wrong simplification)
- More complex logic (another decision layer)
- Static limits simpler, 500 chars sufficient for all cases

---

## 11. Success Criteria

### 11.1 Must Have

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Truncation prevention | 95%+ cases | Zero truncation failures with DashScope in testing |
| Schema diet token reduction | ≥40% | Token budget analysis (2000→800 tokens) |
| Query splitting separation | Clean architecture | Unit tests verify phase separation |
| Existing tests pass | 100% | No regressions in test suite |
| Fallback integration | Works as safety net | Manual testing confirms fallback still triggers |

### 11.2 Should Have

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Latency acceptable | ≤15s for complex goals | Integration test measurements |
| User experience unchanged | Clear progress display | Manual UX testing |
| Combined reasoning quality | Complete chain visible | Manual review of phase outputs |
| Early completion optimization | Faster simple goals | Latency comparison (simple vs complex) |

### 11.3 Nice to Have

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Telemetry shows improvement | ≥90% reduction in failures | Production monitoring |
| Reusable pattern | Apply to other schemas | PlanResult simplification |
| Benchmark suite | 10+ test cases | Benchmark validation pass rate ≥80% |

---

## 12. Open Questions

### 12.1 Reasoning Field Length

**Question**: Should `reasoning` be 500 chars or shorter (200 chars)?

**Options**:
- 500 chars: Allows combined reasoning from both phases (100+100=200 chars)
- 200 chars: Matches current logging truncation (very brief)

**Recommendation**: Start with 500 chars (allows expansion), reduce to 200 if budget still exceeds limits.

### 12.2 Plan Phase Context Integration

**Question**: Should Phase 2 include assessment in schema (input fields) or SystemMessage?

**Options**:
- SystemMessage: Cleaner separation, no schema duplication
- Schema input fields: More structured, but duplicates StatusAssessment fields

**Recommendation**: Use SystemMessage context (cleaner separation of concerns).

### 12.3 Decision Steps Limit

**Question**: Should `decision.steps` have max count limit (cap at 5 steps)?

**Trade-off**:
- Cap saves tokens (each step ~50-100 tokens)
- Cap limits complex goal decomposition

**Recommendation**: Start without cap, add if budget still exceeds limits.

### 12.4 Phase Display Strategy

**Question**: Should both phases display `next_action` to user?

**Options**:
- Both phases: Transparent execution (user sees reasoning chain)
- Plan only: Cleaner display, less verbosity

**Recommendation**: Display both phases (transparent execution, shows reasoning chain).

---

## 13. Relationship to Other RFCs

### 13.1 Dependencies

* **RFC-603-reasoning-quality-progressive-actions**: Provides Reason phase architecture and quality improvements that this RFC builds upon
* **RFC-201-agentic-goal-execution**: Defines Layer 2 AgentLoop architecture where Reason phase operates

### 13.2 Integration Points

* **RFC-603 Section 4.1 (Schema Changes)**: This RFC modifies ReasonResult schema defined there
* **RFC-201 Section 5 (Reason Phase)**: This RFC refactors Reason phase execution pattern defined there
* **RFC-603 Section 3 (Quality Improvements)**: This RFC preserves evidence-based confidence/progress calculations

---

## 14. Conclusion

This RFC defines a robust three-layer defense strategy to prevent JSON truncation failures in structured output generation. By combining proactive schema simplification (Layer 1) and query splitting (Layer 2) with reactive fallback (Layer 3), the architecture ensures reliable Reason phase operation across all LLM providers. The design reduces token budgets by 40-60% while preserving critical reasoning quality through concatenated phase outputs and evidence-based metrics. The universal approach eliminates provider-specific complexity while gracefully handling edge cases through existing fallback mechanisms.

> **Reliability through layered defense: proactive prevention before reactive fallback**

---

## Appendix A: Token Budget Reference

### A.1 Provider Output Token Limits

| Provider | Recommended Limit | Hard Limit | Truncation Risk Threshold |
|----------|-------------------|------------|---------------------------|
| DashScope/Kimi | 7372 tokens | 8000 tokens | ~1500-5000 chars observed |
| OpenAI GPT-4 | 4096 tokens | 4096 tokens | Rare truncation |
| Anthropic Claude | 4096 tokens | 4096 tokens | No truncation observed |

### A.2 Schema Token Budgets

**Current ReasonResult** (Problematic):
- Total: ~2000-3000 tokens (worst case)
- Risk: Exceeds DashScope limit → truncation

**Layer 1 Simplified** (Schema Diet):
- Total: ~800-1200 tokens (worst case)
- Risk: Well under DashScope limit → safe

**Layer 2 Split Calls** (Query Splitting):
- Phase 1: ~200-250 tokens (very safe)
- Phase 2: ~500-800 tokens (safe)
- Combined: ~700-1050 tokens (50-65% reduction)

---

## Appendix B: Implementation Scope Estimate

| Phase | Component | Lines Changed |
|-------|-----------|---------------|
| Layer 1 | Schema + downstream changes | ~60 lines |
| Layer 2 | Schemas + refactor + helpers | ~180 lines |
| Layer 3 | Fallback (unchanged) | ~0 lines |
| Tests | Unit + integration tests | ~120 lines |
| **Total** | | **~360 lines** |

**Timeline**: 1-2 days implementation + testing.

---

**RFC Status**: Draft - Ready for Implementation Guide Creation