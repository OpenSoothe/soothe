# IG-060: Implementation Guide Renaming

**Status**: In Progress
**Created**: 2026-03-26
**Purpose**: Rename all implementation guides with IG- prefix and update all references

## Overview

Standardize naming convention for all implementation guides by adding the `IG-` prefix to all files in `docs/impl/` directory.

## Background

Implementation guides should have a consistent naming prefix `IG-` to clearly distinguish them from other documentation files. Currently, only one file follows this convention: `IG-053-cli-tui-event-progress.md`. All other guides need to be renamed.

## Implementation Plan

### Phase 1: File Renaming

Rename all implementation guides from `NNN-description.md` to `IG-NNN-description.md`:

**Files to rename** (as of 2026-03-26):
- `001-soothe-setup-migration.md` → `IG-001-soothe-setup-migration.md`
- `002-soothe-polish.md` → `IG-002-soothe-polish.md`
- `003-streaming-examples.md` → `IG-003-streaming-examples.md`
- `004-ecosystem-capability-analysis.md` → `IG-004-ecosystem-capability-analysis.md`
- `005-core-protocols-implementation.md` → `IG-005-core-protocols-implementation.md`
- `006-vectorstore-router-persistence.md` → `IG-006-vectorstore-router-persistence.md`
- `007-cli-tui-implementation.md` → `IG-007-cli-tui-implementation.md`
- `008-config-docs-revision.md` → `IG-008-config-docs-revision.md`
- `009-ollama-provider.md` → `IG-009-ollama-provider.md`
- `010-tui-layout-history-refresh.md` → `IG-010-tui-layout-history-refresh.md`
- `011-skillify-agent-implementation.md` → `IG-011-skillify-agent-implementation.md`
- `012-weaver-agent-implementation.md` → `IG-012-weaver-agent-implementation.md`
- `013-soothe-polish-pass.md` → `IG-013-soothe-polish-pass.md`
- `014-code-structure-revision.md` → `IG-014-code-structure-revision.md`
- `015-rfc-gap-closure-and-compat-hard-cut.md` → `IG-015-rfc-gap-closure-and-compat-hard-cut.md`
- `016-agent-optimization-pass.md` → `IG-016-agent-optimization-pass.md`
- `017-progress-events-tools-polish.md` → `IG-017-progress-events-tools-polish.md`
- `018-autonomous-iteration-loop.md` → `IG-018-autonomous-iteration-loop.md`
- `019-soothe-tools-enhancement.md` → `IG-019-soothe-tools-enhancement.md`
- `020-detached-daemon-autonomous-capability.md` → `IG-020-detached-daemon-autonomous-capability.md`
- `021-daemon-lifecycle-fixes.md` → `IG-021-daemon-lifecycle-fixes.md`
- `021-dag-execution-unified-concurrency.md` → `IG-021-dag-execution-unified-concurrency.md`
- `021-performance-optimization-implementation.md` → `IG-021-performance-optimization-implementation.md`
- `022-rfc0009-gaps-tests-tui-dag.md` → `IG-022-rfc0009-gaps-tests-tui-dag.md`
- `022-unified-persistence-storage.md` → `IG-022-unified-persistence-storage.md`
- `023-failure-recovery-progressive-persistence.md` → `IG-023-failure-recovery-progressive-persistence.md`
- `023-postgres-db-separation-and-persistence-deadlock-fix.md` → `IG-023-postgres-db-separation-and-persistence-deadlock-fix.md`
- `024-existing-browser-connection.md` → `IG-024-existing-browser-connection.md`
- `024-rfc0010-gap-fixes.md` → `IG-024-rfc0010-gap-fixes.md`
- `025-subagent-progress-visibility.md` → `IG-025-subagent-progress-visibility.md`
- `026-rfc0009-logging-enhancements.md` → `IG-026-rfc0009-logging-enhancements.md`
- `027-final-report-cli-output.md` → `IG-027-final-report-cli-output.md`
- `028-direct-to-simple-planner-renaming.md` → `IG-028-direct-to-simple-planner-renaming.md`
- `028-dynamic-goal-management.md` → `IG-028-dynamic-goal-management.md`
- `029-planner-refactoring.md` → `IG-029-planner-refactoring.md`
- `032-unified-complexity-classification.md` → `IG-032-unified-complexity-classification.md`
- `033-secure-filesystem-path-handling.md` → `IG-033-secure-filesystem-path-handling.md`
- `034-cli-modularization.md` → `IG-034-cli-modularization.md`
- `035-scout-then-plan-implementation.md` → `IG-035-scout-then-plan-implementation.md`
- `036-planning-workflow-refactoring.md` → `IG-036-planning-workflow-refactoring.md`
- `037-unified-classifier-refactoring.md` → `IG-037-unified-classifier-refactoring.md`
- `038-code-structure-refactoring.md` → `IG-038-code-structure-refactoring.md`
- `039-capability-abstraction-tool-consolidation.md` → `IG-039-capability-abstraction-tool-consolidation.md`
- `040-tool-optimization-complete.md` → `IG-040-tool-optimization-complete.md`
- `041-cli-polish.md` → `IG-041-cli-polish.md`
- `042-tool-events-polish.md` → `IG-042-tool-events-polish.md`
- `043-planning-unified-architecture-guide.md` → `IG-043-planning-unified-architecture-guide.md`
- `043-unified-planning-complete.md` → `IG-043-unified-planning-complete.md`
- `044-unified-planning-final-report.md` → `IG-044-unified-planning-final-report.md`
- `045-agentic-loop-implementation.md` → `IG-045-agentic-loop-implementation.md`
- `046-unified-daemon-protocol.md` → `IG-046-unified-daemon-protocol.md`
- `047-daemon-integration-test-coverage.md` → `IG-047-daemon-integration-test-coverage.md`
- `047-event-bus-architecture.md` → `IG-047-event-bus-architecture.md`
- `047-memu-migration-python-version-update.md` → `IG-047-memu-migration-python-version-update.md`
- `047-module-self-containment-refactoring-COMPLETED.md` → `IG-047-module-self-containment-refactoring-COMPLETED.md`
- `047-module-self-containment-refactoring-FINAL.md` → `IG-047-module-self-containment-refactoring-FINAL.md`
- `047-module-self-containment-refactoring.md` → `IG-047-module-self-containment-refactoring.md`
- `047-skills-migration.md` → `IG-047-skills-migration.md`
- `047-tui-claude-code-layout-refactor.md` → `IG-047-tui-claude-code-layout-refactor.md`
- `047-ux-module-refactoring.md` → `IG-047-ux-module-refactoring.md`
- `048-thread-management-final-report.md` → `IG-048-thread-management-final-report.md`
- `049-rfc0017-thread-resume-history-recovery.md` → `IG-049-rfc0017-thread-resume-history-recovery.md`
- `050-cli-subcommand-flattening.md` → `IG-050-cli-subcommand-flattening.md`
- `051-plugin-api-implementation.md` → `IG-051-plugin-api-implementation.md`
- `052-rfc0018-event-system-optimization.md` → `IG-052-rfc0018-event-system-optimization.md`
- `054-event-constants-self-containment.md` → `IG-054-event-constants-self-containment.md`
- `055-essential-progress-events.md` → `IG-055-essential-progress-events.md`
- `056-paperscout-community-plugin.md` → `IG-056-paperscout-community-plugin.md`
- `057-dynamic-subagent-registration.md` → `IG-057-dynamic-subagent-registration.md`
- `058-soothe-community-package-polish.md` → `IG-058-soothe-community-package-polish.md`
- `059-thread-continue-resume-history.md` → `IG-059-thread-continue-resume-history.md`

