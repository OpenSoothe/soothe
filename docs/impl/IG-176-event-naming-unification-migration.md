# IG-176: Event Naming Unification Migration

**RFC**: RFC-403 (Unified Event Naming Semantics)
**Status**: Active Implementation
**Date**: 2026-04-15
**Duration**: 4-5 days

---

## 1. Overview

This implementation guide executes the systematic migration of Soothe's event naming system to unified semantics defined in RFC-403.

**Key changes**:
- Present progressive tense for all action verbs
- 9 function-based semantic domains
- Plugin namespace rules for third-party extensions
- Complete migration of 80+ event types

---

## 2. Prerequisites

Before starting:
- RFC-403 approved and finalized
- Clean feature branch created
- All tests passing baseline
- Migration script tested on sample files

---

## 3. Implementation Checklist

### 3.1 Pre-Migration Setup

- [x] RFC-403 created and documented
- [ ] Create `scripts/migrate_event_names.py`
- [ ] Create `scripts/validate_event_names.py`
- [ ] Test migration script on sample files
- [ ] Create clean feature branch: `feat/event-naming-unification`

### 3.2 Phase 1: Event Catalog Migration (Day 1-2)

**Goal**: Update all event type definitions in event catalog and module event files.

- [ ] Update `event_catalog.py`:
  - [ ] Update type string constants
  - [ ] Update event class `type` field defaults
  - [ ] Update `_reg()` calls with new verbosity summaries
  - [ ] Delete old constants

- [ ] Update module event files:
  - [ ] `cognition/agent_loop/events.py`
  - [ ] `subagents/browser/events.py`
  - [ ] `subagents/claude/events.py`
  - [ ] `subagents/research/events.py`
  - [ ] `plugin/events.py`

- [ ] Run `make lint` after each file
- [ ] Run unit tests after Phase 1 completion

### 3.3 Phase 2: Emitter Code Migration (Day 2-3)

**Goal**: Update all event emission sites in runtime code.

- [ ] Find all `custom_event()` calls:
  - [ ] Core runner and agent factory
  - [ ] Protocol implementations
  - [ ] Subagent implementations
  - [ ] Tool implementations

- [ ] Update event constant imports:
  - [ ] Replace old imports with new constants
  - [ ] Fix import errors

- [ ] Search hardcoded event strings:
  - [ ] Find all string literals matching `soothe.*.*.*`
  - [ ] Replace with new event types

- [ ] Run `make lint` after each batch
- [ ] Run unit tests after Phase 2 completion

### 3.4 Phase 3: Test Migration (Day 3-4)

**Goal**: Update test code to use new event types.

- [ ] Update test assertions:
  - [ ] `tests/unit/test_event_catalog.py`
  - [ ] `tests/unit/test_event_emission.py`
  - [ ] Integration tests

- [ ] Update mock event data:
  - [ ] Fix hardcoded event dicts in mocks
  - [ ] Update test fixtures

- [ ] Run all unit tests (900+ tests)
- [ ] Fix test failures

### 3.5 Phase 4: Documentation & Verification (Day 4-5)

**Goal**: Update documentation and run full verification.

- [ ] Update documentation:
  - [ ] Update `event-catalog.md` with new naming
  - [ ] Update `CLAUDE.md` examples
  - [ ] Update user guide plugin section

- [ ] Run verification suite:
  - [ ] `./scripts/verify_finally.sh`
  - [ ] Ensure linting passes (zero errors)
  - [ ] Ensure all 900+ tests pass

- [ ] Manual validation:
  - [ ] Start daemon, verify heartbeat event
  - [ ] Run browser subagent, verify events
  - [ ] Run research subagent, verify events
  - [ ] Run TUI, verify event rendering
  - [ ] Run CLI, verify event streams

- [ ] CI integration:
  - [ ] Add validation script to CI workflow
  - [ ] Add to pre-commit hooks
  - [ ] Test CI passes

---

## 4. Migration Map Summary

**Total events**: ~80+ event types

**Key migrations**:
- Lifecycle: `created` → `started`, `saved` → `saving`
- Protocol: `recalled` → `recalling`, `stored` → `storing`
- Cognition: `created` → `creating`, `reflected` → `reflecting`
- Capability: `subagent.*` → `capability.*`, domain migration
- System: `autopilot.*` → `system.autopilot.*`
- Output: `response` → `responding`

**Complete map**: See RFC-403 Section 8.

---

## 5. Validation Rules

After migration, all events must satisfy:

1. Namespace format: `soothe.<domain>.<component>.<action_or_state>`
2. Domain in approved list (9 domains)
3. Action in approved verb list OR approved state noun list
4. Third-party events: `soothe.plugin.<vendor>.*`
5. No duplicate type strings

Run `scripts/validate_event_names.py` to check.

---

## 6. Success Criteria

Migration successful when:
- ✅ All 900+ unit tests pass
- ✅ Linting passes (zero errors)
- ✅ Validation script passes
- ✅ Manual daemon execution verified
- ✅ TUI renders new events correctly
- ✅ CLI event streams work
- ✅ Documentation updated
- ✅ CI validation passes

---

## 7. Rollback Plan

If critical failures:
1. Revert feature branch commits
2. Restore original event types
3. Run verification suite
4. Investigate root cause
5. Fix and retry migration

---

## 8. Post-Migration

After successful migration:
1. Merge feature branch to main
2. Update RFC-403 status to "Implemented"
3. Update IG-176 status to "Completed"
4. Remove backward compatibility code (none needed per RFC-403)
5. Monitor event system stability
6. Collect developer feedback on new naming

---

## 9. Estimated Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Pre-Migration | 0.5 day | RFC approval |
| Phase 1: Catalog | 1-2 days | Migration script |
| Phase 2: Emitters | 1-2 days | Phase 1 complete |
| Phase 3: Tests | 1 day | Phase 2 complete |
| Phase 4: Verification | 1 day | All phases complete |
| **Total** | **4-5 days** | |

---

## 10. Risk Mitigation

**Risks**:
- Migration script errors → Test on samples first
- Missed emission sites → Use grep search
- Test failures → Incremental migration with testing
- TUI rendering breaks → Manual TUI validation
- Plugin compatibility → Document migration guide

**Mitigations**:
- Incremental migration per phase
- Verification after each phase
- Manual validation scenarios
- Rollback plan ready
- Developer communication

---

## 11. References

- **RFC-403**: `docs/specs/RFC-403-unified-event-naming.md`
- **Design Draft**: `docs/drafts/2026-04-15-event-naming-semantics-unification-design.md`
- **Event Catalog**: `docs/specs/event-catalog.md`
- **RFC-401**: `docs/specs/RFC-401-event-processing.md`

---

**Implementation Lead**: Platonic Coding Workflow
**Next Action**: Create migration and validation scripts