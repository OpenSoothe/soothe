# IG-643: Loop-Scoped Router Profile Override

**IG**: 643  
**Title**: Loop-Scoped Router Profile Override  
**Created**: 2026-07-14  
**Related RFCs**: [RFC-632](../specs/RFC-632-loop-scoped-router-profile-override.md)  
**Depends on**: RFC-450 (`input` model overrides), RFC-454 (slash registry), RFC-627 (ModelRouter), IG-545 (role routing / `/model` wins)  
**Design**: [docs/drafts/2026-07-14-loop-scoped-router-profile-design.md](../drafts/2026-07-14-loop-scoped-router-profile-design.md)  
**Status**: Implemented

---

## Summary

Implement TUI `/model-router` so the user can select a configured `router_profiles` entry for the **current loop**. Each following turn sends `input.router_profile`; the daemon attaches a **turn-scoped chat-role overlay**. Process `embedding_profile` (embedding model + dims) stays unchanged. New loop / `/clear` clear the client override (same durability class as `/model`).

---

## Non-goals (from RFC-632)

- Resume / loop-metadata persistence  
- Overlaying embedding role or dims  
- `/model-router --default` writing YAML  
- Status bar badge (optional follow-on)

---

## Architecture

```text
/model-router → TUI _router_profile_override
                      │
                      ▼
loop_input.router_profile (+ optional model)
                      │
                      ▼
QueryEngine: validate name → LoopRunRequest.router_profile
                      │
                      ▼
worker stream_turn_overrides → resolve_model / RoleRouting — chat roles
embedding / dims = process active profile
                      ▲
                      └── PerTurnModelMiddleware (/model) still wins on patched hop
```

**Resolution order** (per hop):

1. Stream `/model` override → wins for patched request  
2. Else router-profile overlay → chat roles from selected `ModelRouter`  
3. Else process `router`  
4. Embedding always (3)

---

## Work packages

### P0 — Protocol + SDK wire

| Item | Detail |
|------|--------|
| `LoopInputParams` | Add optional `router_profile: str \| None` in `soothe_sdk.client.protocol_params` |
| WS send | `WebSocketClient` / turn send path includes field when set (mirror `model`) |
| Daemon schemas | Mirror field on daemon-side loop input validation if duplicated outside SDK |
| RFC-450 note | Changelog line: `input` may carry `router_profile` |

### P0 — Core overlay + resolution

| Item | Detail |
|------|--------|
| ContextVar API | Prefer sibling to `_model_override.py`, e.g. `_router_profile_override.py`: `attach_stream_router_profile(name)`, `reset_…`, `get_stream_router_profile()` |
| Overlay payload | Store profile **name**; look up `ModelRouter` from `SootheConfig.router_profiles` at resolve time (do not copy embedding) |
| `resolve_model` | If overlay active and `role != "embedding"`: use overlay router (role or fallback to that router’s `default`); if `role == "embedding"`: always process `self.router` |
| RoleRouting / factory | Any path that uses `config.resolve_model` inherits behavior; do **not** mutate `config.router` |
| QueryEngine | Validate name ∈ profiles; pass `router_profile` on `LoopRunRequest`; reject unknown |
| Worker stream | Attach via `stream_turn_overrides` around `SootheRunner.astream` (pool / thread / ray) |

### P0 — TUI command + state

| Item | Detail |
|------|--------|
| Registry | `/model-router` in `command_registry.py`, `BypassTier.IMMEDIATE_UI` |
| State | `_router_profile_override: str \| None` on app (next to `_model_override`) |
| Clear | `_clear_loop_session_overrides()` on `/clear`, new loop, resume start |
| Handler | Bare → selector; `/model-router <name>` → set; `/model-router --clear` → clear |
| Turn payload | Extend `CLIContext` with `router_profile`; `textual_adapter` / session send passes it into `loop_input` |
| Selector data | List profile **names** + mark `active_router_profile`. Prefer extending `models_list` response with `router_profiles: [{name, …}]` and `active_router_profile`, or a thin `config_section` fetch of those keys — reuse startup prewarm pattern from `/model` |

### P1 — UX polish (same PR if cheap)

- Selector highlights current override vs config default  
- Chat `AppMessage` confirming switch / clear (no IG/RFC ids in copy)  
- Autocomplete argument suggestions for known names (optional)

### P2 — Docs

- Wiki slash-command / tips: `/model-router` next to `/model`  
- Config docs: one sentence that TUI can override profile per loop without editing YAML  

---

## Concrete file map

| Area | Paths |
|------|--------|
| SDK | `packages/soothe-sdk/src/soothe_sdk/client/protocol_params.py`, `websocket.py`, wire tests |
| Overlay | `packages/soothe/src/soothe/middleware/_router_profile_override.py` (new), export if needed |
| Resolve | `packages/soothe/src/soothe/config/settings.py` (`resolve_model`) |
| Daemon | `query/engine.py` (validate + `LoopRunRequest`); pool/thread/ray workers (`stream_turn_overrides`); protocol schemas; `models_list` / `models_catalog` |
| TUI | `command_registry.py`, `_app.py`, `_execution.py`, `_model.py` (or `_router_profile.py` mixin), `_cli_context.py`, `textual_adapter.py`, new selector widget or reuse list-modal pattern from `model_selector.py` |
| Tests | See below |

---

## Error handling

| Case | Behavior |
|------|----------|
| Unknown name (TUI) | Do not set; error message |
| Unknown name (daemon) | Reject turn; no silent fallback |
| Empty / omitted | No overlay |
| Profile equals process active | Allowed (idempotent override); optional “already using …” UX like `/model` |

---

## Testing

### Unit — soothe

- Overlay active: `resolve_model("think")` / `fast` / `default` follow named profile; `resolve_model("embedding")` and `embedding_dims` unchanged.  
- No overlay: unchanged from today.  
- Attach/reset restores prior contextvar state.

### Unit — soothe-sdk / daemon

- `LoopInputParams` accepts `router_profile`.  
- Query path rejects unknown name.  
- Worker attaches overlay for known name via `stream_turn_overrides`.

### Unit — soothe-cli

- Set / `--clear` / `/clear` / new loop / resume-start clear state.  
- Turn send includes `router_profile` when set.  
- Layering: profile set + `_model_override` still sends both fields.

### Integration (optional if harness exists)

- One daemon turn with two profiles differing on `think`; assert factory/resolution observed.

**Do not** change unrelated config tests to “pass” by weakening validation.

---

## Implementation order

1. ContextVar + `resolve_model` + unit tests (core behavior independent of TUI).  
2. SDK / daemon `loop_input` field + worker `stream_turn_overrides` + reject unknown.  
3. TUI state, command, payload, clear lifecycle.  
4. Selector + name listing (extend `models_list` or config section).  
5. Docs / tips.  
6. `./scripts/verify_finally.sh`.

---

## Acceptance checklist

- [x] `/model-router <name>` changes chat roles on next turns for that loop  
- [x] Embedding / dims still process active profile  
- [x] `/model` still overrides stream default on top  
- [x] `/clear` and new loop reset to config `active_router_profile`  
- [x] Unknown profile fails loudly client- and daemon-side  
- [x] No YAML mutation; no resume restore  
- [x] Verify script green  

---

## Open implementation choices (pick during coding; defaults below)

| Question | Default |
|----------|---------|
| New file vs extend `_model_override.py` | **New** `_router_profile_override.py` (keep model API focused) |
| Profile list for selector | **Extend `models_list`** with `router_profiles` + `active_router_profile` |
| Selector widget | Thin list modal (names only); reuse model selector chrome only if it stays simpler |
