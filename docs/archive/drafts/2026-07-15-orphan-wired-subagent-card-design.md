# Design Draft: Orphan Wired-Subagent Card

**Status**: Formalized → [RFC-630 §6.3.3](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md) + [RFC-628 Part III](../specs/RFC-628-step-card-display-refactor.md); impl [IG-602](../impl/IG-602-orphan-wired-subagent-card.md) (Implemented)  
**Date**: 2026-07-15  
**Scope**: TUI progress surface for StrangeLoop intake-only `invoke_wired_subagent` (direct specialist invoke, no CoreAgent `task`). Reuses SubAgent card chrome without a parent step card.  
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md) (wired route / intake-only dual registry), [RFC-628](../specs/RFC-628-step-card-display-refactor.md) (step + SubAgent cards), IG-599 / IG-600 / IG-601 (wired direct invoke).  
**Trigger incident**: loop `779b` — `deep_research` ran under bare `ainvoke` (pre–stream bridge); TUI showed only plan-phase «Delegating to deep_research», no SubAgent card; turn cancelled with `step_completed=0` and `goal_interrupted … (no execute evidence)`.

---

## Problem

Intake-only specialists (`browser_use`, `deep_research`, `academic_research`) are invoked from `invoke_wired_subagent` via **streamed direct invoke** on an intake-only registry runnable (post–IG-602). Before the stream bridge, that path used bare `ainvoke` and:

1. Built a trivial plan in scratch (for ledger / goal_completion) but **did not** enter resolve → execute.
2. Emitted only `plan_phase_status` («Delegating to {subagent}»).
3. Emitted specialist `soothe.subagent.*` wire events through LangGraph `get_stream_writer()`, which the worker logged locally but **did not forward** into the StrangeLoop client stream when not nested under executor `astream(..., stream_mode=["messages","custom"])`.

TUI SubAgent cards today mount only when:

1. A Cognition **step** widget exists in `_current_step_messages`, and
2. A main-graph **`task`** tool row creates / binds a card (`create_subagent_card` + `_subagent_cards_by_key`), and
3. Subsequent `soothe.subagent.*` events resolve a `TaskScope` (task_tcid, subagent_type, step_id).

None of those exist on the intake-only path. Result: long specialist runs look like a stuck thinking row; wire progress is invisible; cancel leaves no card lifecycle.

Catalog wire `planner` is unaffected: it still goes resolve → execute → CoreAgent `task` and mounts a parented SubAgent card.

---

## Goal

1. While an intake-only wired specialist runs, the TUI mounts a **standalone SubAgent card** (orphan = no parent step card, no `task` row).
2. Specialist wire progress (`soothe.subagent.*` step / note / lifecycle) appears on that card in the same visual language as parented SubAgent cards.
3. The card completes (success / fail / cancel) when the direct invoke finishes or the turn is cancelled.
4. Do not fake StrangeLoop execute topology (no synthetic step card, no fake CoreAgent `task` on the open catalog).
5. Parenting path for execute-`task` SubAgent cards remains unchanged.

---

## Non-Goals

- Putting intake-only specialists back on CoreAgent `task` / plan `delegate`.
- Changing specialist runnables’ internal wire allowlists or event schemas beyond what streaming/forwarding requires.
- A second visual widget language (new chrome, dashboard, etc.) — reuse SubAgent header / rows / notes.
- Desktop / headless alternate renderers beyond consuming the same wire envelopes (headless may ignore UX; events still flow).
- Replacing `plan_phase_status` for non-wired phases.

---

## Approaches considered

| # | Approach | Pros | Cons |
|---|----------|------|------|
| A | **Fake step + fake `task`** so existing mount path runs | Zero TUI branching | Lies about execute; pollutes step counts / finalize / interrupt markers; contradicts intake-only invisibility |
| B | **Orphan SubAgent card** + lifecycle emits + wire forward | Honest topology; reuses card UX; localizes change to wired node + TUI router | Needs new registry key + started/completed events; must stream customs |
| C | **Upgrade plan-phase only** (richer spinner / text) | Tiny diff | No tool/wire rows; same opaque long-run UX as 779b |

