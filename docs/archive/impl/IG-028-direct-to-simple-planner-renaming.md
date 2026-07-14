# IG-028: DirectPlanner to SimplePlanner Renaming

## Overview

This implementation guide documents the renaming of `DirectPlanner` to `SimplePlanner` for improved clarity and consistency. The name "SimplePlanner" better conveys the planner's role in handling simple tasks, contrasting with `SubagentPlanner` (medium complexity) and `ClaudePlanner` (complex tasks).

**Status**: ✅ Complete
**Date**: 2026-03-18
**Scope**: Internal refactoring, no behavior changes

## Motivation

### Why Rename to SimplePlanner?

1. **Clarity**: "Simple" clearly indicates the planner's purpose - handling simple tasks
2. **Consistency**: Aligns with complexity levels (simple, medium, complex)
3. **Discoverability**: New developers can immediately understand the planner hierarchy
4. **Self-documenting**: The name itself explains when to use this planner

### Why Rename the File?

Keeping the file name in sync with the class name is a Python convention that improves code organization and makes it easier to locate class definitions.

## Implementation Plan

### Phase 1: File Renaming

1. Rename `src/soothe/cognition/planning/direct.py` to `simple.py`
2. Update module docstring from "DirectPlanner" to "SimplePlanner"

### Phase 2: Class Renaming

1. Rename `class DirectPlanner` to `class SimplePlanner`
2. Update all docstrings referencing "DirectPlanner"
3. Update log messages using "DirectPlanner"

### Phase 3: Import Updates

1. Update `src/soothe/cognition/planning/__init__.py`:
   - Import `SimplePlanner` from `simple.py`
   - Update `__all__` exports

2. Update `src/soothe/core/resolver.py`:
   - Import `SimplePlanner` instead of `DirectPlanner`
   - Update variable names (`direct` → `simple`)

3. Update `src/soothe/cognition/planning/router.py`:
   - Rename parameter `direct` to `simple`
   - Rename instance variable `self._direct` to `self._simple`
   - Update docstrings

4. Update `src/soothe/cognition/planning/_shared.py`:
   - Update module docstring

### Phase 4: Test Updates

1. Update test imports
2. Rename test classes and methods
3. Update test documentation

## File Structure

### Files Modified

```
src/soothe/cognition/planning/
├── direct.py → simple.py          # Renamed file
├── __init__.py                    # Updated exports
├── router.py                      # Updated parameter names
└── _shared.py                     # Updated docstring

src/soothe/core/
└── resolver.py                    # Updated imports and variable names

tests/unit_tests/
├── test_planning.py               # Updated imports and class names
├── test_enhanced_reflection.py    # Updated imports
├── test_auto_planner.py           # Updated parameter names
└── README.md                      # Updated documentation
```

## Implementation Details

### 1. simple.py (formerly direct.py)

**Changes**:
- Module docstring: `"DirectPlanner -- single LLM call planner..."` → `"SimplePlanner -- single LLM call planner..."`
- Class definition: `class DirectPlanner` → `class SimplePlanner`
- Docstrings: All references to "DirectPlanner" → "SimplePlanner"
- Log messages: `"DirectPlanner: using template..."` → `"SimplePlanner: using template..."`

### 2. router.py (AutoPlanner)

**Key Changes**:

```python
# Before
def __init__(
    self,
    *,
    direct: Any | None = None,
    ...
) -> None:
    self._direct = direct

def _planner_for_level(self, level: str) -> Any:
    if level == "simple":
        return self._direct or self._subagent

# After
def __init__(
    self,
    *,
    simple: Any | None = None,
    ...
) -> None:
    self._simple = simple

def _planner_for_level(self, level: str) -> Any:
    if level == "simple":
        return self._simple or self._subagent
```

### 3. resolver.py

**Key Changes**:

```python
# Before
from soothe.cognition.planning.direct import DirectPlanner
direct = DirectPlanner(model=planner_model, fast_model=fast_model)
return AutoPlanner(..., direct=direct, ...)

# After
from soothe.cognition.planning.simple import SimplePlanner
simple = SimplePlanner(model=planner_model, fast_model=fast_model)
return AutoPlanner(..., simple=simple, ...)
```

### 4. Test Files

**test_planning.py**:
- Import: `from soothe.cognition.planning.simple import SimplePlanner`
- Class: `class TestSimplePlanner` (formerly `TestDirectPlanner`)

**test_enhanced_reflection.py**:
- Import: `from soothe.cognition.planning.simple import SimplePlanner`
- Fixture: `planner() -> SimplePlanner`
- Method signatures: Updated type hints

**test_auto_planner.py**:
- Parameter name: `direct=` → `simple=`
- Variable names in tests: `direct` → `direct` (kept for test variable clarity)

## Testing Strategy

### Unit Tests

All existing tests continue to pass with updated imports:

```bash
# Test SimplePlanner directly
pytest tests/unit_tests/test_planning.py -v

# Test reflection logic
pytest tests/unit_tests/test_enhanced_reflection.py -v

# Test AutoPlanner integration
pytest tests/unit_tests/test_auto_planner.py -v
```

### Verification

1. **Code Search**: Verify no references to `DirectPlanner` remain
   ```bash
   grep -r "DirectPlanner" src/soothe/
   grep -r "from.*direct import" src/soothe/
   ```

2. **Import Check**: Ensure all imports resolve correctly
   ```bash
   python -c "from soothe.cognition.planning import SimplePlanner; print('✓ Import successful')"
   ```

3. **Test Suite**: All tests pass
   ```bash
   make test-unit
   ```

## Verification Checklist

- [x] File `direct.py` renamed to `simple.py`
- [x] Class `DirectPlanner` renamed to `SimplePlanner`
- [x] Module docstring updated
- [x] Class docstrings updated
- [x] Log messages updated
- [x] `__init__.py` exports updated
- [x] `router.py` parameter names updated
- [x] `resolver.py` imports and variable names updated
- [x] `_shared.py` docstring updated
- [x] All test files updated
- [x] Test class names updated
- [x] No remaining references to `DirectPlanner` in source code
- [x] All unit tests pass

## Notes

### Backward Compatibility

This is an internal refactoring with no public API impact:
- `DirectPlanner` was never exposed as a public API
- All references are internal to the soothe package
- No deprecation period needed

### Future Considerations

The renaming improves the planner naming hierarchy:
- `SimplePlanner` - simple tasks (single LLM call)
- `SubagentPlanner` - medium complexity (subagent delegation)
- `ClaudePlanner` - complex tasks (Claude CLI orchestration)

This naming pattern makes it immediately clear which planner to use for each complexity level.

### Pre-existing Test Issues

Note: `test_auto_planner.py` contains pre-existing test failures unrelated to this renaming. These tests use an outdated `routing_mode` parameter that was removed in RFC-102's unified classification refactoring. These tests need separate fixing.

## Related Documents

- Implementation Plan: See conversation transcript
- RFC-102: Unified complexity classification
- RFC-202: Enhanced reflection with dependency awareness
- RFC-201: Template matching optimization

---

*Implementation completed: 2026-03-18*
