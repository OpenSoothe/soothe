# RFC-403: Unified Event Naming Semantics

**RFC**: 403
**Title**: Unified Event Naming Semantics
**Status**: Draft
**Kind**: Implementation Interface Design
**Created**: 2026-04-15
**Updated**: 2026-05-01
**Authors**: Platonic Brainstorming Session
**Depends on**: -

---

## 1. Abstract

This RFC defines unified semantics for Soothe's event naming system, establishing present progressive tense grammar, function-based semantic domains, and clear extension guidelines for third-party developers. This formalization eliminates naming inconsistencies, clarifies domain boundaries, and provides a scalable foundation for future event system growth.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* **Grammar rules**: Present progressive tense for actions, approved state nouns for reports
* **Semantic domains**: 9 function-based domains with clear scope definitions
* **Namespace hierarchy**: `soothe.<domain>.<component>.<action_or_state>` format
* **Plugin extension rules**: Third-party namespace conventions with vendor prefixes
* **Approved vocabularies**: Lists of approved verbs and state nouns
* **Migration strategy**: Systematic approach for renaming existing events
* **Validation rules**: Grammar and semantics validation criteria

### 2.2 Non-Goals

This RFC does **not** define:

* Event processing architecture (see RFC-400)
* Event registry implementation (see RFC-400)
* VerbosityTier classification (see RFC-501)
* Transport or filtering mechanisms (see RFC-400, RFC-400)
* Specific event type definitions (see event-catalog.md)

---

## 3. Background & Motivation

### 3.1 Current Problems

| Problem | Impact | Example |
|---------|--------|---------|
| **Tense inconsistency** | Developer confusion, unclear grammar | `created` (past), `started` (present), `report` (noun) |
| **Domain ambiguity** | Unclear where new events belong | `cognition` vs `protocol` boundaries unclear |
| **Extension confusion** | Plugin developers lack guidelines | Third-party events risk collisions |
| **Future scalability risk** | Naming drift compounds confusion | New protocols/subagents add inconsistencies |

### 3.2 Design Goals

1. **Grammar consistency**: Single tense rule for all action events
2. **Semantic clarity**: Function-based domains, not implementation location
3. **Extension guidelines**: Clear rules for third-party plugin events
4. **Future scalability**: Domain decision tree prevents ambiguity
5. **Tooling support**: Grammar validation in CI/pre-commit hooks

---

## 4. Naming Semantics

### 4.1 Grammar Rules

**Core principle**: All action verbs use **present progressive tense** to represent ongoing event emission, matching RFC-0015's "progress events" concept.

#### 4.1.1 Grammar Categories

| Category | Tense/Form | Examples |
|----------|-----------|----------|
| **Lifecycle actions** | Present progressive | `started`, `resumed`, `saving`, `ended` |
| **Operation actions** | Present progressive | `running`, `checking`, `recalling`, `creating`, `reflecting`, `storing` |
| **Capability actions** | Present progressive | `started`, `dispatching`, `running`, `completed`, `failed` |
| **State nouns** | Noun (not action) | `report`, `heartbeat`, `snapshot`, `status_changed`, `loaded`, `unloaded`, `health_checked` |

#### 4.1.2 Tense Transformation Rules

| Old Tense | New Tense | Context | Reason |
|-----------|-----------|---------|--------|
| `created` | `started` | Lifecycle begin events | Thread/process boundaries use `started` |
| `created` | `creating` | Cognitive planning events | Planning operations use present progressive |
| `recalled` | `recalling` | Protocol memory operations | Protocol operations use present progressive |
| `stored` | `storing` | Protocol memory operations | Storage operations use present progressive |
| `dispatched` | `started` | Capability invocation begin | Invocation begin uses `started` |
| `completed` | `completed` | Already present progressive | Keep unchanged |
| `failed` | `failed` | Already present progressive | Keep unchanged |
| `report` | `report` | State noun | Keep as state noun |
| `heartbeat` | `heartbeat` | State noun | Keep as state noun |
| `snapshot` | `snapshot` | State noun | Keep as state noun |
| `status_changed` | `status_changed` | State noun | Keep as state noun |

### 4.2 Semantic Domain Taxonomy

#### 4.2.1 Domain Definitions

**9 function-based domains** organized by functional purpose, not implementation location:

| Domain | Functional Scope | Examples |
|--------|------------------|----------|
| `lifecycle` | Thread/process lifecycle boundaries | `thread.started`, `checkpoint.saving`, `iteration.completed` |
| `protocol` | Protocol operations (memory, policy, context, durability) | `memory.recalling`, `policy.checking`, `durability.storing` |
| `cognition` | Cognitive reasoning and decision-making | `plan.creating`, `goal.creating`, `strange_loop.completed`, `reason.running` |
| `capability` | External capability naming (draft taxonomy; not used for built-in subagent wire) | Hypothetical `soothe.capability.*` names—**obsolete for built-ins** (IG-339 uses `soothe.subagent.*`) |
| `output` | User-facing content delivery | `final_report.reporting`, `autonomous.displaying` (duplicate `soothe.output.*` assistant bodies removed; use `messages` + `phase` per RFC-614) |
| `system` | System-level operations (daemon, autopilot) | `daemon.heartbeat`, `autopilot.status_changed` |
| `error` | Error and exception events | `general.failed`, `protocol.violated` |
| `plugin` | Plugin lifecycle (core-managed) | `plugin.loaded`, `plugin.failed`, `plugin.health_checked` |
| `plugin.<vendor>` | Third-party plugin extension namespace | `plugin.acme.collector.started`, `plugin.dataflow.pipeline.running` |

#### 4.2.2 Domain Decision Rules

**Decision tree for placing events in domains**:

1. Is it a thread/process boundary event? → `lifecycle`
2. Is it a protocol implementation operation? → `protocol`
3. Is it a cognitive reasoning/decision event? → `cognition`
4. Is it delegated subagent sparse UX on the wire? → `subagent` (built-in: IG-339 allowlist); optional RFC-403 **`capability`** domain remains for other “external capability” naming drafts—not used for built-in subagent progress (see §8.4)
5. Is it user-facing output? → `output`
6. Is it system-level infrastructure? → `system`
7. Is it an error/exception? → `error`
8. Is it plugin lifecycle managed by core? → `plugin`
9. Is it a third-party plugin event? → `plugin.<vendor>`

**Examples**:

```python
# Correct domain placement
soothe.lifecycle.thread.started           # Thread boundary → lifecycle
soothe.protocol.memory.recalling          # Memory protocol → protocol
soothe.cognition.plan.creating            # Planning decision → cognition
soothe.subagent.browser.started          # Delegated subagent wire → subagent (IG-339)
soothe.output.telemetry.line            # Ancillary capture → output (example only)
soothe.system.daemon.heartbeat            # Daemon system → system
soothe.plugin.acme.collector.started      # Third-party → plugin.<vendor>
```

**IG-317 note:** The `soothe.output.*` line above illustrates **domain placement** (`output`) for optional telemetry-style names. Core-loop assistant answer bodies use the LangGraph **`messages`** stream with a loop **`phase`** field (see RFC-614 / `soothe_sdk.ux.loop_stream`).

### 4.3 Namespace Hierarchy

#### 4.3.1 Format

```
soothe.<domain>.<component>.<action_or_state>
```

#### 4.3.2 Component Naming Rules

1. Use **singular form**: `thread` (not `threads`), `plan` (not `plans`)
2. Use **snake_case**: `strange_loop`, `final_report`
3. **Hierarchical components** allowed for nested operations:
   ```
   soothe.cognition.strange_loop.step.started
   soothe.cognition.plan.step.completed
   ```

#### 4.3.3 Action Naming Rules

1. Actions must be from **approved verb list** (present progressive) OR **approved state noun list**
2. Use consistent action semantics across components:
   - Begin events: `started`, `creating`, `dispatching`
   - Progress events: `running`, `checking`, `recalling`, `reflecting`
   - End events: `completed`, `failed`, `ended`
   - State reports: `report`, `heartbeat`, `snapshot`, `status_changed`

### 4.4 Approved Vocabularies

#### 4.4.1 Approved Domains

```
lifecycle, protocol, cognition, capability, output, system, error, plugin
```

#### 4.4.2 Approved Verbs (Present Progressive)

```
started, resumed, saving, ended, running, checking, recalling,
creating, reflecting, storing, dispatching, completed, failed,
displaying, emitting, analyzing, synthesizing, reasoning, deferring,
applying, validating, suspending, blocking, detecting, sending
```

#### 4.4.3 Approved State Nouns

```
report, heartbeat, snapshot, status_changed, loaded, unloaded,
health_checked
```

---

## 5. Plugin Extension Rules

### 5.1 Third-Party Plugin Namespace

**Format**: `soothe.plugin.<vendor>.<component>.<action_or_state>`