**Decision: B (orphan SubAgent card).**

---

## Decisions

| Topic | Decision |
|-------|----------|
| Card model | Reuse `create_subagent_card` / CognitionStepMessage-as-SubAgent; **empty** `parent_step_id` and `parent_task_key`; `sync_status_to_step` stays no-op |
| Registry key | `wire:{subagent}:{invocation_id}` — separate from `{step_id}:t{task_idx}` |
| Display / step id | Use the trivial-plan step id already produced in `_invoke_intake_only_direct` (stable per invoke); fall back to synthesizing `WIRE-{short}` only if plan build fails |
| Mount trigger | Dedicated **`wired_subagent_started`** envelope (not inferred from plan-phase label alone) |
| Progress | Forward `soothe.subagent.*` customs into the client stream stamped with `invocation_id` / orphan scope |
| Complete | **`wired_subagent_completed`** / **`failed`** / **`cancelled`** after direct invoke; then existing `goal_completion` |
| Plan-phase label | Emit «Delegating…» then, once the orphan card mounts, **stop refreshing** the thinking row as the primary progress surface (card owns the narrative). Do not keep two competing spinners indefinitely |
| Streaming | Direct path must use **`astream` with custom mode** (or an equivalent emit bridge) so `get_stream_writer()` events reach `ctx.emit("stream_event", …)` / the query stream. Final result may still be taken from the last stream state or a follow-up `ainvoke` — implementation detail; progress must not depend on bare `ainvoke` alone |
| `planner` | Unchanged: resolve → execute → parented SubAgent card |

---

## Solution overview

```mermaid
sequenceDiagram
  participant SL as invoke_wired_subagent
  participant Spec as Intake-only runnable
  participant Q as Query stream
  participant TUI as Textual adapter

  SL->>Q: plan_phase_status Delegating…
  SL->>Q: wired_subagent_started (subagent, invocation_id, step_id, description)
  TUI->>TUI: create orphan SubAgent card; mount; register wire:…
  SL->>Spec: astream / invoke with custom writer
  loop progress
    Spec->>Q: stream_event soothe.subagent.* + invocation_id
    TUI->>TUI: route wire event onto orphan card
  end
  SL->>Q: wired_subagent_completed|failed|cancelled
  TUI->>TUI: complete orphan card; unregister
  SL->>SL: ledger Human/AI; route goal_completion
```

---

## Components

### 1. Orchestrator — `invoke_wired_subagent` / `_invoke_intake_only_direct`

| Responsibility | Detail |
|----------------|--------|
| Allocation | Before invoke: `invocation_id` (uuid fragment), resolve wire name, build trivial plan → `step_id`, description from goal text |
| Start emit | `ctx.emit("wired_subagent_started", { subagent, invocation_id, step_id, description, goal })` after (or immediately before) plan-phase status |
| Run | Stream specialist with custom events forwarded: each `soothe.subagent.*` payload re-emitted as `stream_event` (or typed custom) **including** `invocation_id` and `step_id` |
| End emit | On success / exception / cancellation: matching completed / failed / cancelled payload with `duration_ms`, short `summary` |
| Ledger | Unchanged: Human(goal)+AI(report) execute-step rows, then `wired_route_next=goal_completion` |
| Fatal | Existing `fatal_error` path; also failed lifecycle if card was started |

### 2. TUI — orphan registry + mount

| Piece | Responsibility |
|-------|----------------|
| Registry | `_orphan_subagent_cards_by_key: dict[str, card]` **or** unified `_subagent_cards_by_key` with `wire:` keys (prefer **one** registry if key prefixes never collide with `{step}:t{n}`) |
| On `wired_subagent_started` | `create_subagent_card(step_id=…, description=…, subagent_type=…, parent_step_id="", parent_task_key="", task_idx=0)`; mount via `_mount_message`; demote thinking-row primacy |
| Wire routing | If event has orphan `invocation_id` / `wire:` scope, **bypass** `step_w is None` early-return; call existing `_apply_subagent_wire_*` helpers with a synthetic `TaskScope` `(synthetic_task_tcid, subagent_type, step_id)` |
| Synthetic task id | Stable string derived from invocation, e.g. `{step_id}:s:task:0` or `wire:{invocation_id}:task:0` — only for ID parsing / row keys, **never** displayed as a parent task branch |
| Complete | Same `_complete_subagent_card`; skip `sync_status_to_step` when parent empty; pop registry key |
| Cancel | Turn teardown / disconnect must complete orphan cards still running |

