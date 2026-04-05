# RFC-600 Event System Optimization Implementation Guide

**Guide**: 052
**Title**: RFC-600 Event System Optimization
**Status**: In Progress
**Created**: 2026-03-25
**Dependencies**: RFC-600, IG-047

## Objective

Optimize the event system architecture to support RFC-600's plugin extension system by:
1. Creating a decentralized event registration API
2. Enabling third-party plugins to register custom events
3. Achieving module self-containment for event definitions
4. Removing backward compatibility code and duplication

## Background

RFC-600 introduces a plugin extension system that allows third-party developers to create custom tools and subagents. The current event system has two critical issues:

1. **Inconsistency**: Plugin lifecycle events are not registered in the event catalog
2. **Centralization**: All events must be registered in `core/event_catalog.py`, preventing third-party plugins from adding custom events

## Architecture Changes

### Current Architecture (Problems)
```
core/events.py           ← Constants only
core/base_events.py      ← Base classes
core/event_catalog.py    ← Monolithic registry (874 lines, 50+ registrations)
  ├── Defines core events
  ├── Imports ALL tool/subagent events
  └── Registers everything centrally

tools/*/events.py        ← Event definitions (must be imported in event_catalog)
subagents/*/events.py    ← Event definitions (must be imported in event_catalog)
plugin/events.py         ← NOT REGISTERED (missing from event_catalog)
```

### New Architecture (Solution)
```
core/events.py           ← Constants (including PLUGIN_*)
core/base_events.py      ← Base classes (unchanged)
core/event_catalog.py    ← Core events only + registration API
  ├── Defines core events
  ├── Provides register_event() API
  └── Calls module register_events() functions

tools/*/events.py        ← Event definitions + register_events()
subagents/*/events.py    ← Event definitions + register_events()
plugin/events.py         ← Event definitions + register_events() at module load

Third-party plugins      ← Can register custom events via API
```

## Implementation Phases

### Phase 1: Create Registration API ✅

**Goal**: Provide clean public API for decentralized event registration.

**Changes**:
- Add `register_event()` public API to `core/event_catalog.py`
- Auto-extract type string from event class Pydantic model
- Parse domain/component/action from type string
- Set default verbosity based on domain conventions
- Keep `_reg()` as internal helper for core events

**Files Modified**:
- `src/soothe/core/event_catalog.py`

**Verification**:
```python
from soothe.core.event_catalog import register_event, REGISTRY
from soothe.core.base_events import SootheEvent

class TestEvent(SootheEvent):
    type: str = "soothe.test.custom.event"

register_event(TestEvent, verbosity="debug", summary_template="Test: {data}")
assert REGISTRY.get_meta("soothe.test.custom.event") is not None
```

### Phase 2: Migrate Plugin Events

**Goal**: Make plugin lifecycle events self-contained.

**Changes**:
1. Add plugin event constants to `core/events.py`:
   - `PLUGIN_LOADED = "soothe.plugin.loaded"`
   - `PLUGIN_FAILED = "soothe.plugin.failed"`
   - `PLUGIN_UNLOADED = "soothe.plugin.unloaded"`
   - `PLUGIN_HEALTH_CHECKED = "soothe.plugin.health_checked"`

2. Update `plugin/events.py` to use `register_event()` API:
   - Import `register_event` from `core.event_catalog`
   - Call `register_event()` for each event class at module load time
   - Remove dependency on central registration in `event_catalog.py`

**Files Modified**:
- `src/soothe/core/events.py`
- `src/soothe/plugin/events.py`

**Verification**:
```python
from soothe.core.event_catalog import REGISTRY

# Plugin events should be registered
meta = REGISTRY.get_meta("soothe.plugin.loaded")
assert meta is not None
assert meta.domain == "plugin"
assert meta.summary_template != ""
```

### Phase 3: Migrate Tool/Subagent Events

**Goal**: Module self-containment for all built-in modules.

**Changes**:
1. For each tool module (`tools/*/events.py`):
   - Add `register_events()` function
   - Call `register_event()` for each event class
   - Call `register_events()` at module load time

2. For each subagent module (`subagents/*/events.py`):
   - Same pattern as tools

3. Update `core/event_catalog.py`:
   - Remove tool/subagent event imports
   - Remove tool/subagent event `_reg()` calls
   - Keep only core event definitions and registrations

**Tool Modules** (11 total):
- `tools/execution/events.py`
- `tools/file_ops/events.py`
- `tools/code_edit/events.py`
- `tools/data/events.py`
- `tools/audio/events.py`
- `tools/video/events.py`
- `tools/image/events.py`
- `tools/goals/events.py`
- `tools/datetime/events.py`
- `tools/research/events.py`
- `tools/web_search/events.py`

**Subagent Modules** (4 total):
- `subagents/browser/events.py`
- `subagents/claude/events.py`
- `subagents/skillify/events.py`
- `subagents/weaver/events.py`

