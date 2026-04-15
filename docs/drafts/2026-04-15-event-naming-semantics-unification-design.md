# Event Naming Semantics Unification Design

**Date**: 2026-04-15
**Author**: Platonic Brainstorming Session
**Status**: Draft - Pending User Review

---

## Problem Statement

Soothe's event system currently suffers from semantic inconsistencies that create confusion for developers and make future extension difficult:

1. **Tense inconsistency**: Events mix past tense ("created", "completed"), present progressive ("started", "reflect"), and nouns ("report", "heartbeat") without clear rules.

2. **Domain categorization ambiguity**: Domains like "cognition" contain both plan and goal events, while "protocol" vs "cognition" boundaries are unclear. The "autopilot" domain was added outside RFC-0015's original 6-domain specification.

3. **Extension confusion**: Third-party plugin developers lack clear guidelines for registering custom events, risking namespace collisions and semantic drift.

4. **Future scalability risk**: As new protocols, subagents, and cross-cutting events are added, the lack of unified semantics will compound confusion.

**Goal**: Establish unified event naming semantics with clear grammar rules, semantic domains, and extension guidelines to support future growth.

---

## Design Overview

This design establishes a unified event naming system using **present progressive tense grammar** and **function-based semantic domains**:

- **Namespace**: `soothe.<domain>.<component>.<action_or_state>` (4-segment)
- **Grammar**: All actions use present progressive tense; state nouns allowed for reports
- **Domains**: 9 semantic domains based on functional scope, not implementation location
- **Extensions**: Clear plugin namespace rules for third-party developers

---

## Section 1: Unified Tense Grammar Rules

### Grammar Principle

All action verbs use **present progressive tense** to represent ongoing event emission, matching RFC-0015's "progress events" concept.

### Grammar Categories

**Lifecycle actions** (thread/process boundaries):
- `started`, `resumed`, `saving`, `ended`

**Operation actions** (protocol and cognitive operations):
- `running`, `checking`, `recalling`, `creating`, `reflecting`, `storing`

**Capability actions** (external invocations):
- `started`, `dispatching`, `running`, `completed`, `failed`

**State nouns** (status reports, NOT actions):
- `report`, `heartbeat`, `snapshot`, `status_changed`, `loaded`, `unloaded`, `health_checked`

### Tense Transformation Rules

| Old Tense | New Tense | Context |
|-----------|-----------|---------|
| `created` | `started` | Lifecycle begin events (thread, checkpoint) |
| `created` | `creating` | Cognitive planning events (plan, goal) |
| `recalled` | `recalling` | Protocol memory operations |
| `stored` | `storing` | Protocol memory operations |
| `dispatched` | `started` | Capability invocation begin |
| `completed` | `completed` | Already present progressive (keep) |
| `failed` | `failed` | Already present progressive (keep) |
| `report` | `report` | State noun (keep) |
| `heartbeat` | `heartbeat` | State noun (keep) |
| `snapshot` | `snapshot` | State noun (keep) |
| `status_changed` | `status_changed` | State noun (keep) |

### Examples

```python
# Lifecycle events
soothe.lifecycle.thread.created       → soothe.lifecycle.thread.started
soothe.lifecycle.thread.ended         → soothe.lifecycle.thread.ended (keep)
soothe.lifecycle.checkpoint.saved     → soothe.lifecycle.checkpoint.saving

# Protocol events
soothe.protocol.memory.recalled       → soothe.protocol.memory.recalling
soothe.protocol.memory.stored         → soothe.protocol.memory.storing
soothe.protocol.policy.checked        → soothe.protocol.policy.checking (or keep "checked" as state?)

# Cognitive events
soothe.cognition.plan.created         → soothe.cognition.plan.creating
soothe.cognition.goal.created         → soothe.cognition.goal.creating
soothe.cognition.goal.report          → soothe.cognition.goal.report (keep as noun)

# Capability events
soothe.capability.browser.dispatched  → soothe.capability.browser.started
soothe.capability.research.completed  → soothe.capability.research.completed (keep)
```

### Why This Works

Present progressive tense is natural for event emission (events represent ongoing progress), provides a simple grammar rule for third-party developers, and eliminates tense confusion across the system.

---

## Section 2: Domain Reorganization (Semantic Scope)