### 3. Protocol / SDK

Prefer **reuse** of existing stream_event / custom envelopes where possible. Minimum typed shapes:

| Event | Required fields |
|-------|-----------------|
| `wired_subagent_started` | `subagent`, `invocation_id`, `step_id`, `description` |
| Forwarded `soothe.subagent.*` | existing allowlist + `invocation_id` (and `step_id` when known) |
| `wired_subagent_completed` / `failed` / `cancelled` | `invocation_id`, `duration_ms`, `summary` / error |

User-visible strings must not mention IG/RFC identifiers.

### 4. UX contract

| Moment | User sees |
|--------|-----------|
| Intake wired branch selected | Brief plan-phase «Delegating to {name}», then orphan card mounts |
| Specialist progress | Card header `name(description)` with subagent glyph; wire steps/notes as tool-like rows |
| Footer | Tool/wire-row counts only — **no** «N task» parent branch |
| Success | Card success + optional short summary; then goal completion card / ledger text as today |
| Fail / cancel | Card error state; no orphan left «Running» after turn_finished |

---

## Error handling

| Case | Behavior |
|------|----------|
| Intake-only lookup miss / no runnable | Existing fatal; do not start orphan card (or start then failed if already emitted) |
| Invoke exception | `wired_subagent_failed`; card error; fatal or goal_completion policy unchanged |
| Client disconnect mid-stream | `cancelled` (or adapter finalize-on-teardown); worker cancel as today |
| Wire event without matching orphan | Drop for orphan path; do not invent a second card |
| Duplicate `started` same `invocation_id` | Idempotent: ignore or refresh description |

---

## Testing

- **Orchestrator unit**: intake-only path emits started → ≥1 forwarded wire custom → completed; ledger still written; routes `goal_completion`.
- **Orchestrator unit**: bare catalog `planner` path does **not** emit orphan lifecycle (still resolve/execute).
- **Streaming**: under fake runnable that calls `emit_subagent_wire_event`, customs appear on the query/stream sink (regression for 779b silence).
- **TUI unit**: `wired_subagent_started` mounts card with empty parent; wire step/note attach without `_current_step_messages` entry; completed clears registry.
- **TUI unit**: parented `task` SubAgent path still mounts under step (no regression).
- **Integration / log forensics**: loop like 779b shows card mount + progress while specialist runs.

---

## Rollout / files (implementation hint)

Likely touch points (not exhaustive):

- `packages/soothe/.../orchestrator/nodes/invoke_wired_subagent.py` — lifecycle emits + stream forward
- StrangeLoop stream bridge / runner emission of `stream_event` (mirror `execute_steps`)
- `packages/soothe-cli/.../tui/textual_adapter.py` — orphan mount + wire routing without step parent
- `packages/soothe-cli/.../tui/widgets/messages/cognition_subagent.py` — minor factory defaults for orphan
- Optional: `soothe_sdk` event registration if new type names are required
- Unit tests under `packages/soothe/tests/.../orchestrator/` and `packages/soothe-cli/tests/.../tui/`
- Amend RFC-630 (wired UX) + RFC-628 (orphan SubAgent variant) when formalized

---

## Open questions (deferred)

None blocking v1. Optional later:

- Persist orphan card snapshot for `/resume` mid-specialist (out of scope; specialist itself is not checkpointed as execute today).
- Collapse plan-phase status entirely once started (vs brief handoff).
- Shared helper to mount “delegation cards” for future non-task specialists.

---

## Success criteria

- Intake-only wired run shows an orphan SubAgent card with live wire progress.
- Cancel / fail marks the card terminal; no stuck Running orphan after `turn_finished`.
- `planner` and normal execute-`task` SubAgent cards unchanged.
- Worker logs alone are insufficient proof of UX — client must receive started + at least one progress or completed event in a successful dry-run.
)