**Files Modified**:
- All `src/soothe/tools/*/events.py`
- All `src/soothe/subagents/*/events.py`
- `src/soothe/core/event_catalog.py`

**Verification**:
```python
from soothe.core.event_catalog import REGISTRY

# Tool events should still be registered
assert REGISTRY.get_meta("soothe.tool.research.analyze") is not None
assert REGISTRY.get_meta("soothe.tool.websearch.search_started") is not None

# Subagent events should still be registered
assert REGISTRY.get_meta("soothe.subagent.browser.step") is not None
assert REGISTRY.get_meta("soothe.subagent.claude.text") is not None
```

### Phase 4: Remove Backward Compatibility Code

**Goal**: Clean codebase, remove duplication and compat shims.

**Changes**:
1. Identify and remove:
   - Duplicate event class definitions in `event_catalog.py`
   - Unused imports in `event_catalog.py`
   - Deprecated import paths
   - Unused event constants

2. Clean up `core/event_catalog.py`:
   - Should only contain core event definitions
   - Should be significantly smaller (~400 lines vs 874 lines)

3. Update tests if needed:
   - Ensure all tests pass with new architecture
   - Remove tests for deprecated code paths

**Files Modified**:
- `src/soothe/core/event_catalog.py`
- `tests/` (if needed)

**Verification**:
```bash
# Run full test suite
uv run pytest tests/ -v

# Check line count reduction
wc -l src/soothe/core/event_catalog.py
# Should be ~400 lines instead of 874
```

### Phase 5: Update Documentation

**Goal**: Document the new pattern for plugin developers.

**Changes**:
1. Update `docs/specs/RFC-600-plugin-extension-system.md`:
   - Add "Event Registration" section
   - Document `register_event()` API
   - Show examples for third-party plugins

2. Create `docs/plugin_development.md`:
   - Guide for creating plugins with custom events
   - Event registration best practices
   - Examples and patterns

3. Create `examples/plugins/custom_events/`:
   - Example plugin with custom events
   - Demonstrates registration in `on_load()` hook

4. Update `CLAUDE.md`:
   - Add event registration section to architecture
   - Reference the new pattern

**Files Created/Modified**:
- `docs/specs/RFC-600-plugin-extension-system.md`
- `docs/plugin_development.md` (new)
- `examples/plugins/custom_events/` (new)
- `CLAUDE.md`

## Testing Strategy

### Unit Tests
```bash
# Test registration API
pytest tests/unit/test_event_catalog.py -v

# Test plugin events
pytest tests/unit/test_plugin_events.py -v

# Test all tools still emit events correctly
pytest tests/unit/test_tools.py -v

# Test all subagents still emit events correctly
pytest tests/unit/test_subagents.py -v
```

### Integration Tests
```bash
# Test full event flow
pytest tests/integration/test_event_flow.py -v

# Test plugin loading with events
pytest tests/integration/test_plugin_lifecycle.py -v
```

### Manual Verification
```python
from soothe.core.event_catalog import REGISTRY

# Check all expected events are registered
expected_events = [
    "soothe.plugin.loaded",
    "soothe.tool.research.analyze",
    "soothe.subagent.browser.step",
    # ... etc
]

for event_type in expected_events:
    meta = REGISTRY.get_meta(event_type)
    assert meta is not None, f"Event {event_type} not registered"
    print(f"✓ {event_type}: domain={meta.domain}, verbosity={meta.verbosity}")
```

## Success Criteria

- [ ] `register_event()` API available and documented
- [ ] Plugin events registered and accessible via `REGISTRY`
- [ ] All tool/subagent events self-registered
- [ ] `event_catalog.py` reduced to ~400 lines (core events only)
- [ ] No duplicate event definitions
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Example plugin created
- [ ] Zero linting errors

## Risks and Mitigations

### Risk 1: Event Registration Order
**Issue**: Events might be accessed before module is imported.
**Mitigation**: Import modules at the top of `event_catalog.py` to ensure registration happens early.

### Risk 2: Missing Event Registrations
**Issue**: Some events might not be registered during migration.
**Mitigation**: Run comprehensive tests and verify all expected events are in registry.

### Risk 3: Backward Compatibility
**Issue**: Code might depend on current import patterns.
**Mitigation**: Keep event classes importable from `event_catalog` during transition, then remove in Phase 4.

## Timeline

- **Phase 1**: 1 hour (API creation)
- **Phase 2**: 30 minutes (Plugin events)
- **Phase 3**: 3 hours (Migrate all modules)
- **Phase 4**: 2 hours (Clean up)
- **Phase 5**: 2 hours (Documentation)
- **Total**: ~8-10 hours

## References

- RFC-600: Plugin Extension Specification
- IG-047: Module Self-Containment Refactoring
- `docs/impl/IG-047-module-self-containment-refactoring-FINAL.md`

---

**Status Tracking**:
- Phase 1: ✅ Completed
- Phase 2: ✅ Completed
- Phase 3: ✅ Completed
- Phase 4: ✅ Completed
- Phase 5: ⏳ Pending