### 5.2 Vendor Naming Rules

1. Use **vendor/organization prefix**: `acme`, `dataflow`, `enterprise`, `monitoring`
2. Use **snake_case** for vendor and component names
3. **Avoid reserved core domains**: lifecycle, protocol, cognition, capability, output, system, error, plugin
4. **Prefix vendor-specific components** to avoid collisions with core components

### 5.3 Examples

```python
# Third-party plugin events
soothe.plugin.acme_analytics.collector.started
soothe.plugin.dataflow.pipeline.running
soothe.plugin.enterprise_support.ticket.dispatching
soothe.plugin.monitoring.alert.checking
```

### 5.4 Core Plugin Lifecycle Events

Core-managed plugin lifecycle events remain in top-level `plugin` domain:

```python
soothe.plugin.loaded          # Plugin successfully loaded
soothe.plugin.failed          # Plugin failed to load
soothe.plugin.health_checked  # Plugin health check completed
soothe.plugin.unloaded        # Plugin unloaded
```

### 5.5 Extension Guidelines for Plugin Developers

**Documentation requirements**:

1. Use `soothe.plugin.<your_vendor>.<your_component>.<action>` namespace
2. Follow present progressive tense grammar for actions
3. Use approved state nouns for status reports
4. Register events using `register_event()` API
5. Choose vendor prefix that uniquely identifies your organization

**Example**:

```python
from soothe.core.events import register_event
from soothe_sdk.events import SootheEvent

class MyPluginEvent(SootheEvent):
    type: str = "soothe.plugin.mycompany.processor.started"
    data: str

register_event(
    MyPluginEvent,
    summary_template="Processing: {data}",
)
```

---

## 6. Validation Rules

### 6.1 Grammar Validation

Enforced via `scripts/validate_event_names.py`:

1. **Namespace format**: Must match `soothe.<domain>.<component>.<action_or_state>`
2. **Domain validation**: Domain must be from approved domain list
3. **Action validation**: Action must be from approved verb list OR approved state noun list
4. **Plugin namespace**: Third-party events must start with `soothe.plugin.<vendor>`
5. **No duplicates**: No duplicate type strings across codebase

### 6.2 CI Integration

Add validation script to CI pipeline:

```yaml
# .github/workflows/ci.yml
- name: Validate event naming
  run: python scripts/validate_event_names.py
```

### 6.3 Pre-commit Hook

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

---

## 7. Migration Strategy

### 7.1 Migration Approach

**Direct migration with no backward compatibility**. Forces immediate adoption of unified semantics and eliminates maintenance burden.

### 7.2 Migration Phases

#### Phase 1: Event Catalog Migration (1-2 days)

**Tasks**:
1. Update `core/events/catalog.py` type string constants
2. Update event class `type` field default values
3. Update `_reg()` calls with new type strings
4. Update `register_event()` calls in module event files:
   - `packages/soothe/src/soothe/core/events/catalog.py` (core registry)
   - `packages/soothe/src/soothe/core/strange_loop/utils/events.py` (StrangeLoop typed events)
Optional community plugin event modules (see `community/src/soothe_plugins/`)
   - `packages/soothe/src/soothe/subagents/research/events.py`
   - `packages/soothe/src/soothe/plugin/events.py`
5. Delete old type string constants completely

**Files**:
- `packages/soothe/src/soothe/core/events/catalog.py`
- `packages/soothe/src/soothe/core/events/constants.py`
- `packages/soothe/src/soothe/core/strange_loop/utils/events.py`
- `packages/soothe/src/soothe/subagents/*/events.py`
- `packages/soothe/src/soothe/plugin/events.py`

#### Phase 2: Emitter Code Migration (1-2 days)

**Tasks**:
1. Update all `yield custom_event()` calls with new event types
2. Update all event constant references in emitter code
3. Search for all event type string literals and replace

**Files**:
- All files that emit events using `custom_event()`
- All files that import event constants from `soothe.core.events` / `soothe.core.events.catalog`

#### Phase 3: Test Migration (1 day)

**Tasks**:
1. Update test assertions that check event types
2. Update mock event data in tests
3. Update test fixtures
4. Run unit tests and fix failures

#### Phase 4: Documentation & Verification (1 day)

**Tasks**:
1. Update RFC-400 references to RFC-402
2. Update CLAUDE.md event naming examples
3. Update event-catalog.md with new naming
4. Run full verification suite: `./scripts/verify_finally.sh`
5. Ensure all 900+ tests pass