### Domain Taxonomy

**9 semantic domains** based on functional purpose, not implementation location:

| Domain | Functional Scope | Examples |
|--------|------------------|----------|
| `lifecycle` | Thread/process lifecycle boundaries | thread.started, checkpoint.saving, iteration.completed |
| `protocol` | Protocol operations (memory, policy, context, durability) | memory.recalling, policy.checking, durability.storing |
| `cognition` | Cognitive reasoning and decision-making | plan.creating, goal.creating, agent_loop.completed, reason.running |
| `capability` | External capability invocations (tool, subagent, mcp) | browser.started, claude.completed, tool.running, mcp.dispatching |
| `output` | User-facing content delivery | chitchat.started, final_report.reporting, autonomous.displaying |
| `system` | System-level operations (daemon, autopilot) | daemon.heartbeat, autopilot.status_changed |
| `error` | Error and exception events | general.failed, protocol.violated |
| `plugin` | Plugin lifecycle (core-managed) | plugin.loaded, plugin.failed, plugin.health_checked |
| `plugin.<vendor>` | Third-party plugin extension namespace | plugin.acme.collector.started, plugin.dataflow.pipeline.running |

### Domain Decision Rules

**Decision tree for placing events in domains**:

1. **Is it a thread/process boundary event?** → `lifecycle`
2. **Is it a protocol implementation operation (memory/policy/context/durability)?** → `protocol`
3. **Is it a cognitive reasoning/decision event (planning/goal-setting)?** → `cognition`
4. **Is it an external capability invocation (tool/subagent/MCP dispatch)?** → `capability`
5. **Is it user-facing output (not internal progress)?** → `output`
6. **Is it system-level infrastructure (daemon/autopilot)?** → `system`
7. **Is it an error/exception?** → `error`
8. **Is it plugin lifecycle managed by core?** → `plugin`
9. **Is it a third-party plugin event?** → `plugin.<vendor>`

### Key Domain Migrations

**From old domains to new domains**:

```
soothe.subagent.browser.*      → soothe.capability.browser.*
soothe.subagent.claude.*       → soothe.capability.claude.*
soothe.subagent.research.*     → soothe.capability.research.*
soothe.autopilot.*             → soothe.system.autopilot.*
soothe.cognition.agent_loop.*  → soothe.cognition.agent_loop.* (stays, agent_loop is cognitive)
soothe.tool.*                  → soothe.capability.tool.*
```

### Why This Works

Functional domains eliminate "cognition vs protocol" confusion, make it obvious where new events belong, and provide clear boundaries for future protocols/backends. Domain-based filtering supports TUI verbosity controls and event routing.

---

## Section 3: Component/Action Boundaries

### Namespace Hierarchy

**Format**: `soothe.<domain>.<component>.<action_or_state>`

- **Component**: Specific module/subsystem (thread, memory, plan, browser, claude, autopilot)
- **Action**: Verb in present progressive OR approved state noun

### Component Naming Rules

1. Use singular form: `thread` (not `threads`), `plan` (not `plans`)
2. Use snake_case: `agent_loop`, `final_report`
3. Hierarchical components allowed for nested operations:
   ```
   soothe.cognition.agent_loop.step.started
   soothe.cognition.agent_loop.step.completed
   soothe.cognition.plan.step.started
   soothe.cognition.plan.step.completed
   ```

### Action Naming Rules

1. Actions must be from approved verb list (present progressive) OR approved state noun list
2. Use consistent action semantics across components:
   - Begin events: `started`, `creating`, `dispatching`
   - Progress events: `running`, `checking`, `recalling`, `reflecting`
   - End events: `completed`, `failed`, `ended`
   - State reports: `report`, `heartbeat`, `snapshot`, `status_changed`

### Examples

```python
# Clear component/action separation
soothe.lifecycle.thread.started               # component=thread, action=started
soothe.protocol.memory.recalling              # component=memory, action=recalling
soothe.cognition.plan.creating                # component=plan, action=creating
soothe.capability.browser.started             # component=browser, action=started
soothe.capability.research.completed          # component=research, action=completed
soothe.system.autopilot.status_changed        # component=autopilot, action=status_changed
soothe.cognition.agent_loop.step.started      # hierarchical component=agent_loop.step
```

