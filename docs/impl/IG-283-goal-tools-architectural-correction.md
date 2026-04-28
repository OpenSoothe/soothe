# Goal Tools Architectural Correction Implementation Guide

> Implementation guide for removing unnecessary goal management tools to align with RFC-200 Goal Pull Architecture.
>
> **Crate/Module**: `packages/soothe/src/soothe/tools/goals/`
> **Source**: RFC-200 (Goal Pull Architecture), RFC-204 (Layer 2 ↔ Layer 3 Communication)
> **Related RFCs**: RFC-001, RFC-201
> **Language**: Python 3.11+
> **Framework**: LangChain + Pydantic

---

## 1. Overview

This implementation guide specifies the removal of basic goal management tools (`create_goal`, `list_goals`, `complete_goal`, `fail_goal`) from Layer 2 tool infrastructure to align with RFC-200's Goal Pull Architecture.

### 1.1 Purpose

**Architectural Violation Identified**:
- Current: Basic goal operations wrapped as Layer 2 tools (incorrect)
- Correct: Goal operations are Layer 3 service APIs, not Layer 2 tools

**RFC-200 Requirement** (§195):
> "GoalEngine never invokes AgentLoop (inverted control flow). AgentLoop queries GoalEngine via pull-based API."

GoalEngine is a **service provider**, not a tool target. Layer 2 should query Layer 3, not manage goals directly.

### 1.2 Scope

**In Scope**:
- Remove `CreateGoalTool`, `ListGoalsTool`, `CompleteGoalTool`, `FailGoalTool`
- Remove `create_goals_tools()` factory function
- Remove `resolve_goal_tools()` resolver function
- Update `__init__.py` exports
- Update unit tests for goal tools removal
- Preserve `create_agent_loop_tools()` (RFC-204 required)

**Out of Scope**:
- GoalEngine API methods (remain unchanged)
- Layer 3 runner code (continues using GoalEngine directly)
- AgentLoop communication tools (RFC-204 bidirectional communication)

### 1.3 Spec Compliance

**RFC-200 Compliance**:
- §185: GoalEngine provides service APIs (`create_goal`, `complete_goal`, `fail_goal`)
- §195: GoalEngine never invoked by Layer 2 tools (pull architecture)
- §200: Goals scheduled by Layer 3, not created by Layer 2

**RFC-204 Compliance**:
- §1.2: AgentLoop ↔ Layer 3 communication via query/proposal tools
- §64-76: Query tools (read-only) and Proposal tools (queued)
- §77: Queuing semantics preserve black-box abstraction

---

## 2. Architectural Rationale

### 2.1 Why Remove Basic Goal Tools?

**Current Incorrect Design**:
```python
# Layer 2 tool wrapping Layer 3 service (architectural violation)
class CreateGoalTool(BaseTool):
    def _run(self, description: str):
        goal = await self.goal_engine.create_goal(description)
        return {"created": goal}
```

**Correct Design** (RFC-200 Goal Pull):
```python
# Layer 3 runner creates goals (service API, not tool)
goal = await goal_engine.create_goal(user_input, priority=80)

# Layer 2 queries Layer 3 for goal assignment (pull-based)
current_goal = goal_engine.get_next_ready_goal()
```

**Key Principles**:
1. **Service Provider**: GoalEngine provides goal state service
2. **Pull Architecture**: Layer 2 queries Layer 3, never invokes
3. **Inverted Control**: AgentLoop drives execution, GoalEngine serves state
4. **Black-Box Delegation**: Layer 2 delegates to Layer 3, not manages goals

### 2.2 Goal Operation Owners

| Operation | Owner | Reason |
|-----------|-------|--------|
| `create_goal` | Layer 3 Runner | Goal creation is Layer 3 responsibility |
| `complete_goal` | Layer 3 Runner | Layer 3 validates Layer 2 completion |
| `fail_goal` | Layer 3 Runner | Layer 3 applies BackoffReasoner |
| `list_goals` | GoalEngine internal | Service query, not Layer 2 tool |
| `get_related_goals` | Layer 2 Tool | RFC-204 bidirectional communication ✅ |
| `suggest_goal` | Layer 2 Tool | RFC-204 proposal tool ✅ |

