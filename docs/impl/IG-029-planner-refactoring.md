# IG-029: Planner Refactoring and RFC-200 Goal Context Support

**Status**: ✅ Completed - RFC-200 (merged) merged into RFC-200 (2026-03-29)

## Objective

Refactor the planner subsystem to:
1. Fix RFC-200 §5.4 `goal_context` propagation across all planner modes
2. Enhance multilingual routing with hybrid heuristic + fast-model classification
3. Add LLM-assisted reflection for failure analysis and directive generation
4. Consolidate duplicate code into a shared module
5. Make SubagentPlanner use the `think` model role by default (configurable)
6. Improve DirectPlanner template matching for non-English goals

## Related

- [RFC-200 (merged)](../specs/RFC-200 (merged).md) -- Dynamic Goal Management During Reflection
- [IG-028](028-dynamic-goal-management.md) -- Dynamic Goal Management (prior impl)
- [RFC-200](../specs/RFC-200-autonomous-goal-management.md) -- Autonomous Iteration Loop
- [RFC-202](../specs/RFC-202-dag-execution.md) -- DAG-Based Execution

## Problem Analysis

### 1. RFC-200 (merged) `goal_context` Not Propagated (Bug)

The autonomous runner calls `reflect(plan, step_results, goal_context)` but:
- `AutoPlanner.reflect()` signature is `reflect(plan, step_results)` -- drops `goal_context`
- `SubagentPlanner.reflect()` and `ClaudePlanner.reflect()` lack `goal_context` parameter
- Dynamic goal management is effectively broken for all routing modes except `always_direct`

### 2. English-Only Routing and Template Matching

- `AutoPlanner._heuristic_classify()` uses English keyword sets only
- `DirectPlanner._match_template()` uses English regex patterns only
- Non-English goals always fall through to defaults, often misrouted

### 3. Heuristic-Only Reflection Across All Planners

All planners use identical heuristic reflection: count success/failure, categorize
blocked vs direct-failed. No LLM reasoning is used to analyze failures or generate
better feedback and goal directives.

### 4. Duplicate Code

`SubagentPlanner` and `ClaudePlanner` contain near-identical `_parse_plan_from_text()`
and `reflect()` implementations.

### 5. Unused `_llm_classify`

`AutoPlanner._llm_classify()` is implemented but never called (disabled in RFC-201
for performance). Should be offered as a configurable option.

## Design Decisions

### Routing Strategy: Hybrid Mode (Option A)

Heuristic first (fast path for English); when heuristic returns `None` (ambiguous)
and `fast_model` is configured, call `_llm_classify()`. Language-agnostic since the
LLM understands all languages.

Config: `routing_mode: "heuristic" | "llm" | "hybrid"` (default: `"hybrid"`).

### Reflection Optimization: Shared Heuristic + LLM Hybrid (Option B)

- Keep heuristic for quick pass (all success = no revision)
- When failures exist and a model is available, use LLM to analyze failures and
  generate `goal_directives`
- Falls back to heuristic if LLM fails

### RFC-200 (merged) Support: All Planning Modes

All four planners (Direct, Subagent, Claude, Auto) accept and process `goal_context`.
`AutoPlanner` forwards it to its delegate.

## Changes

### Phase 1: Shared Module and RFC-200 (merged) Fix

**`cognition/planning/_shared.py`** (NEW)

| Component | Description |
|-----------|-------------|
| `parse_plan_from_text()` | Consolidated markdown plan parser |
| `reflect_heuristic()` | Shared heuristic reflection with `goal_context` and `goal_directives` |
| `reflect_with_llm()` | LLM-assisted reflection for failure analysis |

**`cognition/planning/router.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `AutoPlanner.reflect()` | Add `goal_context` param, forward to delegate |

**`cognition/planning/subagent.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `SubagentPlanner.reflect()` | Add `goal_context` param, delegate to shared |
| `_parse_plan_from_text()` | Remove, use shared |