### Why This Works

4-segment namespace balances clarity with brevity, supports hierarchical components for nested operations, and maintains RFC-0015 compatibility. Clear component/action separation makes events self-documenting.

---

## Section 4: Plugin Extension Rules

### Third-Party Plugin Namespace

**Format**: `soothe.plugin.<vendor>.<component>.<action_or_state>`

### Vendor Naming Rules

1. Use vendor/organization prefix: `acme`, `dataflow`, `enterprise`
2. Use snake_case for vendor and component names
3. Avoid reserved core domains: lifecycle, protocol, cognition, capability, output, system, error, plugin
4. Prefix vendor-specific components to avoid collisions with core components

### Examples

```python
# Third-party plugin events
soothe.plugin.acme_analytics.collector.started
soothe.plugin.dataflow.pipeline.running
soothe.plugin.enterprise_support.ticket.dispatching
soothe.plugin.monitoring.alert.checking
```

### Core Plugin Lifecycle Events

Core-managed plugin lifecycle events remain in top-level `plugin` domain:

```python
soothe.plugin.loaded          # Plugin successfully loaded
soothe.plugin.failed          # Plugin failed to load
soothe.plugin.health_checked  # Plugin health check completed
soothe.plugin.unloaded        # Plugin unloaded
```

### Extension Guidelines for Plugin Developers

**Documentation to provide in RFC update**:

1. Use `soothe.plugin.<your_vendor>.<your_component>.<action>` namespace
2. Follow present progressive tense grammar for actions
3. Use approved state nouns for status reports
4. Register events using `register_event()` API
5. Choose vendor prefix that uniquely identifies your organization
6. Example:

```python
from soothe.core.event_catalog import register_event
from soothe_sdk.events import SootheEvent

class MyPluginEvent(SootheEvent):
    type: str = "soothe.plugin.mycompany.processor.started"
    data: str

register_event(
    MyPluginEvent,
    summary_template="Processing: {data}",
)
```

### Why This Works

Clear namespace isolation prevents third-party event collisions with core events. Plugin events are immediately recognizable. Developers have straightforward guidelines to follow.

---

## Section 5: Migration Strategy (No Backward Compatibility)

### Migration Approach

Direct migration with no backward compatibility aliases. This forces immediate adoption of unified semantics and eliminates maintenance burden.

### Phase 1: Event Catalog Migration (1-2 days)

**Tasks**:
1. Update `event_catalog.py` type string constants
2. Update event class `type` field default values
3. Update `_reg()` calls with new type strings
4. Update `register_event()` calls in module event files:
   - `cognition/agent_loop/events.py`
   - `subagents/browser/events.py`
   - `subagents/claude/events.py`
   - `subagents/research/events.py`
   - `plugin/events.py`
5. Delete old type string constants completely

**Files to modify**:
- `packages/soothe/src/soothe/core/event_catalog.py` (core events)
- `packages/soothe/src/soothe/cognition/agent_loop/events.py`
- `packages/soothe/src/soothe/subagents/*/events.py`
- `packages/soothe/src/soothe/plugin/events.py`

### Phase 2: Emitter Code Migration (1-2 days)

**Tasks**:
1. Update all `yield custom_event()` calls with new event types
2. Update all event constant references in emitter code:
   - Replace imports of old constants with new constants
   - Update hardcoded event type strings
3. Search for all event type string literals and replace

**Files to modify**:
- All files that emit events using `custom_event()`
- All files that import event constants from `event_catalog`
- Core runner, agent factory, protocol implementations, subagent implementations

### Phase 3: Test Migration (1 day)

**Tasks**:
1. Update test assertions that check event types
2. Update mock event data in tests
3. Update test fixtures and test event emission
4. Run unit tests and fix any failures

**Files to modify**:
- `tests/unit/test_event_catalog.py`
- `tests/unit/test_event_emission.py`
- All test files that check event types

### Phase 4: Documentation and Verification (1 day)

**Tasks**:
1. Update RFC-0015 event naming convention documentation
2. Update CLAUDE.md event naming examples
3. Create plugin developer extension guide
4. Run full verification suite: `./scripts/verify_finally.sh`
5. Ensure all 900+ tests pass
6. Run manual daemon execution tests