---

## 3. Module Structure Changes

### 3.1 Before

```
packages/soothe/src/soothe/tools/goals/
├── __init__.py
│   ├── create_goals_tools (exported)
│   ├── CreateGoalTool (exported)
│   ├── ListGoalsTool (exported)
│   ├── CompleteGoalTool (exported)
│   ├── FailGoalTool (exported)
│   └── create_agent_loop_tools (exported)
│
├── implementation.py
│   ├── CreateGoalTool (lines 58-106)
│   ├── ListGoalsTool (lines 108-148)
│   ├── CompleteGoalTool (lines 150-193)
│   ├── FailGoalTool (lines 195-258)
│   ├── create_goals_tools() (lines 260-274)
│   └── create_agent_loop_tools() (lines 564-602)
│
└── tests/
    └── test_goal_tools.py (tests basic tools)
```

### 3.2 After

```
packages/soothe/src/soothe/tools/goals/
├── __init__.py
│   ├── create_agent_loop_tools (exported ONLY)
│   ├── GetRelatedGoalsTool (exported)
│   ├── SuggestGoalTool (exported)
│   └── ... (RFC-204 communication tools)
│
├── implementation.py
│   ├── GetRelatedGoalsTool (RFC-204 query)
│   ├── GetGoalProgressTool (RFC-204 query)
│   ├── ReportProgressTool (RFC-204 proposal)
│   ├── SuggestGoalTool (RFC-204 proposal)
│   ├── FlagBlockerTool (RFC-204 proposal)
│   ├── GetWorldInfoTool (RFC-204 query)
│   ├── SearchMemoryTool (RFC-204 query)
│   ├── AddFindingTool (RFC-204 proposal)
│   └── create_agent_loop_tools() (factory)
│
└── tests/
    └── test_goal_tools.py (REMOVED - merged into communication tests)
```

---

## 4. Implementation Details

### 4.1 Remove Basic Goal Tools

**Files Modified**:
1. `implementation.py`: Remove lines 58-274
2. `__init__.py`: Remove basic tool exports
3. `_resolver_tools.py`: Remove `resolve_goal_tools()`
4. `resolver/__init__.py`: Remove `resolve_goal_tools` export

**Code Removal**:

```python
# REMOVE from implementation.py (lines 58-274):
class CreateGoalTool(BaseTool): ...  # Gone
class ListGoalsTool(BaseTool): ...   # Gone
class CompleteGoalTool(BaseTool): ... # Gone
class FailGoalTool(BaseTool): ...    # Gone
def create_goals_tools(...): ...     # Gone

# KEEP from implementation.py (lines 564-602):
class GetRelatedGoalsTool(BaseTool): ...  # RFC-204 required
class SuggestGoalTool(BaseTool): ...      # RFC-204 required
def create_agent_loop_tools(...): ...     # RFC-204 required
```

### 4.2 Update Exports

**`__init__.py` Changes**:

```python
# BEFORE:
from .implementation import (
    create_goals_tools,
    CreateGoalTool,
    ListGoalsTool,
    CompleteGoalTool,
    FailGoalTool,
    create_agent_loop_tools,
    GetRelatedGoalsTool,
    SuggestGoalTool,
    ...
)

__all__ = [
    "create_goals_tools",
    "CreateGoalTool",
    "ListGoalsTool",
    "CompleteGoalTool",
    "FailGoalTool",
    "create_agent_loop_tools",
    ...
]

# AFTER:
from .implementation import (
    create_agent_loop_tools,  # ONLY this factory
    GetRelatedGoalsTool,
    GetGoalProgressTool,
    ReportProgressTool,
    SuggestGoalTool,
    FlagBlockerTool,
    GetWorldInfoTool,
    SearchMemoryTool,
    AddFindingTool,
)

__all__ = [
    "create_agent_loop_tools",
    "GetRelatedGoalsTool",
    "GetGoalProgressTool",
    "ReportProgressTool",
    "SuggestGoalTool",
    "FlagBlockerTool",
    "GetWorldInfoTool",
    "SearchMemoryTool",
    "AddFindingTool",
]
```