**`cognition/planning/claude.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `ClaudePlanner.reflect()` | Add `goal_context` param, delegate to shared |
| `_parse_plan_from_text()` | Remove, use shared |

**`cognition/planning/direct.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `DirectPlanner.reflect()` | Refactor to use shared `reflect_heuristic()` |

### Phase 2: Enhanced Multilingual Routing

**`config.py`** (EDIT)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `routing_mode` | `Literal["heuristic", "llm", "hybrid"]` | `"hybrid"` | Routing classification mode |

**`cognition/planning/router.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `AutoPlanner.__init__()` | Add `routing_mode` param |
| `AutoPlanner._route()` | Call `_llm_classify()` when heuristic is ambiguous and mode allows |

**`core/resolver.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `resolve_planner()` | Pass `routing_mode` to `AutoPlanner` |

### Phase 3: SubagentPlanner Think Model Config

**`config.py`** (EDIT)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `planner_model` | `str` | `"think"` | Model role for planner |

**`core/resolver.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `resolve_planner()` | Use `config.protocols.planner.planner_model` for model resolution |

### Phase 4: LLM-Assisted Reflection

**`cognition/planning/_shared.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `reflect_with_llm()` | Build prompt with step results and goal context, structured output for `Reflection` with `goal_directives`, fallback to heuristic |

**`cognition/planning/subagent.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `SubagentPlanner.reflect()` | Use `reflect_with_llm()` when failures exist |

**`cognition/planning/claude.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `ClaudePlanner.reflect()` | Use `reflect_with_llm()` when failures exist |

### Phase 5: DirectPlanner i18n Enhancement

**`cognition/planning/direct.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `DirectPlanner.__init__()` | Add optional `fast_model` param |
| `DirectPlanner._match_template()` | Add fast-model intent classification fallback for non-English |

**`core/resolver.py`** (EDIT)

| Component | Description |
|-----------|-------------|
| `resolve_planner()` | Pass `fast_model` to `DirectPlanner` |

### Phase 6: Tests

**`tests/unit_tests/test_planning.py`** (EDIT)

- Update reflection tests for `goal_context` parameter
- Add tests for shared `reflect_heuristic()` and `reflect_with_llm()`

**`tests/unit_tests/test_auto_planner.py`** (NEW)

- AutoPlanner routing with heuristic, llm, hybrid modes
- `goal_context` forwarding
- Non-English goal classification

## Implementation Steps

### Step 1: Create `_shared.py` with Shared Logic

Extract `parse_plan_from_text()` from SubagentPlanner/ClaudePlanner.
Extract `reflect_heuristic()` from all planners (with `goal_context` + `goal_directives`).
Add `reflect_with_llm()` stub.

### Step 2: Fix RFC-200 (merged) `goal_context` in All Planners

Update `AutoPlanner.reflect()`, `SubagentPlanner.reflect()`, `ClaudePlanner.reflect()`
to accept and process `goal_context: GoalContext | None = None`.

### Step 3: Refactor Direct/Subagent/Claude to Use Shared

Replace duplicate reflection and parsing logic with shared module calls.

### Step 4: Add Config Fields

Add `routing_mode` and `planner_model` to `PlannerProtocolConfig`.

### Step 5: Wire Hybrid Routing

Enable `_llm_classify()` in `AutoPlanner._route()` based on `routing_mode`.
Pass config through resolver.

### Step 6: Implement LLM-Assisted Reflection

Build `reflect_with_llm()` with structured LLM prompt for failure analysis and
directive generation. Wire into SubagentPlanner and ClaudePlanner.

### Step 7: DirectPlanner i18n

Add `fast_model` to DirectPlanner, use for intent classification when English
templates don't match.

### Step 8: Tests

Update existing tests, add new test file for AutoPlanner routing.

### Step 9: Lint and Verify

Run `make lint` and fix all issues.

## Verification

1. `make lint` passes
2. `pytest tests/unit_tests/test_planning.py -v` passes
3. `pytest tests/unit_tests/test_auto_planner.py -v` passes
4. `pytest tests/unit_tests/test_dynamic_goals.py -v` passes