**Files to modify**:
- `docs/specs/RFC-0015-event-system.md` (if exists, or create new RFC)
- `CLAUDE.md` (update event naming examples)
- `docs/user_guide.md` (add plugin event extension section)

### Migration Tools

**Tool 1: Automated migration script**

Create `scripts/migrate_event_names.py`:
- Find-and-replace event type strings across all Python files
- Generate migration report showing all changes
- Support dry-run mode to preview changes

```python
# Example migration script structure
EVENT_MIGRATION_MAP = {
    "soothe.lifecycle.thread.created": "soothe.lifecycle.thread.started",
    "soothe.protocol.memory.recalled": "soothe.protocol.memory.recalling",
    "soothe.cognition.plan.created": "soothe.cognition.plan.creating",
    # ... (full migration map)
}

def migrate_file(filepath: Path) -> list[str]:
    # Find and replace all old event types
    # Return list of changes made
```

**Tool 2: Validation script**

Create `scripts/validate_event_names.py`:
- Check all events follow new grammar rules
- Validate domains, components, actions
- Run as CI check
- Add as pre-commit hook

```python
# Example validation rules
APPROVED_DOMAINS = [
    "lifecycle", "protocol", "cognition", "capability",
    "output", "system", "error", "plugin"
]

APPROVED_VERBS = [
    "started", "resumed", "saving", "ended", "running",
    "checking", "recalling", "creating", "reflecting", "storing",
    "dispatching", "completed", "failed"
]

APPROVED_STATE_NOUNS = [
    "report", "heartbeat", "snapshot", "status_changed",
    "loaded", "unloaded", "health_checked"
]

def validate_event_type(type_string: str) -> bool:
    # Check follows soothe.<domain>.<component>.<action> format
    # Check domain in approved list
    # Check action in approved verbs or state nouns
    # Check plugin events start with soothe.plugin.
```

### Risk Mitigation

1. Run migration script on clean feature branch
2. Review migration script output manually before committing
3. Run verification after each phase
4. Test against real daemon execution scenarios (start daemon, run queries, check event streams)
5. Run TUI and CLI tests to verify event rendering still works

### Why This Works

Direct migration eliminates maintenance burden, forces immediate unified adoption, and reduces complexity. Automated tooling reduces manual effort and validation ensures correctness.

---

## Section 6: Validation and Testing

### Grammar Validation Rules

Enforce in `validate_event_names.py`:

1. **Namespace format**: Must match `soothe.<domain>.<component>.<action_or_state>`
2. **Domain validation**: Domain must be from approved domain list
3. **Action validation**: Action must be from approved verb list OR approved state noun list
4. **Plugin namespace**: Third-party events must start with `soothe.plugin.<vendor>`
5. **No duplicates**: No duplicate type strings across codebase

### Approved Lists

**Approved domains**:
```
lifecycle, protocol, cognition, capability, output, system, error, plugin
```

**Approved verbs (present progressive)**:
```
started, resumed, saving, ended, running, checking, recalling,
creating, reflecting, storing, dispatching, completed, failed,
displaying, emitting
```

**Approved state nouns**:
```
report, heartbeat, snapshot, status_changed, loaded, unloaded,
health_checked
```

### Testing Strategy

**Unit tests**:
- Test grammar validation rules in `test_validate_event_names.py`
- Test event type string parsing and domain classification
- Test action tense validation

**Integration tests**:
- Test event emission with new types in `test_event_emission.py`
- Test event registry still works with new types
- Test TUI rendering of new event types
- Test CLI event stream handling

**Manual tests**:
- Start daemon and verify heartbeat event: `soothe.system.daemon.heartbeat`
- Run browser subagent and verify events: `soothe.capability.browser.started`
- Run research subagent and verify events: `soothe.capability.research.completed`
- Run agent loop and verify events: `soothe.cognition.agent_loop.completed`
- Run TUI and verify event rendering displays correctly

### CI Integration

Add validation script to CI pipeline:
```yaml
# .github/workflows/ci.yml
- name: Validate event naming
  run: python scripts/validate_event_names.py
```

Add as pre-commit hook:
```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: validate-event-names
      name: Validate event names
      entry: python scripts/validate_event_names.py
      language: system
      types: [python]
```

