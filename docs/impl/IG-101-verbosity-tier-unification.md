# IG-101: VerbosityTier Unification Implementation

**RFC**: RFC-0024
**Status**: Draft
**Created**: 2026-03-29
**Dependencies**: RFC-0015

## Overview

This guide implements RFC-0024, replacing the two-layer event classification system with a unified `VerbosityTier` enum. The implementation eliminates duplicate enums (`ProgressCategory`, `EventCategory`), simplifies classification logic, and uses integer comparison for visibility checks.

## Requirements Checklist

From RFC-0024:

- [ ] `VerbosityTier` IntEnum with five tiers: `QUIET=0`, `NORMAL=1`, `DETAILED=2`, `DEBUG=3`, `INTERNAL=99`
- [ ] `should_show(tier, verbosity)` using integer comparison
- [ ] `classify_event_to_tier(event_type, namespace)` for direct classification
- [ ] `EventMeta.verbosity` type changed to `VerbosityTier`
- [ ] Domain default tier mapping in registry
- [ ] All event registrations updated with `VerbosityTier` values
- [ ] `ProgressCategory` and `EventCategory` enums removed
- [ ] `progress_verbosity.py` deleted
- [ ] All `should_show("string", ...)` calls replaced with `should_show(VerbosityTier.X, ...)`

## Module Structure

```
src/soothe/
├── core/
│   └── event_catalog.py      # MODIFY: EventMeta.verbosity type, _reg() calls
└── ux/
    └── core/
        ├── verbosity_tier.py  # NEW: VerbosityTier, should_show, classify_event_to_tier
        ├── progress_verbosity.py  # DELETE
        ├── display_policy.py  # MODIFY: Remove EventCategory
        ├── event_processor.py # MODIFY: Import and use VerbosityTier
        └── message_processing.py  # MODIFY: Import and use VerbosityTier
```

## Type Definitions

### VerbosityTier (NEW)

**File**: `src/soothe/ux/core/verbosity_tier.py`

```python
from enum import IntEnum
from typing import Literal

VerbosityLevel = Literal["quiet", "normal", "detailed", "debug"]

class VerbosityTier(IntEnum):
    """Minimum verbosity level at which content is visible."""
    QUIET = 0      # Always visible
    NORMAL = 1     # Standard progress
    DETAILED = 2   # Detailed internals
    DEBUG = 3      # Everything
    INTERNAL = 99  # Never shown
```

### EventMeta Update

**File**: `src/soothe/core/event_catalog.py`

```python
# Before
verbosity: ProgressCategory

# After
verbosity: VerbosityTier
```

## Implementation Tasks

### Task 1: Create verbosity_tier.py

**File**: `src/soothe/ux/core/verbosity_tier.py` (new)

Create the module with:
1. `VerbosityLevel` type alias (imported from here by display_policy.py)
2. `VerbosityTier` IntEnum
3. `_VERBOSITY_LEVEL_VALUES` mapping dict
4. `should_show(tier, verbosity)` function
5. `classify_event_to_tier(event_type, namespace)` function

### Task 2: Update event_catalog.py

**File**: `src/soothe/core/event_catalog.py`

Changes:
1. Add import: `from soothe.ux.core.verbosity_tier import VerbosityTier`
2. Remove `ProgressCategory` type alias (if defined locally) or remove import
3. Update `EventMeta.verbosity` type annotation to `VerbosityTier`
4. Replace `_DOMAIN_DEFAULT_VERBOSITY` with `_DOMAIN_DEFAULT_TIER` using `VerbosityTier` values
5. Update `get_verbosity()` return type to `VerbosityTier`
6. Update all `_reg()` calls to use `VerbosityTier` enum values

### Task 3: Remove EventCategory from display_policy.py

**File**: `src/soothe/ux/core/display_policy.py`

Changes:
1. Remove `EventCategory` enum class
2. Add import: `from soothe.ux.core.verbosity_tier import VerbosityTier, should_show, classify_event_to_tier`
3. Update `_classify_event()` to return `VerbosityTier` and delegate to `classify_event_to_tier()`
4. Replace `_should_show_category()` with `_should_show_tier()` using `should_show()`
5. Update `should_show_event()` to use the new tier-based methods

### Task 4: Update event_processor.py

**File**: `src/soothe/ux/core/event_processor.py`

Changes:
1. Update import: `from soothe.ux.core.verbosity_tier import VerbosityTier, should_show`
2. Replace `should_show("protocol", ...)` with `should_show(VerbosityTier.DETAILED, ...)`
3. Replace `should_show("assistant_text", ...)` with `should_show(VerbosityTier.QUIET, ...)`
4. Replace `should_show("error", ...)` with `should_show(VerbosityTier.QUIET, ...)`
5. Update `classify_custom_event` import to `classify_event_to_tier`

### Task 5: Update message_processing.py

**File**: `src/soothe/ux/core/message_processing.py`

