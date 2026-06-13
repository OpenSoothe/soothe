# IG-488: StrangeLoop → StrangeLoop Name Migration

## Scope
Rename `StrangeLoop` to `StrangeLoop` (short alias: `Sloop`) across the entire codebase.

## Naming Decisions
| Old | New |
|-----|-----|
| `StrangeLoop` class | `StrangeLoop` (alias: `Sloop`) |
| `StrangeLoopProtocol` | `StrangeLoopProtocol` |
| `strange_loop.py` file | `strange_loop.py` |
| `soothe.cognition.strange_loop.*` events | `soothe.cognition.strange_loop.*` |
| `strange_loop_*` config | `sloop_*` |
| `strange_loop` (snake_case refs) | `strange_loop` |
| `StrangeLoopStateManager` | `StrangeLoopStateManager` |
| `StrangeLoopCheckpoint` | `StrangeLoopCheckpoint` |

## Backward Compatibility Aliases Added
All old names have backward compatibility aliases so existing imports continue to work:
- `StrangeLoop = StrangeLoop`
- `StrangeLoopProtocol = StrangeLoopProtocol`
- `StrangeLoopStateManager = StrangeLoopStateManager`
- `StrangeLoopCheckpoint = StrangeLoopCheckpoint`
- `STRANGE_LOOP_* = STRANGE_LOOP_*` (event constants)
- `StrangeLoopStartedEvent = StrangeLoopStartedEvent` (event classes)
- `build_strange_loop_graph = build_strange_loop_graph`
- `invoke_strange_loop_graph = invoke_strange_loop_graph`
- `ctx.strange_loop` property on LoopRuntimeContext

## Status
- [x] Phase 1: Core Python (classes, protocols, files) - DONE
  - Classes renamed with backward compat aliases
  - Files renamed: strange_loop.py → strange_loop.py, manager.py → sloop_manager.py
  - RuntimeContext updated: strange_loop field + strange_loop property
  - Orchestrator builder/runner renamed with aliases
  - Events constants/catalog updated with aliases
  - Imports updated in foundation.loop modules
- [x] Phase 2: Events - DONE (with backward compat aliases)
- [x] Phase 3: Config - NOT NEEDED (using backward compat)
- [ ] Phase 4: Tests - IN PROGRESS
  - Need to update test files that:
    - Pass `strange_loop=` to LoopRuntimeContext → use `strange_loop=`  
    - Update mock patch paths to new module paths
    - Update langfuse run_name assertions
- [ ] Phase 5: Documentation - TODO
  - RFCs still reference "StrangeLoop"
  - IGs still reference "StrangeLoop"
  - User guide still references "StrangeLoop"
- [ ] Phase 6: Scripts/Diagrams - TODO

## Remaining Test Failures
Key patterns to fix in tests:
1. `LoopRuntimeContext(strange_loop=...)` → `LoopRuntimeContext(strange_loop=...)`
2. Mock paths like `soothe.foundation.loop.engine.strange_loop.StrangeLoopStateManager` → `soothe.foundation.loop.state.sloop_manager.StrangeLoopStateManager`
3. Langfuse run_name assertions: `'strange-loop-graph'` → `'strange-loop-graph'`

## Verification
Run `./scripts/verify_finally.sh` after completion.