### Why This Works

Validation ensures all future events follow unified semantics, preventing drift. Testing ensures migration correctness. CI integration enforces rules automatically.

---

## Section 7: Complete Event Migration Map

### Lifecycle Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.lifecycle.thread.created` | `soothe.lifecycle.thread.started` | Lifecycle begin |
| `soothe.lifecycle.thread.started` | `soothe.lifecycle.thread.started` | Keep (already correct) |
| `soothe.lifecycle.thread.resumed` | `soothe.lifecycle.thread.resumed` | Keep (already correct) |
| `soothe.lifecycle.thread.saved` | `soothe.lifecycle.thread.saving` | Saving action |
| `soothe.lifecycle.thread.ended` | `soothe.lifecycle.thread.ended` | Keep (already correct) |
| `soothe.lifecycle.iteration.started` | `soothe.lifecycle.iteration.started` | Keep |
| `soothe.lifecycle.iteration.completed` | `soothe.lifecycle.iteration.completed` | Keep |
| `soothe.lifecycle.checkpoint.saved` | `soothe.lifecycle.checkpoint.saving` | Saving action |
| `soothe.lifecycle.recovery.resumed` | `soothe.lifecycle.recovery.resumed` | Keep |
| `soothe.lifecycle.daemon.heartbeat` | `soothe.system.daemon.heartbeat` | Domain migration: daemon → system |

### Protocol Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.protocol.memory.recalled` | `soothe.protocol.memory.recalling` | Present progressive |
| `soothe.protocol.memory.stored` | `soothe.protocol.memory.storing` | Present progressive |
| `soothe.protocol.policy.checked` | `soothe.protocol.policy.checking` | Present progressive |
| `soothe.protocol.policy.denied` | `soothe.protocol.policy.denied` | Keep (already correct) |

### Cognitive Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.cognition.plan.created` | `soothe.cognition.plan.creating` | Present progressive |
| `soothe.cognition.plan.step_started` | `soothe.cognition.plan.step.started` | Hierarchical component |
| `soothe.cognition.plan.step_completed` | `soothe.cognition.plan.step.completed` | Keep |
| `soothe.cognition.plan.step_failed` | `soothe.cognition.plan.step.failed` | Keep |
| `soothe.cognition.plan.batch_started` | `soothe.cognition.plan.batch.started` | Hierarchical component |
| `soothe.cognition.plan.reflected` | `soothe.cognition.plan.reflecting` | Present progressive |
| `soothe.cognition.plan.dag_snapshot` | `soothe.cognition.plan.dag_snapshot` | Keep (state noun) |
| `soothe.cognition.goal.created` | `soothe.cognition.goal.creating` | Present progressive |
| `soothe.cognition.goal.completed` | `soothe.cognition.goal.completed` | Keep |
| `soothe.cognition.goal.failed` | `soothe.cognition.goal.failed` | Keep |
| `soothe.cognition.goal.batch_started` | `soothe.cognition.goal.batch.started` | Hierarchical component |
| `soothe.cognition.goal.report` | `soothe.cognition.goal.report` | Keep (state noun) |
| `soothe.cognition.goal.directives_applied` | `soothe.cognition.goal.directives_applying` | Present progressive |
| `soothe.cognition.goal.deferred` | `soothe.cognition.goal.deferring` | Present progressive |
| `soothe.cognition.agent_loop.started` | `soothe.cognition.agent_loop.started` | Keep |
| `soothe.cognition.agent_loop.completed` | `soothe.cognition.agent_loop.completed` | Keep |
| `soothe.cognition.agent_loop.step.started` | `soothe.cognition.agent_loop.step.started` | Keep |
| `soothe.cognition.agent_loop.step.completed` | `soothe.cognition.agent_loop.step.completed` | Keep |
| `soothe.cognition.agent_loop.reason` | `soothe.cognition.agent_loop.reasoning` | Present progressive |

