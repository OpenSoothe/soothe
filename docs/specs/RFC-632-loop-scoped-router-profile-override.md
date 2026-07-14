# RFC-632: Loop-Scoped Router Profile Override

**RFC**: 632  
**Title**: Loop-Scoped Router Profile Override  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-07-14  
**Authors**: xiaming (with Cursor)  
**Depends on**: RFC-450 (Daemon Protocol — `input` / turn overrides), RFC-454 (Slash Command Architecture), RFC-500 (CLI TUI), RFC-503 (Loop-First UX), RFC-627 (LLM Utilities / ModelRouter)  
**Related**: RFC-450 `model` / `model_params` per-turn override; IG-545 (RoleRoutingMiddleware)  
**Design**: [docs/drafts/2026-07-14-loop-scoped-router-profile-design.md](../drafts/2026-07-14-loop-scoped-router-profile-design.md)  
**Implemented by**: [IG-592](../impl/IG-592-loop-scoped-router-profile-override.md)

---

## 1. Abstract

This RFC defines a **loop-scoped router profile override**: the TUI command `/model-router` selects a named entry from configured `router_profiles` for the current StrangeLoop. Subsequent turns in that loop resolve **chat** `ModelRouter` roles from the selected preset. Process-wide `active_router_profile` and `embedding_profile` remain the daemon/host defaults. New loops and `/clear` drop the override.

The mechanism mirrors the existing per-turn `/model` path: client session memory + optional wire field on `input`, validated and applied as a **turn-scoped overlay** on the daemon—not a mutation of loaded YAML.

---

## 2. Scope and Non-Goals

### 2.1 Scope

* TUI `/model-router` slash command (selector, direct name, `--clear`).
* Client-held loop session override cleared on new loop, `/clear`, and resume start.
* Optional `router_profile` field on daemon turn `input` (RFC-450 family).
* Daemon turn overlay that affects **chat** role resolution (`default`, `think`, `fast`, `image`, `ocr`, and any future chat roles), attached in the **loop worker** from `LoopRunRequest` (not the parent QueryEngine process).
* Layering with existing stream `/model` override.
* Validation against loaded `router_profiles` names.

### 2.2 Non-Goals

* Persisting the override on loop metadata or restoring it on `/resume` / TUI restart.
* Switching process-wide embedding model or dimensions for the override (indexes stay on the process embedding profile).
* Writing `active_router_profile` back to `config.yml` (no `--default` in this RFC).
* Changing how `router_profiles` are declared or how load-time `_apply_active_router_profile` works.
* Requiring autopilot / Discord / other channels to pass the field (optional for them).

---

## 3. Motivation

Named `router_profiles` already let operators define deployment presets (cloud vs local, different think/fast/default maps). Selection today is process-global (`active_router_profile` / `SOOTHE_ACTIVE_ROUTER_PROFILE`) at config load.

Interactive users need a **temporary** preset for one loop (e.g. try `local-deploy` without reloading the daemon, then return to `production` on `/clear`) without losing the multi-role map that `/model` alone cannot express.

---

## 4. Guiding Principles

1. **Loop boundary = override boundary.** Stick across goals in the loop; reset on new loop / `/clear`.
2. **Mirror `/model` durability.** Client session memory only; no loop DB, no resume restore in v1.
3. **Chat roles only.** Overlay must not change process embedding model or dims.
4. **Do not mutate process config.** Overlay is turn-scoped; YAML-derived `router` stays the process default.
5. **Fail loud on unknown names.** No silent fallback to `active_router_profile` when a name is sent but invalid.
6. **Compose with `/model`.** Profile fills roles; stream model override still wins on the hop `PerTurnModelMiddleware` patches.

---

## 5. Component Overview

```text
TUI /model-router
        │
        ▼
_router_profile_override (client session)
        │
        ▼
input.router_profile  ──►  daemon validate name
                                │
                                ▼
                   LoopRunRequest.router_profile (+ model)
                                │
                                ▼
                   worker: stream_turn_overrides (contextvar)
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                    ▼
   resolve_model(chat roles)          embedding model / embedding_dims
   (+ RoleRoutingMiddleware)          = process embedding_profile
              ▲
              │
   optional input.model ──► PerTurnModelMiddleware (wins for stream default)
```

