# IG-191: Soothe-SDK Deprecation and Legacy Cleanup

**Status**: Completed
**Created**: 2026-04-18
**RFC References**: N/A (Maintenance)
**Impact**: soothe-sdk, soothe, soothe-cli

---

## Overview

Remove all deprecation and legacy indicators from soothe-sdk package and adapt dependent packages accordingly. This is a maintenance task to clean up documentation and code references that are no longer relevant.

### Motivation

The soothe-sdk package has accumulated several deprecation markers and legacy references that are either:
- Already removed (e.g., types/ directory)
- No longer accurate (e.g., legacy Unix socket references)
- Compatibility aliases that should be replaced with clean breaks

This guide ensures clean documentation and removes backward compatibility baggage.

---

## Implementation Plan

### Phase 1: Documentation Cleanup

**Tasks**:
1. Remove deprecated types/ directory references from MIGRATION.md and README.md
2. Remove legacy Unix socket reference from websocket.py docstring
3. Remove planned removal note from MIGRATION.md (migration complete)
4. Update MIGRATION.md to reflect final state

### Phase 2: Documentation Clarification

**Tasks**:
1. Clarify stub implementation note in events.py (better document SDK-side purpose)
2. Update verbosity.py docstring to clarify "minimal" is a valid option, not deprecated alias

### Phase 3: Cross-Package Adaptation

**Tasks**:
1. Search soothe package for references to removed items
2. Search soothe-cli package for references to removed items
3. Update any dependent code or documentation

### Phase 4: Verification

**Tasks**:
1. Run verification script
2. Update CHANGELOG if applicable

---

## File Structure

### Files to Modify

```
packages/soothe-sdk/
├── MIGRATION.md                       # Remove types/, migration notes
├── README.md                          # Remove types/ reference
└── src/soothe_sdk/
    ├── client/websocket.py            # Remove legacy Unix socket reference
    ├── verbosity.py                   # Clarify minimal is valid option
    └── events.py                      # Clarify SDK-side purpose

packages/soothe/
└── (any files referencing removed items)

packages/soothe-cli/
└── (any files referencing removed items)
```

---

## Implementation Details

### 1. MIGRATION.md Updates

**Remove**:
- Line 121: `└── types/                # Deprecated (empty)`
- Lines 9-41: Migration plan notes (already complete)
- Any references to "to be removed"

**Keep**:
- Current structure documentation
- Migration instructions for users

### 2. README.md Updates

**Remove**:
- Line 235: `└── types/                # Deprecated (empty)`

**Update**:
- Directory structure to reflect current state

### 3. websocket.py Docstring Update

**Current** (line 27):
```python
"""WebSocket client that provides the same interface as the legacy Unix socket client."""
```

**New**:
```python
"""WebSocket client for communicating with Soothe daemon."""
```

### 4. verbosity.py Documentation Update

**Current** (lines 12-16):
```python
VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]
"""User-configured verbosity level for filtering display content.

`minimal` is accepted as a compatibility alias for `normal`.
"""
```

**New**:
```python
VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]
"""User-configured verbosity level for filtering display content.

Both `minimal` and `normal` are valid verbosity levels that map to VerbosityTier.NORMAL.
This provides flexibility for user preference without changing behavior.
"""
```

**Note**: "minimal" is NOT deprecated. Both "minimal" and "normal" are valid options
that map to the same tier (NORMAL=1). This is intentional design, not a compatibility alias.

### 5. events.py Stub Clarification

**Current** (lines 37-39):
```python
# This is a stub for SDK compatibility
# The actual implementation is in soothe.utils.progress on daemon side
pass
```

**New**:
```python
# SDK-side event base class
# Daemon-side implementation provides actual emit functionality
pass
```

---

## Testing Strategy

### Unit Tests
- No new tests needed (removing deprecated items, not adding features)
- Existing tests should continue to pass

### Integration Tests
- Run verification script after changes
- Check for any broken references

---

## Verification Checklist

- [ ] MIGRATION.md cleaned of deprecated references
- [ ] README.md cleaned of deprecated references
- [ ] websocket.py docstring updated
- [ ] verbosity.py minimal alias removed
- [ ] events.py stub comment clarified
- [ ] Cross-package search completed
- [ ] All dependent code updated
- [ ] `./scripts/verify_finally.sh` passes
- [ ] CHANGELOG updated (if applicable)

---

## Risk Assessment

**Low Risk**:
- Documentation changes (no code impact)
- Already-removed types/ directory references
- Stub comment clarification
- Verbosity documentation update (no code change)

**Mitigation**:
- Grep search for all references before removal
- Run verification script before commit

---

## Notes

- This is cleanup work, not feature development
- No RFC needed (maintenance task)
- Follow CLAUDE.md rules: run verification before commit