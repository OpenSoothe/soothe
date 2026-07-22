---
title: "Event System"
parent: Core Modules
grand_parent: Wiki
nav_order: 5
description: Centralized event infrastructure for Soothe's protocol observability and event registration.
---

# Event System

Centralized event infrastructure for Soothe's protocol observability.

---

## What This Module Is

The event system (`soothe.events`) provides the vocabulary and plumbing for all observability in Soothe. It defines event type constants, Pydantic event models, a registry for O(1) lookup, and the visibility rules that decide which events reach WebSocket clients. Every `soothe.*` custom event in the stream originates here.

The system exists because Soothe streams execution progress to clients in real time. Without a centralized event catalog, visibility rules would be scattered across daemon delivery stages, and bugs would silently drop user-visible output.

**Source**: `packages/soothe/src/soothe/events/` (`constants.py`, `catalog.py`, `visibility.py`, `internal_bus.py`)

---

## The Naming Convention (RFC-403)

All event types follow a **4-segment convention**: `soothe.<domain>.<component>.<action>`

This is enforced as string constants in `constants.py` — the single source of truth. There is no string concatenation at call sites; every event type is a named constant imported from the catalog.

The critical design split is between two namespaces:

- **Client-facing** (`soothe.<domain>.*`) — events that may reach WebSocket clients. Domains include `cognition` (goal/plan/strange_loop), `system` (autopilot status), and `error`.
- **Internal** (`soothe.internal.*`) — **never** broadcast to clients. These cover iteration lifecycle, checkpointing, recovery, loop lifecycle, memory/policy protocol internals, daemon heartbeats, plugin lifecycle, and branch internals.

This split exists because the daemon, workers, and internal tooling need fine-grained observability that clients shouldn't see (implementation details, high-frequency checkpoints, internal state transitions). Mixing them into one namespace would require filtering logic everywhere; the prefix makes the intent explicit at the constant definition site.

---

## Event Domains at a Glance

Rather than enumerate all 60+ constants, here are the domains and what they represent:

| Domain | Namespace | Covers |
|--------|-----------|--------|
| **Goal cognition** | `soothe.cognition.goal.*` | created, completed, failed, removed, decomposed, deferred, reported |
| **Plan cognition** | `soothe.cognition.plan.*` | created, reflected |
| **StrangeLoop** | `soothe.cognition.strange_loop.*` | started, completed, step started/queued/completed, plan decision, reasoned, context compacted |
| **Branch** | `soothe.cognition.branch.*` | created, retry started |
| **Autopilot** | `soothe.system.autopilot.*` | status changed, goal created/progress/completed/suspended/blocked, dreaming |
| **Intent** | `soothe.cognition.intent.*` | classified (IG-518) |
| **Error** | `soothe.error.*` | general failures |
| **LLM retry** | `soothe.cognition.llm.retry.*` | retry attempts (IG-504) |
| **Internal** | `soothe.internal.*` | iteration, checkpoint, recovery, loop, memory, policy, daemon, plugin, plan DAG, skill, MCP, branch analysis, autopilot details |

---

## The Registry Pattern

Event models (Pydantic subclasses of `SootheEvent` from `soothe_sdk`) are registered in an `EventRegistry` at import time. The registry provides:

- **O(1) lookup** by event type string — used by the daemon's delivery pipeline to check visibility and verbosity.
- **Summary templates** — string templates (e.g., `"Goal {goal_id} created"`) that interpolate event fields for human-readable summaries.
- **Verbosity tiers** — each event type is assigned a tier (`QUIET`, `NORMAL`, `VERBOSE`, `DEBUG`) that controls client delivery based on the client's configured verbosity ceiling.

Custom events from plugins register via `register_event()`:

```python
from soothe.events import register_event, SootheEvent

class MyCustomEvent(SootheEvent):
    type: str = "soothe.cognition.plugin.my_event"
    custom_data: str

register_event(MyCustomEvent, summary_template="Custom: {custom_data}")
```

---

## The Visibility System — Why It's Centralized

Visibility rules silently drop frames. A bug here is invisible until users report "no output." The IG-435 regression postmortem documented exactly this: `mode=messages` envelopes weren't enumerated as a wire shape, fell through to "unknown event type → DEBUG tier → suppress," and every synthesized answer was dropped.

To prevent that class of regression, `visibility.py` classifies each wire frame into an explicit `WireEnvelopeKind` and dispatches on it. **There is no implicit fallback.** Unknown shapes fail loud (warning log + suppress) so future schema changes are caught immediately.

The visibility module is the single authority for "may this frame reach a WebSocket client?" Four daemon delivery stages funnel through it:

1. `SootheDaemon._broadcast` — broadcast-time gate
2. Session manager sender — per-client tier filter
3. `StreamDeliveryCoalescer` — early drop of invisible `custom` payloads
4. Event reattachment — history-replay filter on reattach

### Wire Frame Shapes

The daemon sends five kinds of frames to clients:

1. **Control frames** (`status`, `error`, `replay_complete`, `loop_*_response`) — always visible.
2. **Catalog events** — `{"type": "event", "mode": "custom", "data": {"type": "soothe.*"}}`. Visible iff non-internal and verbosity tier ≤ client ceiling.
3. **LangGraph message chunks** — `mode: "messages"`. Always visible (carries assistant text and tool I/O).
4. **LangGraph updates** — `mode: "updates"`. Dropped earlier by the coalescer (only interrupts survive).
5. **Unknown** — logged at WARNING on first observation, then suppressed.

---

## The Canonical Stream Chunk

Events flow through the system as `StreamChunk` tuples: `(namespace, mode, data)`. The helper `custom_event(data)` builds a chunk with an empty namespace and `"custom"` mode. This is the deepagents-canonical format that the runner yields and the daemon delivers.

---

## Event Emission Pattern

The recommended pattern for type-safe emission:

```python
from soothe.events import GoalCreatedEvent, custom_event

yield custom_event(GoalCreatedEvent(goal_id=gid).to_dict())
```

For comparisons and routing, use the string constants:

```python
from soothe.events import GOAL_CREATED
if event_type == GOAL_CREATED:
    handle_goal_created(event_data)
```

---

## Internal Event Bus

Beyond the client-facing stream, there's an `InternalEventBus` for daemon/worker-internal pub/sub. This is separate from the client stream — internal events (`soothe.internal.*`) never appear on the WebSocket. The bus supports subscribing to specific event types with handler callbacks, used for cross-component coordination within the daemon process.

---

## Gotchas

- **Never broadcast `soothe.internal.*`** — the visibility module enforces this, but if you bypass the centralized predicates (e.g., by writing directly to the WebSocket), you'll leak internal state to clients.
- **Adding a new wire shape requires extending the enum** — the `WireEnvelopeKind` dispatch table has no implicit fallback. If you introduce a new `mode` value, you must register it or it will be suppressed with a warning.
- **Verbosity tiers are per-event-type, not per-event-instance** — the registry assigns the tier at registration time. To change visibility, re-register the event type.
- **The `REPLAY_COMPLETE` constant** is a wire envelope, not a `soothe.*` catalog event. Prefer the wire `replay_complete` envelope over the deprecated `HISTORY_REPLAY_COMPLETE` alias.

---

## Related

- **[SootheRunner](runner.md)** — yields the canonical event stream
- **[StrangeLoop](strangeloop.md)** — emits cognition events during execution
- **[ContextEngine](goal-engine.md)** — emits goal lifecycle events
- **[RFC-401](../../specs/RFC-401-event-processing.md)** — event processing spec
