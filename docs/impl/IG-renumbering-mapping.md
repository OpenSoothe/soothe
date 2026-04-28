# IG Renumbering Mapping Table

## Duplicate IG Files and Renumbering Assignments

### Mapping Rules
- **Keep**: Most comprehensive/primary file for each duplicate number
- **Renumber**: Remaining files assigned new sequential IG-277 through IG-294

### Detailed Mapping

| Current File | Decision | New IG Number |
|-------------|----------|---------------|
| **IG-053 duplicates** |||
| IG-053-fix-planner-early-done-bug.md | Keep | IG-053 (original) |
| IG-053-loop-checkpoint-bug-fixes.md | Renumber | IG-277 |
| **IG-054 duplicates** |||
| IG-054-fix-concurrent-query-race-condition.md | Keep | IG-054 (original) |
| IG-054-postgres-multi-db.md | Renumber | IG-278 |
| **IG-220 duplicates** |||
| IG-220-tui-thread-restore-history-load.md | Keep | IG-220 (original) |
| IG-220-tui-thread-history-enum-mismatch-fix.md | Renumber | IG-279 |
| **IG-225 duplicates** |||
| IG-225-goalengine-multi-goal-enhancement.md | Keep | IG-225 (original) |
| IG-225-cli-assessment-plan-flat-display.md | Renumber | IG-280 |
| **IG-232 duplicates** |||
| IG-232-filesystem-middleware-extension.md | Keep | IG-232 (original) |
| IG-232-tui-daemon-session-rpc-stream-separation.md | Renumber | IG-281 |
| **IG-235 duplicates** |||
| IG-235-unified-tui-message-display-filter.md | Keep | IG-235 (original) |
| IG-235-tui-message-display-polish.md | Renumber | IG-282 |
| **IG-226 duplicates (4 files)** |||
| IG-226-unified-query-intent-classification.md | Keep | IG-226 (original) |
| IG-226-goal-tools-architectural-correction.md | Renumber | IG-283 |
| IG-226-intention-module-refactoring.md | Renumber | IG-284 |
| IG-226-final-migration-complete.md | Renumber | IG-285 |
| **IG-261 duplicates** |||
| IG-261-enhanced-doctor-daemon-status.md | Keep | IG-261 (original) |
| IG-261-subagent-task-display-polish.md | Renumber | IG-286 |
| **IG-262 duplicates (3 files)** |||
| IG-262-cli-display-fixes.md | Keep | IG-262 (original) |
| IG-262-friendly-goal-message.md | Renumber | IG-287 |
| IG-262-263-current-status.md | Renumber | IG-288 |
| **IG-264 duplicates** |||
| IG-264-simplify-planner-schemas.md | Keep | IG-264 (original) |
| IG-264-limited-provider-wrapper-propagation.md | Renumber | IG-289 |
| **IG-258 duplicates (6 files)** |||
| IG-258-daemon-concurrent-performance-optimization.md | Keep | IG-258 (original) |
| IG-258-implementation-complete.md | Renumber | IG-290 |
| IG-258-phase2-implementation.md | Renumber | IG-291 |
| IG-258-phase2-validation-results.md | Renumber | IG-292 |
| IG-258-final-analysis.md | Renumber | IG-293 |
| IG-258-subagent-event-analysis.md | Renumber | IG-294 |

## Summary
- **Files to keep**: 11 files (one per duplicate set)
- **Files to renumber**: 17 files (IG-277 through IG-294)
- **Total duplicate IGs**: 11 numbers (053, 054, 220, 225, 232, 235, 226, 261, 262, 264, 258)

## Renumbering Script
```bash
# Renumber files according to mapping
cd /Users/chenxm/Workspace/Soothe/docs/impl/

# IG-053: loop-checkpoint-bug-fixes → IG-277
mv IG-053-loop-checkpoint-bug-fixes.md IG-277-loop-checkpoint-bug-fixes.md

# IG-054: postgres-multi-db → IG-278
mv IG-054-postgres-multi-db.md IG-278-postgres-multi-db.md

# IG-220: enum-mismatch-fix → IG-279
mv IG-220-tui-thread-history-enum-mismatch-fix.md IG-279-tui-thread-history-enum-mismatch-fix.md

# IG-225: cli-assessment-plan-flat-display → IG-280
mv IG-225-cli-assessment-plan-flat-display.md IG-280-cli-assessment-plan-flat-display.md

# IG-232: tui-daemon-session-rpc-stream-separation → IG-281
mv IG-232-tui-daemon-session-rpc-stream-separation.md IG-281-tui-daemon-session-rpc-stream-separation.md

# IG-235: tui-message-display-polish → IG-282
mv IG-235-tui-message-display-polish.md IG-282-tui-message-display-polish.md

# IG-226 duplicates (3 files)
mv IG-226-goal-tools-architectural-correction.md IG-283-goal-tools-architectural-correction.md
mv IG-226-intention-module-refactoring.md IG-284-intention-module-refactoring.md
mv IG-226-final-migration-complete.md IG-285-final-migration-complete.md

# IG-261: subagent-task-display-polish → IG-286
mv IG-261-subagent-task-display-polish.md IG-286-subagent-task-display-polish.md

# IG-262 duplicates (2 files)
mv IG-262-friendly-goal-message.md IG-287-friendly-goal-message.md
mv IG-262-263-current-status.md IG-288-263-current-status.md

# IG-264: limited-provider-wrapper-propagation → IG-289
mv IG-264-limited-provider-wrapper-propagation.md IG-289-limited-provider-wrapper-propagation.md

# IG-258 duplicates (5 files)
mv IG-258-implementation-complete.md IG-290-implementation-complete.md
mv IG-258-phase2-implementation.md IG-291-phase2-implementation.md
mv IG-258-phase2-validation-results.md IG-292-phase2-validation-results.md
mv IG-258-final-analysis.md IG-293-final-analysis.md
mv IG-258-subagent-event-analysis.md IG-294-subagent-event-analysis.md
```

## Reference Update Mapping

For updating references, use this mapping:

| Old IG | New IG | Files Affected |
|--------|--------|----------------|
| IG-053 → IG-277 | loop-checkpoint-bug-fixes only |
| IG-054 → IG-278 | postgres-multi-db only |
| IG-220 → IG-279 | enum-mismatch-fix only |
| IG-225 → IG-280 | cli-assessment-plan-flat-display only |
| IG-232 → IG-281 | tui-daemon-session-rpc-stream-separation only |
| IG-235 → IG-282 | tui-message-display-polish only |
| IG-226 → IG-283 | goal-tools-architectural-correction only |
| IG-226 → IG-284 | intention-module-refactoring only |
| IG-226 → IG-285 | final-migration-complete only |
| IG-261 → IG-286 | subagent-task-display-polish only |
| IG-262 → IG-287 | friendly-goal-message only |
| IG-262 → IG-288 | 263-current-status only |
| IG-264 → IG-289 | limited-provider-wrapper-propagation only |
| IG-258 → IG-290 | implementation-complete only |
| IG-258 → IG-291 | phase2-implementation only |
| IG-258 → IG-292 | phase2-validation-results only |
| IG-258 → IG-293 | final-analysis only |
| IG-258 → IG-294 | subagent-event-analysis only |

Note: References to the "kept" files (original numbers) remain unchanged.