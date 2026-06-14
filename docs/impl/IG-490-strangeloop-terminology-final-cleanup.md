# IG-490: StrangeLoop Terminology Final Cleanup

## Summary
Complete the AgentLoop → StrangeLoop migration by cleansing remaining terminology
in RFC filenames, IG filenames, config fields, code references, and docs.
Also fixed daemon hanging issue where CLI timed out waiting for running status.

## Background
IG-488 renamed the core class from `AgentLoop` to `StrangeLoop` (alias `Sloop`).
This IG finishes the cleanup by renaming all remaining references.

## Changes Completed

### 1. Daemon Hanging Fix
**Issue**: CLI `soothe --no-tui` would hang because the daemon didn't emit `status: running`
fast enough after receiving `loop_input`.

**Fix**: Emit `status: running` early in `_process_loop_input_message()` after
`bind_execution_thread_for_loop()` succeeds (handlers.py lines 180-187).

### 2. RFC Filename Renames (8 files)
Renamed from `RFC-XXX-agentloop-*.md` to `RFC-XXX-strangeloop-*.md`:
- RFC-201, RFC-203, RFC-207, RFC-213, RFC-214, RFC-215, RFC-216, RFC-218

### 3. IG Filename Renames (9 files)
Renamed from `IG-XXX-agentloop-*.md` to `IG-XXX-strangeloop-*.md`:
- IG-479, IG-369, IG-370, IG-380, IG-386, IG-387, IG-397, IG-398, IG-420

### 4. Config Field Renames
`agentloop_pool_size` → `sloop_pool_size` in:
- config/*.yml files
- packages/soothe/src/soothe/config/models.py
- packages/soothe-daemon/src/soothe_daemon/config/models.py
- packages/soothe-daemon/src/soothe_daemon/persistence/pool_sizing.py

### 5. Function Renames
- `recommended_agentloop_pool_size` → `recommended_sloop_pool_size`

### 6. Variable Renames
- `_agentloop_shared_pool` → `_sloop_shared_pool`
- `get_agentloop_shared_pool` → `get_sloop_shared_pool`
- `agentloop_result` → `sloop_result` (in planner.reflect)

### 7. Test Function Renames
- `test_agentloop_*` → `test_sloop_*` or `test_strangeloop_*`

### 8. Doc Cross-References Updated
All internal references in docs now use new filenames.

## NOT Changed (Migration Compatibility)
Database table names `agentloop_checkpoints` and `agentloop_loops` remain unchanged
to maintain migration checksum compatibility with existing databases. The SQL
migration filename `001_agentloop_tables.sql` also remains unchanged.

### 9. Runner and Client Terminology (IG-488 Phase 7/8 completion)
- Renamed `_runner_agentic.py` → `_runner_strange_loop.py`
- Renamed `AgenticMixin` → `StrangeLoopMixin`, `_run_agentic_loop` → `_run_strange_loop`
- Updated desktop app event namespaces: `soothe.cognition.agent_loop.*` → `soothe.cognition.strange_loop.*`
- Renamed test files: `test_agent_loop_*` → `test_strange_loop_*`, `test_agentic_*` → `test_strange_loop_*`
- Renamed wiki `agent-loop.md` → `strangeloop.md` and updated cross-references
- Renamed diagram/script assets to `strange_loop_graph.*` and `visualize_strange_loop_graph.py`

## Verification
- All lint checks pass
- All tests pass
- CLI `soothe --no-tui` works without hanging