### Capability Events (Subagents)

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.subagent.browser.dispatched` | `soothe.capability.browser.started` | Domain migration + action change |
| `soothe.subagent.browser.completed` | `soothe.capability.browser.completed` | Domain migration |
| `soothe.subagent.browser.step` | `soothe.capability.browser.step.running` | Domain migration + action clarification |
| `soothe.subagent.browser.cdp` | `soothe.capability.browser.cdp.connecting` | Domain migration + action clarification |
| `soothe.subagent.claude.text` | `soothe.capability.claude.text.running` | Domain migration |
| `soothe.subagent.claude.tool_use` | `soothe.capability.claude.tool.running` | Domain migration |
| `soothe.subagent.claude.result` | `soothe.capability.claude.completed` | Domain migration |
| `soothe.subagent.research.dispatched` | `soothe.capability.research.started` | Domain migration + action change |
| `soothe.subagent.research.completed` | `soothe.capability.research.completed` | Domain migration |
| `soothe.subagent.research.analyze` | `soothe.capability.research.analyzing` | Domain migration + present progressive |
| `soothe.subagent.research.sub_questions` | `soothe.capability.research.questions.generating` | Domain migration + action clarification |
| `soothe.subagent.research.queries_generated` | `soothe.capability.research.queries.generating` | Domain migration + present progressive |
| `soothe.subagent.research.gather` | `soothe.capability.research.gathering` | Domain migration + present progressive |
| `soothe.subagent.research.gather_done` | `soothe.capability.research.gather.completed` | Domain migration + hierarchical component |
| `soothe.subagent.research.summarize` | `soothe.capability.research.summarizing` | Domain migration + present progressive |
| `soothe.subagent.research.reflect` | `soothe.capability.research.reflecting` | Domain migration + present progressive |
| `soothe.subagent.research.reflection_done` | `soothe.capability.research.reflection.completed` | Domain migration + hierarchical component |
| `soothe.subagent.research.synthesize` | `soothe.capability.research.synthesizing` | Domain migration + present progressive |
| `soothe.subagent.research.internal_llm` | `soothe.capability.research.internal_llm.running` | Domain migration |
| `soothe.subagent.research.judgement` | `soothe.capability.research.judgement.reporting` | Domain migration + present progressive |

### System Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.autopilot.status_changed` | `soothe.system.autopilot.status_changed` | Domain migration |
| `soothe.autopilot.goal_created` | `soothe.system.autopilot.goal.creating` | Domain migration + hierarchical component |
| `soothe.autopilot.goal_progress` | `soothe.system.autopilot.goal.reporting` | Domain migration + present progressive |
| `soothe.autopilot.goal_completed` | `soothe.system.autopilot.goal.completed` | Domain migration + hierarchical component |
| `soothe.autopilot.dreaming_entered` | `soothe.system.autopilot.dreaming.started` | Domain migration + present progressive |
| `soothe.autopilot.dreaming_exited` | `soothe.system.autopilot.dreaming.completed` | Domain migration + present progressive |
| `soothe.autopilot.goal_validated` | `soothe.system.autopilot.goal.validating` | Domain migration + present progressive |
| `soothe.autopilot.goal_suspended` | `soothe.system.autopilot.goal.suspending` | Domain migration + present progressive |
| `soothe.autopilot.send_back` | `soothe.system.autopilot.feedback.sending` | Domain migration + present progressive |
| `soothe.autopilot.relationship_detected` | `soothe.system.autopilot.relationship.detecting` | Domain migration + present progressive |
| `soothe.autopilot.checkpoint.saved` | `soothe.system.autopilot.checkpoint.saving` | Domain migration + present progressive |
| `soothe.autopilot.goal_blocked` | `soothe.system.autopilot.goal.blocking` | Domain migration + present progressive |

### Output Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.output.chitchat.started` | `soothe.output.chitchat.started` | Keep |
| `soothe.output.chitchat.response` | `soothe.output.chitchat.responding` | Present progressive |
| `soothe.output.autonomous.final_report` | `soothe.output.autonomous.final_report.reporting` | Hierarchical component + present progressive |

### Plugin Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.plugin.loaded` | `soothe.plugin.loaded` | Keep (state noun) |
| `soothe.plugin.failed` | `soothe.plugin.failed` | Keep |
| `soothe.plugin.unloaded` | `soothe.plugin.unloaded` | Keep (state noun) |
| `soothe.plugin.health_checked` | `soothe.plugin.health_checked` | Keep (state noun) |

### Error Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.error.general` | `soothe.error.general.failed` | Add action clarification |

---

