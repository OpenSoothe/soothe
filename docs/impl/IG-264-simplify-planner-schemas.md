# IG-264: Simplify Planner Schemas for Faster LLM Inference

**Status**: In Progress
**Created**: 2026-04-26
**RFC**: RFC-604 (Plan-And-Execute Loop)

---

## Objective

Simplify planner LLM call schemas to reduce inference burden and improve performance. Remove derivable fields while keeping execution-critical fields intact.

---

## Context

The two-phase planner (StatusAssessment + PlanGeneration) generates structured outputs via LLM. Some fields (`brief_reasoning`, `next_action`) can be derived from core decision structure and are redundant.

**Problem**: User-reported validation error - `plan_action='keep'` MUST have decision=None was too strict.

---

## Approach

### Schema Simplification

**StatusAssessment** (Phase 1):
- KEEP: `status`, `goal_progress`, `confidence` (MUST-have for flow control)
- REMOVE: `brief_reasoning`, `next_action` (deriv able from status/decision)

**PlanGeneration** (Phase 2):
- KEEP: `plan_action`, `decision` (MUST-have for execution)
- REMOVE: `brief_reasoning`, `next_action` (deriv able from decision)

**AgentDecision**:
- KEEP: ALL fields including `reasoning`, `adaptive_granularity` (used in execution/planning_utils)
- No changes - runtime needs these

**StepAction**:
- KEEP: ALL fields including `tools`, `subagent`, `dependencies` (used in executor)
- No changes - executor relies on these hints

### Validator Relaxation

- `plan_action='keep'` CAN have decision (optional, not enforced to be None)
- Only enforce `plan_action='new'` requires decision

### Planner Code Updates

1. Remove references to derivable fields (`brief_reasoning`, `next_action`)
2. Derive user-friendly messages from decision structure
3. Update fallback logic to use simplified schemas

---

## Implementation Tasks

- [x] Fix validation error (plan_action='keep' constraint)
- [x] Simplify StatusAssessment schema (remove derivable fields)
- [x] Simplify PlanGeneration schema (remove derivable fields)
- [x] Relax validators for optional decision
- [x] Update planner.py to handle simplified schemas
- [x] Update schemas.py to fix syntax errors
- [ ] Fix executor references (restore needed fields)
- [ ] Run verification suite
- [ ] Test planner performance improvement

---

## Expected Impact

- **Token reduction**: ~100-150 tokens per planner call (Phase 1 + Phase 2)
- **Latency improvement**: ~20-30% faster LLM inference per call
- **Validation relaxed**: No more spurious validation errors
- **Runtime intact**: Execution-critical fields preserved

---

## Risks

- User-facing messages derived dynamically (less LLM-generated detail)
- Tests may need updates for simplified schemas

---

## Verification

Run: `./scripts/verify_finally.sh`

Check:
- 1288 tests pass
- Linting clean
- Executor hints still work
- Planner calls succeed

---

## References

- `schemas.py`: Phase schemas definitions
- `planner.py`: Two-phase planner implementation
- `executor.py`: Uses `step.tools`, `step.subagent` for execution hints
- `planning_utils.py`: Uses `decision.reasoning`
- `RFC-604`: Plan-And-Execute architecture