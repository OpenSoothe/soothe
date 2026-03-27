# IG-079: Goal Natural Language Logging Enhancement

**Status**: ✅ Completed
**Date**: 2026-03-28
**Completed**: 2026-03-28 01:10 UTC
**RFC References**: RFC-0007 (Goal Lifecycle), RFC-0009 (DAG Execution)

---

## Objective

Enhance goal engine logging to include comprehensive natural language context (parent relationships, dependency descriptions, duration tracking) for better debugging and understanding.

---

## Problem

Current logs show goal descriptions but lack contextual information:

```log
Created goal 7217edda: Analyze user authentication flow (priority=50)
Ready goals: 1 ([('7217edda', 'Analyze user authentication flow', 'priority=50')])
Completed goal 6269bf9c: Fix login bug (priority=50)
Added dependencies to goal abc123: ['def456']  ← Dependency IDs only, no context ❌
```

**Issues**:
1. Parent goal relationships not shown with descriptions
2. Dependency IDs shown without their natural language descriptions
3. Ready goals format hard to read for long descriptions
4. DAG visualization truncates descriptions to 60 chars
5. No duration tracking on goal completion
6. Dependency status not visible on failures

---

## Solution: Natural Language Context Enhancement

### Implementation Plan

1. Add `_get_goal_context()` helper method for natural language context
2. Enhance `create_goal()` logging with parent context
3. Enhance `ready_goals()` logging with multi-line readable format
4. Enhance `complete_goal()` logging with duration and parent context
5. Enhance `fail_goal()` logging with dependency descriptions and status
6. Enhance `add_dependencies()` logging with dependency descriptions
7. Enhance `_format_goal_dag()` to show full descriptions and dependency context

---

## Expected Output

After natural language enhancement:

```log
Created goal 7217edda: "Analyze user authentication flow" (priority=50)
Created goal 6269bf9c: "Fix login bug" | parent: "Analyze user authentication flow" (priority=50)
Ready goals: 2
  → 7217edda: "Analyze user authentication flow" (priority=50)
  → 6269bf9c: "Fix login bug" | parent: "Analyze user authentication flow" (priority=50)
Completed goal 7217edda: "Analyze user authentication flow" (priority=50, duration=12.3s)
Added dependencies to goal abc123 "Implement logout": [def456: "Clear session data", ghi789: "Update UI"]
Failed goal 28c8a673: "Test login" | depends_on: [Fix login bug (completed), Setup database (failed)] (priority=50, retries=2/2) - Connection error

Goal DAG:
  [7217edda] completed priority=50
      → Analyze user authentication flow
  [6269bf9c] completed priority=50 parent=7217edda "Analyze user auth..."
      → Fix login bug
  [abc123] active priority=50 parent=7217edda "Analyze..." depends_on=[def456 "Clear session data", ghi789 "Update UI"]
      → Implement logout
```

---

## Benefits

1. **Parent context visibility** - See parent goal descriptions in lifecycle events
2. **Dependency context** - Understand what a goal depends on from descriptions
3. **Better readability** - Multi-line format for ready goals easier to read
4. **Duration tracking** - See how long goals took to complete
5. **Full descriptions in DAG** - No truncation in DAG visualization
6. **Dependency status** - See status of dependencies on failure
7. **Natural language flow** - Logs tell a story of goal relationships

---

## Testing

- All existing tests continue to pass (behavior unchanged)
- Manual log inspection confirms enhanced format
- No breaking changes to test expectations

---

## Completion Checklist

- ✅ Add `_get_goal_context()` helper method
- ✅ Enhanced `create_goal()` logging
- ✅ Enhanced `ready_goals()` logging
- ✅ Enhanced `complete_goal()` logging
- ✅ Enhanced `fail_goal()` logging
- ✅ Enhanced `add_dependencies()` logging
- ✅ Enhanced `_format_goal_dag()`
- ✅ All tests passing (930 tests)
- ✅ Linting clean (zero errors)

---

## References

- **RFC-0007**: Goal Lifecycle Management
- **RFC-0009**: DAG-based Execution with Dependencies
- **Source**: `src/soothe/cognition/goal_engine.py`
- **Tests**: `tests/unit/test_goal_engine.py`