### 7.3 Migration Tools

#### Tool 1: Automated Migration Script

Create `scripts/migrate_event_names.py`:
- Find-and-replace event type strings across all Python files
- Generate migration report showing all changes
- Support dry-run mode to preview changes

#### Tool 2: Validation Script

Create `scripts/validate_event_names.py`:
- Check all events follow new grammar rules
- Validate domains, components, actions
- Run as CI check and pre-commit hook

---

## 8. Complete Migration Map

### 8.1 Lifecycle Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.lifecycle.thread.created` | `soothe.lifecycle.thread.started` | Lifecycle begin |
| `soothe.lifecycle.thread.saved` | `soothe.lifecycle.thread.saving` | Saving action |
| `soothe.lifecycle.checkpoint.saved` | `soothe.lifecycle.checkpoint.saving` | Saving action |
| `soothe.lifecycle.daemon.heartbeat` | `soothe.system.daemon.heartbeat` | Domain migration |

### 8.2 Protocol Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.protocol.memory.recalled` | `soothe.protocol.memory.recalling` | Present progressive |
| `soothe.protocol.memory.stored` | `soothe.protocol.memory.storing` | Present progressive |
| `soothe.protocol.policy.checked` | `soothe.protocol.policy.checking` | Present progressive |

### 8.3 Cognitive Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.cognition.plan.created` | `soothe.cognition.plan.creating` | Present progressive |
| `soothe.cognition.plan.step_started` | `soothe.cognition.plan.step.started` | Hierarchical component |
| `soothe.cognition.plan.reflected` | `soothe.cognition.plan.reflecting` | Present progressive |
| `soothe.cognition.goal.created` | `soothe.cognition.goal.creating` | Present progressive |
| `soothe.cognition.goal.directives_applied` | `soothe.cognition.goal.directives_applying` | Present progressive |
| `soothe.cognition.goal.deferred` | `soothe.cognition.goal.deferring` | Present progressive |
| `soothe.cognition.strange_loop.reason` | `soothe.cognition.strange_loop.reasoning` | Present progressive |

### 8.4 Subagent delegated UX (`soothe.subagent.*`, IG-339)

Built-in subagents emit **only** allowlisted, metadata-only progress types under `soothe.subagent.<agent>.<signal>`. The allowlist and field caps live in **`soothe_sdk.core.subagent_wire`** (`ALLOWLISTED_SUBAGENT_EVENT_TYPES`, `clip_wire_event_payload`). Full prompts, raw HTML, and unconstrained transcripts stay off the custom stream; use LangGraph **`messages`** where the subgraph exposes LangChain tool calls and assistant text.

**Historical note**: An interim `soothe.capability.*` naming experiment appeared in early migration drafts. It was **never** the stable wire contract and has been **removed** from producers and clients. Do not subscribe to `soothe.capability.*` for built-in subagents.

| Agent | Curated custom-stream types (examples) | Purpose |
|-------|------------------------------------------|---------|
| Community web delegate | `soothe.subagent.browser.started`, `…step.completed`, `…completed` | Lifecycle + step metadata |
| Community coding delegate | `…claude.started`, `…completed`, `…failed` | Lifecycle + outcome |
| Explore | `…explore.started`, `…milestone`, `…completed` | Lifecycle + assessment milestone + done |
| Research | `…research.started`, `…gather.summary`, `…completed` | Lifecycle + gather batch + done |

Run-level completion uses types ending in `.completed` but **not** `*.step.completed` (step lines are activity milestones).

### 8.4.1 Archived migration table (pre-IG-339, obsolete)

The following table recorded an abandoned rename toward `soothe.capability.*`. **Ignore for integration work**; retained only as archaeology.

| Old Type | Superseded direction (obsolete) | Notes |
|----------|----------------------------------|-------|
| `soothe.subagent.<id>.dispatched` | *(never shipped as stable)* | Use curated `soothe.subagent.<id>.*` |
| `soothe.subagent.<id>.text` | *(removed from wire)* | Assistant text → `messages` stream |
| `soothe.subagent.research.analyze` | *(removed from wire)* | Use curated research types |

### 8.5 System Events

| Old Type | New Type | Notes |
|----------|----------|-------|
| `soothe.autopilot.*` | `soothe.system.autopilot.*` | Domain migration |
| `soothe.autopilot.goal_created` | `soothe.system.autopilot.goal.creating` | Domain + hierarchical |
| `soothe.autopilot.dreaming_entered` | `soothe.system.autopilot.dreaming.started` | Domain + present progressive |
| `soothe.autopilot.relationship_detected` | `soothe.system.autopilot.relationship.detecting` | Domain + present progressive |