Changes:
1. Update import: `from soothe.ux.core.verbosity_tier import VerbosityTier, should_show`
2. Replace `should_show("protocol", ...)` with `should_show(VerbosityTier.DETAILED, ...)`
3. Replace `should_show("assistant_text", ...)` with `should_show(VerbosityTier.QUIET, ...)`

### Task 6: Update renderer.py

**File**: `src/soothe/ux/cli/renderer.py`

Changes:
1. Update import: `from soothe.ux.core.verbosity_tier import VerbosityTier, should_show`
2. Replace `should_show("protocol", ...)` with `should_show(VerbosityTier.DETAILED, ...)`

### Task 7: Update daemon/client_session.py

**File**: `src/soothe/daemon/client_session.py`

Changes:
1. Update import: `from soothe.ux.core.verbosity_tier import VerbosityTier, should_show`
2. Update `should_show()` call to pass `VerbosityTier` instead of string

### Task 8: Update standalone.py

**File**: `src/soothe/ux/cli/execution/standalone.py`

Changes:
1. Update import: `from soothe.ux.core.verbosity_tier import classify_event_to_tier, should_show, VerbosityTier`
2. Replace `classify_custom_event` with `classify_event_to_tier`
3. Update `should_show()` calls with `VerbosityTier`

### Task 9: Delete progress_verbosity.py

**File**: `src/soothe/ux/core/progress_verbosity.py` (delete)

Remove the entire file. All functionality moved to `verbosity_tier.py`.

### Task 10: Update __init__.py exports

**File**: `src/soothe/ux/core/__init__.py`

Changes:
1. Remove exports from `progress_verbosity`
2. Add exports from `verbosity_tier`: `VerbosityTier`, `VerbosityLevel`, `should_show`, `classify_event_to_tier`

### Task 11: Rewrite tests

**File**: `tests/unit/test_progress_verbosity.py` (rename to `test_verbosity_tier.py`)

Rewrite tests for:
1. `VerbosityTier` ordering (QUIET < NORMAL < DETAILED < DEBUG < INTERNAL)
2. `should_show()` at each verbosity level
3. `should_show(INTERNAL, ...)` always returns `False`
4. `classify_event_to_tier()` for soothe.* events
5. `classify_event_to_tier()` for non-soothe events
6. `classify_event_to_tier()` with namespace

## Migration Mapping

### ProgressCategory → VerbosityTier

| Old String | New VerbosityTier |
|------------|-------------------|
| `"assistant_text"` | `VerbosityTier.QUIET` |
| `"error"` | `VerbosityTier.QUIET` |
| `"milestone"` | `VerbosityTier.QUIET` |
| `"plan_update"` | `VerbosityTier.NORMAL` |
| `"subagent_progress"` | `VerbosityTier.NORMAL` |
| `"protocol"` | `VerbosityTier.DETAILED` |
| `"tool_activity"` | `VerbosityTier.DETAILED` |
| `"subagent_custom"` | `VerbosityTier.DETAILED` |
| `"thinking"` | `VerbosityTier.DEBUG` |
| `"debug"` | `VerbosityTier.DEBUG` |
| `"internal"` | `VerbosityTier.INTERNAL` |

### Domain Default Tiers

| Domain | VerbosityTier |
|--------|---------------|
| `lifecycle` | `DETAILED` |
| `protocol` | `DETAILED` |
| `cognition` | `NORMAL` |
| `tool` | `DETAILED` |
| `subagent` | `DETAILED` |
| `output` | `QUIET` |
| `error` | `QUIET` |
| `agentic` | `NORMAL` |

## Testing Strategy

### Unit Tests

1. **VerbosityTier enum**: Verify ordering and values
2. **should_show()**: Test all tier/verbosity combinations
3. **classify_event_to_tier()**: Test soothe.* events via registry
4. **classify_event_to_tier()**: Test non-soothe fallbacks
5. **Registry integration**: Verify `get_verbosity()` returns correct tier

### Integration Tests

1. **End-to-end event flow**: Emit events, verify correct filtering at each verbosity
2. **Daemon filtering**: Verify daemon-side filtering uses new tier system

### Verification

```bash
./scripts/verify_finally.sh
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Missed `should_show()` caller | Full test suite coverage, grep for all usages |
| Circular import | `VerbosityLevel` defined in `verbosity_tier.py`, imported by `display_policy.py` |
| Type errors in registry | Update `EventMeta` type annotation, verify all `_reg()` calls |

## Success Criteria

- [ ] All tests pass (`./scripts/verify_finally.sh`)
- [ ] No `ProgressCategory` or `EventCategory` references remain
- [ ] `progress_verbosity.py` deleted
- [ ] `classify_custom_event` replaced with `classify_event_to_tier`
- [ ] All `should_show()` calls use `VerbosityTier` enum
- [ ] ~90 lines of code removed (classification simplification)