**Note**: `IG-053-cli-tui-event-progress.md` already has the correct prefix.

### Phase 2: Update References

Update all references to implementation guides throughout the codebase:

**Files with references** (as of 2026-03-26):
- `docs/specs/RFC-101-tool-interface.md` ✅
- `docs/impl/IG-013-soothe-polish-pass.md` ✅
- `docs/impl/IG-025-subagent-progress-visibility.md` ✅
- `docs/impl/IG-027-final-report-cli-output.md` ✅
- `docs/impl/IG-047-module-self-containment-refactoring-COMPLETED.md` ✅
- `docs/impl/IG-047-module-self-containment-refactoring-FINAL.md` ✅
- `docs/impl/IG-052-rfc0018-event-system-optimization.md` ✅
- `docs/wiki/troubleshooting.md`
- `CLAUDE.md`

**Reference updates needed**:
- `docs/impl/004-ecosystem-capability-analysis.md` → `docs/impl/IG-004-ecosystem-capability-analysis.md` ✅
- `docs/impl/040-tool-optimization-complete.md` → `docs/impl/IG-040-tool-optimization-complete.md` ✅
- `docs/impl/010-tui-layout-history-refresh.md` → `docs/impl/IG-010-tui-layout-history-refresh.md` ✅
- `docs/impl/024-existing-browser-connection.md` → `docs/impl/IG-024-existing-browser-connection.md` ✅
- `docs/impl/024-rfc0010-gap-fixes.md` → `docs/impl/IG-024-rfc0010-gap-fixes.md` ✅
- `docs/impl/047-module-self-containment-refactoring.md` → `docs/impl/IG-047-module-self-containment-refactoring.md` ✅
- `docs/impl/047-module-self-containment-refactoring-FINAL.md` → `docs/impl/IG-047-module-self-containment-refactoring-FINAL.md` ✅

### Phase 3: Update CLAUDE.md

Update the Implementation Guides section in `CLAUDE.md` to reflect the new naming convention and update any specific guide references.

### Phase 4: Verification

1. Run `./scripts/verify_finally.sh` to ensure no regressions
2. Verify all links in markdown files are valid
3. Confirm no orphaned references remain

## Success Criteria

- All implementation guides have `IG-` prefix
- All references updated throughout codebase
- No broken links in documentation
- All tests pass
- Zero linting errors

## Risks

- **Low risk**: This is purely a renaming operation
- All references identified and will be updated
- Git will track file renames automatically

## Timeline

- Estimated time: 15-20 minutes
- File renaming: 5 minutes (using git mv)
- Reference updates: 10 minutes
- Verification: 5 minutes