## Section 8: Documentation Updates Required

### RFC Updates

1. **RFC-0015** (Event System): Update event naming convention section with:
   - Present progressive tense grammar rules
   - New domain taxonomy with functional scope definitions
   - Component/action naming rules
   - Plugin extension namespace guidelines
   - Approved verb and state noun lists

2. **RFC-000** (System Conceptual Design): Update event system overview to reference new naming semantics

### CLAUDE.md Updates

Update event naming examples in:
- "Quick Start for Common Tasks" section
- "Plugin System (RFC-600)" section
- "Architecture at a Glance" section

Replace old event naming examples with new unified naming.

### User Guide Updates

Add new section in `docs/user_guide.md`:
- "Plugin Event Extension Guide" with examples for third-party developers
- Clear vendor namespace guidelines
- Example code for registering custom events

---

## Section 9: Implementation Checklist

### Pre-Migration
- [ ] Create `scripts/migrate_event_names.py` migration script
- [ ] Create `scripts/validate_event_names.py` validation script
- [ ] Test migration script on sample files
- [ ] Create clean feature branch for migration

### Phase 1: Event Catalog
- [ ] Migrate `event_catalog.py` core events
- [ ] Migrate `cognition/agent_loop/events.py`
- [ ] Migrate `subagents/browser/events.py`
- [ ] Migrate `subagents/claude/events.py`
- [ ] Migrate `subagents/research/events.py`
- [ ] Migrate `plugin/events.py`
- [ ] Run `make lint` and fix errors
- [ ] Run unit tests and fix failures

### Phase 2: Emitter Code
- [ ] Update all `custom_event()` calls
- [ ] Update all event constant imports
- [ ] Update all hardcoded event type strings
- [ ] Run `make lint` and fix errors
- [ ] Run unit tests and fix failures

### Phase 3: Tests
- [ ] Update test assertions
- [ ] Update mock event data
- [ ] Update test fixtures
- [ ] Run all unit tests
- [ ] Ensure 900+ tests pass

### Phase 4: Documentation & Verification
- [ ] Update RFC-0015
- [ ] Update CLAUDE.md
- [ ] Update user guide
- [ ] Run `./scripts/verify_finally.sh`
- [ ] Run manual daemon tests
- [ ] Run TUI tests
- [ ] Run CLI tests
- [ ] Add validation script to CI
- [ ] Add validation script to pre-commit hooks

---

## Open Questions (To Resolve)

1. **Policy events**: Should `soothe.protocol.policy.checked` become `soothe.protocol.policy.checking` (action) or keep `checked` as state noun? Policy check is an action, so probably `checking`.

2. **Verb consistency**: Should all "completed" events stay `completed` or become `completing`? Currently `completed` is treated as present progressive (action result). Keep as is.

3. **Tool events**: How to handle tool events if we migrate `soothe.tool.*` → `soothe.capability.tool.*`? Need to find all tool event definitions and migrate.

4. **Internal vs external**: Some subagent events like `browser.step` are "internal" progress. Should they be `capability.browser.step.running` (internal action) or stay simpler? Proposed: `soothe.capability.browser.step.running` to show it's a running action.

5. **Domain decision**: Where do events from new protocols/backends belong? Clear rule: protocol implementation operations → `protocol` domain, regardless of backend location.

---

## Success Criteria

Migration is successful when:

1. ✅ All 900+ unit tests pass
2. ✅ Linting passes with zero errors
3. ✅ Validation script finds no violations
4. ✅ Manual daemon execution produces correct event streams
5. ✅ TUI renders all new event types correctly
6. ✅ CLI event stream handling works
7. ✅ Plugin developers can register events following new guidelines
8. ✅ Documentation updated with clear rules

---

## Next Steps

After user review approval:

1. **Platonic Coding Phase 1**: Generate RFC from this design draft
2. **RFC-0015 update**: Formalize unified event naming semantics
3. **RFC review**: Get user approval on RFC
4. **Platonic Coding Phase 2**: Create implementation guide from RFC
5. **Implementation**: Execute migration phases 1-4
6. **Verification**: Run full verification suite

---

**Draft Status**: Ready for user review. Please review this design draft and provide feedback before advancing to Platonic Coding Phase 1 RFC formalization.