| Component | Responsibility |
|-----------|----------------|
| TUI command + state | Set/clear override; pass on each turn; clear with loop lifecycle |
| Protocol `input` | Optional `router_profile: string \| null` |
| Daemon query turn | Validate name; put fields on `LoopRunRequest` |
| Loop worker | `stream_turn_overrides` attach/reset around `astream` |
| Resolution path | Read overlay for chat roles; never for embedding |

---

## 6. Behavior Contract

### 6.1 Selection and reset

| Event | Effect |
|-------|--------|
| `/model-router` | Open selector of configured profile names (mark config default + current selection) |
| `/model-router <name>` | Set override if name ∈ loaded profiles; else TUI error |
| `/model-router --clear` | Clear override |
| New loop / `/clear` | Clear override |
| `/resume` (v1) | Do not restore a prior override |

### 6.2 Apply timing

Override applies on the **next** user turn / daemon query that carries the field (same class as `/model`).

### 6.3 Effective resolution order (per hop)

1. Stream `/model` override attached for this turn → wins for the patched request model.
2. Else stream router-profile overlay set → use that profile’s `ModelRouter` for chat `resolve_model(role)`.
3. Else process `active_router_profile` / derived `router`.

For `role == embedding` (and process `embedding_profile`): always (3), never (2).

### 6.4 Independence

Clearing the profile override does not clear `/model`. Setting a profile does not clear `/model`.

---

## 7. Protocol Extension (RFC-450)

Extend turn `input` params with:

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `router_profile` | `string \| null` | No | Profile name for this turn’s chat-role overlay; omit/null → process default |

Daemon SHALL:

* Reject the turn with a clear validation/application error if the name is non-empty and not in `router_profiles`.
* Accept omit/null without changing behavior vs today.

Optional follow-on RPC (not required for v1): list profile names for the TUI selector if the client cannot obtain them from an existing config snapshot. Implementations MAY reuse any existing daemon config introspection; this RFC does not mandate a new RPC if the client already has the name list.

---

## 8. Slash Command

Register `/model-router` in the unified command registry (RFC-454):

* **Bypass tier**: `IMMEDIATE_UI` (align with `/model` — bare opens UI without racing the agent).
* **Aliases**: none required in v1.
* User-visible strings MUST NOT include IG/RFC identifiers (project terminology rule).

---

## 9. Error Handling

| Case | Behavior |
|------|----------|
| Unknown name (client) | Do not set override; show error |
| Unknown name (daemon) | Fail the turn; do not fall back silently |
| Empty / omitted field | No overlay |
| Mid-busy bare command | Follow `/model` immediate-UI rules |

---

## 10. Testing Requirements

* Daemon: valid `router_profile` changes chat role resolution; embedding + dims unchanged.
* Daemon: unknown name rejected.
* TUI: set / `--clear` / `/clear` / new loop clear state; payload includes field when set.
* Layering: profile + `/model` → stream model wins on default hop; other chat roles still from profile.
* Omitted field → identical to pre-RFC behavior.

---

## 11. Rollout Notes

Likely packages: `soothe-cli` (command, state, payload), `soothe-daemon` (schema, turn attach), `soothe` (overlay + `resolve_model` / role routing), `soothe-sdk` if protocol params are shared.

Wiki: document `/model-router` beside `/model`; config docs remain authoritative for declaring profiles.

---

## 12. Future Work (out of this RFC)

* Status bar badge when overridden.
* `/model-router --default` to persist `active_router_profile`.
* Persist on loop record for `/resume`.
* Mid-loop embedding switch with migration rules (explicitly deferred).

---

## 13. Change History

| Date | Change |
|------|--------|
| 2026-07-14 | Initial Draft from design brainstorm |
| 2026-07-14 | TUI command renamed `/router-profile` → `/model-router` |
| 2026-07-14 | Overlay attach moved to loop workers only; removed ineffective parent QueryEngine ContextVar path |
