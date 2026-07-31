# IG-602: Orphan Wired-Subagent Card (Intake-Only Progress UX)

**Created**: 2026-07-15  
**Status**: Implemented  
**Related**: [RFC-630 §6.3.3](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [RFC-628 Part III](../specs/RFC-628-step-card-display-refactor.md), [IG-599](IG-599-pass2-wired-subagent-direct-route.md), [IG-600](IG-600-intake-only-wire-subagent-exposure.md), [IG-601](IG-601-intake-only-subagent-dual-registry.md)  
**Design draft**: [docs/drafts/2026-07-15-orphan-wired-subagent-card-design.md](../drafts/2026-07-15-orphan-wired-subagent-card-design.md)  
**Trigger**: loop `779b` — intake-only `deep_research` direct invoke with no SubAgent card (plan-phase only).

---

## Executive Summary

Intake-only wired specialists run via direct invoke (no CoreAgent `task`), so the TUI never mounts a parented SubAgent card. This guide implements the **stream bridge** (RFC-630 §6.3.3) and **orphan SubAgent card** (RFC-628 Part III): lifecycle emits + custom-wire forward from `invoke_wired_subagent`, and TUI mount/route/complete without a parent step.

All allowlisted specialists (`planner`, `browser_use`, `deep_research`, `academic_research`) use this path after [IG-656](IG-656-planner-intake-only.md).

---

## Scope

### In Scope

1. `wired_subagent_started` / `completed` / `failed` / `cancelled` emits from intake-only path
2. Stream specialist under custom mode; forward `soothe.subagent.*` + `invocation_id` via `ctx.emit("stream_event", …)`
3. TUI orphan card: registry key `wire:{subagent}:{invocation_id}`, empty parents, wire routing without `step_w`
4. Demote thinking/plan-phase primacy after orphan mount; finalize orphans on turn teardown
5. Unit tests (orchestrator + TUI); cleanse any dead “only ainvoke” comments that contradict streaming

### Out of Scope

- Re-registering intake-only names on CoreAgent `task` / plan `delegate`
- Fake StrangeLoop step card solely to parent a SubAgent
- `/resume` mid-specialist persistence
- Changing specialist internal wire event schemas (only stamp `invocation_id` / forward)

---

## Design

### Orchestrator (`_invoke_intake_only_direct`)

```
plan_phase_status «Delegating…»
wired_subagent_started {subagent, invocation_id, step_id, description}
astream / custom bridge → for each soothe.subagent.*:
    stamp invocation_id (+ step_id) → ctx.emit("stream_event", …)
on success → extract report → ledger → wired_subagent_completed
on exception → wired_subagent_failed (+ existing fatal policy)
on cancel → wired_subagent_cancelled (best-effort)
→ route to goal_completion
```

| Field | Source |
|-------|--------|
| `invocation_id` | New uuid4 hex (8–12 chars) per invoke |
| `step_id` | Trivial-plan `steps[0].id` (already built before invoke) |
| `description` | Goal text (trim for display; full goal may be separate field) |

**Streaming**: Prefer `runnable.astream(..., stream_mode=["custom", "values"])` (or project-equivalent) so `get_stream_writer()` events surface. Collect final state/messages for `_extract_subagent_report`. If astream is impractical for a given CompiledSubAgent shape, an explicit emit-bridge that polls writer callbacks is acceptable — bare `ainvoke` alone is **not**.

Mirror execute’s pattern: `await ctx.emit("stream_event", item)` for custom chunks (same envelope shape the adapter already consumes for nested customs).

### TUI (`textual_adapter`)

| Event | Action |
|-------|--------|
| `wired_subagent_started` | `create_subagent_card(..., parent_step_id="", parent_task_key="")`; register `_subagent_cards_by_key[f"wire:{subagent}:{invocation_id}"]`; `_mount_message`; stop treating thinking row as primary progress |
| Forwarded `soothe.subagent.*` with `invocation_id` | Resolve orphan card; synthetic `TaskScope` `(f"{step_id}:s:task:0", subagent, step_id)`; call existing `_route_subagent_wire_event` / `_apply_subagent_wire_*` **without** requiring `_current_step_messages[step_id]` |
| `wired_subagent_completed` / `failed` / `cancelled` | `_complete_subagent_card`; pop `wire:` key |
| Turn clear / disconnect | Finalize remaining `wire:` keys |

Keep parented path (`{step}:t{n}`) unchanged. Prefer **one** `_subagent_cards_by_key` with `wire:` prefix over a second dict.

Helper suggestions (keep thin):

- `_orphan_registry_key(subagent, invocation_id) -> str`
- `_ensure_orphan_subagent_card(adapter, payload) -> card`
- `_lookup_orphan_card_from_wire_data(adapter, data) -> card | None`

---

## Files

| File | Action |
|------|--------|
| `packages/soothe/.../orchestrator/nodes/invoke_wired_subagent.py` | Lifecycle emits; replace bare `ainvoke` with stream+forward; stamp customs |
| Possibly small helper under `foundation/sloop/utils/` or next to node | Emit-bridge / stream_event normalize (optional) |
| `packages/soothe-cli/.../tui/textual_adapter.py` | Handlers for started/completed + orphan wire route |
| `packages/soothe-cli/.../tui/widgets/messages/cognition_step.py` | `create_subagent_card` factory (orphan fields on shared step card) |
| Event constants / SDK (if typed names required) | Register `wired_subagent_*` or map via existing custom catalog |
| `packages/soothe/tests/unit/.../orchestrator/test_invoke_wired_subagent.py` | Extend: started → custom → completed; ledger + route |
| `packages/soothe-cli/tests/unit/...` | Orphan mount / wire attach / cancel finalize / parented regression |
| RFC-628 Part III / draft status | Point «Implemented by» → this IG when done |

---

## Error handling

| Case | Behavior |
|------|----------|
| Lookup / no runnable | Existing fatal; no `started` (or `started` then immediate `failed` if already emitted) |
| Invoke exception | `wired_subagent_failed`; card error; keep current fatal vs goal_completion policy |
| Wire event, unknown `invocation_id` | Drop (no phantom card) |
| Duplicate `started` same id | Idempotent ignore |
| Client disconnect | Adapter finalize orphans; orchestrator cancel → `cancelled` best-effort |

User-visible strings: no IG/RFC identifiers.

---

## Testing

| Test | Assert |
|------|--------|
| Orchestrator happy path | Emits started; ≥1 forwarded custom (fake runnable writing wire event); completed; ledger Human/AI; routes to `goal_completion` |
| Orchestrator failure | failed lifecycle + existing error outcome |
| Orchestrator planner path | No orphan lifecycle emits |
| TUI mount | started → card in registry with empty parent; mounted |
| TUI wire | soothe.subagent step/note attaches rows without `_current_step_messages` |
| TUI complete / cancel | Registry cleared; not left Running |
| Regression | Parented `task` SubAgent path still mounts under step |

Acceptance forensic: a loop like `779b` must show client `wired_subagent_started` (and progress or terminal), not plan-phase-only.

Gate: `./scripts/verify_finally.sh` before commit.

---

## Cleanse

- [x] Docs/comments that describe intake-only as «ainvoke only» without streaming
- [x] Dual `{step}:t0` SubAgent registry alias for orphans (use `wire:{name}:{invocation}` + `_orphan_cards_by_invocation` / step_id lookup only)
- [x] Any dead dual path that synthesizes fake step/`task` for this UX (must not ship)
- [x] Temporary debug hacks for plan-phase-only progress once card path ships
- [x] `browser_use` events: foundation `register_event` only (no SDK registry / duplicate wire allowlist)
- [x] Stale `/research` slash examples in CLI/TUI comments; `/«subagent»` help points at plugins

---

## Acceptance

- [x] IG authored
- [x] Intake-only path emits started → stream customs → terminal lifecycle
- [x] TUI mounts orphan SubAgent card; wire progress visible
- [x] Cancel/fail leaves no stuck orphan Running card
- [x] `planner` / parented SubAgent path unchanged
- [x] RFC-628 Part III status notes implementation; verify green
- [x] Related dead dual paths cleansed

---

## Coding plan (impl-code)

1. Orchestrator stream bridge + lifecycle emits (tests first / with)
2. TUI orphan registry + started/complete handlers
3. Wire routing bypass for orphan scope
4. Turn teardown finalize
5. Cleanse + `./scripts/verify_finally.sh`

---

## Revision History

| Date | Change |
|------|--------|
| 2026-07-15 | Initial guide from design draft + RFC-630 §6.3.3 / RFC-628 Part III |