### 4.3 Remove Resolver Function

**`_resolver_tools.py` Changes**:

```python
# REMOVE (lines 494-505):
def resolve_goal_tools(goal_engine: GoalEngine) -> list[BaseTool]:
    """Create goal management tools bound to a GoalEngine instance."""
    from soothe.tools.goals import create_goals_tools
    return create_goals_tools(goal_engine)

# KEEP comment (lines 462-463):
if name == "goals":
    return []  # Goals are handled separately (Layer 3 responsibility)
```

### 4.4 Update Tests

**Test File Changes**:

1. **Remove**: `test_goal_tools.py` (basic tool tests)
2. **Keep**: `test_goal_communication_tools.py` (RFC-204 tools)

**Migration**:
- Tests for `CreateGoalTool`, `ListGoalsTool` removed (not architecturally required)
- Tests for `create_agent_loop_tools()` remain (RFC-204 required)

---

## 5. Verification

### 5.1 Verification Checklist

After implementation, verify:

1. ✅ Basic goal tools removed from `implementation.py`
2. ✅ Exports updated in `__init__.py`
3. ✅ `resolve_goal_tools()` removed from resolver
4. ✅ `create_agent_loop_tools()` preserved
5. ✅ GoalEngine API methods unchanged
6. ✅ Layer 3 runner code unchanged (uses GoalEngine directly)
7. ✅ Unit tests passing
8. ✅ No import errors

### 5.2 Expected Test Results

**Removed Tests**:
- `test_goal_tools.py::TestGoalTools::test_create_returns_four_tools` (removed)
- `test_goal_tools.py::TestGoalTools::test_create_goal` (removed)
- `test_goal_tools.py::TestGoalTools::test_list_goals` (removed)

**Retained Tests**:
- `test_goal_communication_tools.py::TestAgentLoopTools::test_get_related_goals` (kept)
- `test_goal_communication_tools.py::TestAgentLoopTools::test_suggest_goal` (kept)

### 5.3 Run Verification

```bash
./scripts/verify_finally.sh
```

Expected outcome:
- All imports resolve correctly
- No references to removed tools
- RFC-204 communication tools functional
- GoalEngine service APIs functional

---

## 6. Migration Path

### 6.1 Phase 1: Remove Tools

1. Remove basic goal tool classes from `implementation.py`
2. Update `__init__.py` exports
3. Remove `resolve_goal_tools()` from resolver

### 6.2 Phase 2: Update Tests

1. Remove `test_goal_tools.py`
2. Ensure communication tool tests pass
3. Verify no import errors

### 6.3 Phase 3: Verification

1. Run `./scripts/verify_finally.sh`
2. Check for any remaining references
3. Ensure GoalEngine API calls unchanged

---

## Appendix A: RFC Requirement Mapping

| RFC Requirement | Implementation | Status |
|-----------------|----------------|--------|
| RFC-200 §185 GoalEngine service APIs | GoalEngine methods (unchanged) | ✅ Correct |
| RFC-200 §195 Goal Pull Architecture | Remove basic goal tools | ✅ Fixed |
| RFC-200 §200 Layer 3 goal creation | Runner creates goals directly | ✅ Correct |
| RFC-204 §1.2 Bidirectional communication | Keep AgentLoop tools | ✅ Preserved |
| RFC-204 §64-76 Query/Proposal tools | `create_agent_loop_tools()` | ✅ Required |

---

## Appendix B: Revision History

| Date | Changes |
|------|---------|
| 2026-04-21 | Initial implementation guide for architectural correction |

---

**Next Steps**: Execute refactoring in single phase, verify with `./scripts/verify_finally.sh`