### 8.6 Output domain (ancillary naming only)

**IG-317:** Core-loop assistant prose is **not** named under `soothe.output.*`. The table below is a **style reference** for optional `soothe.output.*` telemetry if you introduce new ancillary events—not a migration checklist for assistant answers.

| Old Type (example) | New Type (example) | Notes |
|----------|----------|-------|
| `soothe.output.telemetry.pending` | `soothe.output.telemetry.reporting` | Present progressive |
| `soothe.output.batch.summary` | `soothe.output.batch.summary.reporting` | Hierarchical + present progressive |

---

## 9. Implementation Checklist

### 9.1 Pre-Migration

- [ ] Create `scripts/migrate_event_names.py` migration script
- [ ] Create `scripts/validate_event_names.py` validation script
- [ ] Test migration script on sample files
- [ ] Create clean feature branch for migration

### 9.2 Phase 1: Event Catalog

- [ ] Migrate `core/events/catalog.py` core events
- [ ] Migrate `core/events/catalog.py` and per-module `register_event()` sites (e.g. `core/strange_loop/utils/events.py`)
- [x] Migrate community plugin event modules under `soothe_plugins/` (IG-415)
- [ ] Migrate `subagents/research/events.py`
- [ ] Migrate `plugin/events.py`
- [ ] Run `make lint` and fix errors
- [ ] Run unit tests and fix failures

### 9.3 Phase 2: Emitter Code

- [ ] Update all `custom_event()` calls
- [ ] Update all event constant imports
- [ ] Update all hardcoded event type strings
- [ ] Run `make lint` and fix errors
- [ ] Run unit tests and fix failures

### 9.4 Phase 3: Tests

- [ ] Update test assertions
- [ ] Update mock event data
- [ ] Update test fixtures
- [ ] Run all unit tests
- [ ] Ensure 900+ tests pass

### 9.5 Phase 4: Documentation & Verification

- [ ] Update RFC-400 references
- [ ] Update CLAUDE.md
- [ ] Update event-catalog.md
- [ ] Run `./scripts/verify_finally.sh`
- [ ] Run manual daemon tests
- [ ] Run TUI tests
- [ ] Run CLI tests
- [ ] Add validation script to CI
- [ ] Add validation script to pre-commit hooks

---

## 10. Success Criteria

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

## 11. Relationship to Other RFCs

* **RFC-401 (Event Processing)**: Architecture and registry implementation; RFC-403 defines naming semantics
* **RFC-501 (Display & Verbosity)**: VerbosityTier classification for events
* **RFC-600 (Plugin Extension System)**: Plugin lifecycle managed by core
* **event-catalog.md**: Complete event type registry using RFC-402 naming

---

## 12. Open Questions

1. **Policy events**: Should `soothe.protocol.policy.checked` become `checking` (action) or keep `checked` (state)? **Resolution**: Use `checking` as present progressive action.

2. **Verb consistency**: Should "completed" events become `completing`? **Resolution**: Keep `completed` as it represents present progressive result state.

3. **Tool events**: Should `soothe.tool.*` migrate under a `capability` domain? **Resolution (superseded by IG-339)**: Main-graph tools remain `soothe.tool.*` where used; delegated subagent **sparse** UX signals use **`soothe.subagent.*`** only—not `soothe.capability.*`.

4. **Internal vs external (subagents)**: **Resolution (IG-339)**: Curated **`soothe.subagent.<agent>.<signal>`** for sparse progress; step-like activity uses explicit names (e.g. `browser.step.completed`), not generic `.running` churn. Rich transcripts stay on **`messages`**.

5. **Domain decision**: Where do new protocol/backend events belong? **Resolution**: Protocol implementation operations → `protocol` domain.

---

## 13. Conclusion

This RFC establishes unified semantics for Soothe's event naming:

- Present progressive tense grammar eliminates confusion
- Function-based domains clarify semantic boundaries
- Plugin extension namespace prevents collisions
- Approved vocabularies enforce consistency
- Validation rules prevent drift
- Systematic migration ensures correctness

> **Unified semantics, clear domains, scalable extension.**

---

## 14. References

* Design draft: `docs/drafts/2026-04-15-event-naming-semantics-unification-design.md`
* Event catalog: `docs/specs/event-catalog.md`
* RFC-400: Event Processing & Filtering