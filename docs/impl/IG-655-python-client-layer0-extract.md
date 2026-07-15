# IG-655: Extract soothe-client-python (Layer 0)

**Guide**: IG-655  
**Title**: Extract WebSocket client from soothe-sdk into `client/python`  
**Created**: 2026-07-15  
**Related**: RFC-629 (Client Appkit), RFC-450 (Protocol-1), RFC-610 (SDK structure)  
**Status**: Phase D + IG-651 lifecycle + packaging (Makefile/CI/examples) (2026-07-16)

---

## Goal

Align Python with Go/TS client layout:

```
soothe-cli → soothe-client-python → [WS] → daemon → soothe (core)
                 └─► soothe-sdk (slim contracts)
```

## Phase A (this guide)

1. Create `client/python` (`soothe-client-python`, import `soothe_client`).
2. Move Layer 0 transport modules out of `soothe_sdk.client`.
3. Keep shared wire/config/codec in slim SDK (`wire`, `protocol`, `config`).
4. Point CLI / daemon (and tests) at `soothe_client` for transport APIs.
5. **No** SDK → client re-export shims (SDK must stay independent of workspace packages).

## Module placement

| Move to `soothe_client` | Keep in `soothe_sdk.client` |
|-------------------------|----------------------------|
| `websocket.py` | `wire.py` |
| `session.py` | `protocol.py` |
| `helpers.py` | `config.py` |
| `ws_command_client.py` | |
| `protocol_params.py` | |
| `schemas.py` | |
| `intent_hints.py` | |

## Later phases

- **B**: Slim SDK further — relocate wire/paths out of `soothe_sdk.client` ✓
- **C**: Thin CLI onto client; remove `soothe.*` leaks ✓
- **D**: Python `appkit` (promote CLI session/turn generics) — first slice ✓
  (Pool / TurnRunner / EventClassifier deferred).

## Phase B (slim SDK layout)

| Old path | Canonical path |
|----------|----------------|
| `soothe_sdk.client.wire` | `soothe_sdk.wire.codec` (`soothe_sdk.wire`) |
| `soothe_sdk.client.protocol` | `soothe_sdk.wire.protocol` |
| `soothe_sdk.client.config` | `soothe_sdk.paths` |

Compat shims under `soothe_sdk.client.*` remain for one migration window.

## Phase C (thin CLI; no core imports)

| Leak | Remediation |
|------|-------------|
| `/context` CE persistence via `soothe.config` + `resolve_context_engine_persistence` | Load goals via daemon `fetch_loop_history` (RFC-631 snapshots); wire `daemon_session` into `ContextViewerScreen` |
| `run_cmd` `--mcp-config` via `MCPServerConfig` | Flag is daemon-owned post-split; CLI warns and ignores |
| `cognition_goal_tree` `is_error_tool_result_text` | Canonical helper in `soothe_sdk.display.tool_result`; core re-exports |
| CLI tests importing `LoopAIMessage` | Use `SimpleNamespace` / getattr phase only |

## Exit criteria

### Phase A
- [x] `client/python` is a uv workspace member
- [x] Unit tests for Layer 0 live under `client/python/tests`
- [x] CLI + daemon transport imports use `soothe_client`
- [x] SDK no longer depends on `websockets` for runtime
- [x] `./scripts/verify_finally.sh` green

### Phase B
- [x] Wire/paths live under `soothe_sdk.wire` / `soothe_sdk.paths`
- [x] Compat shims keep old `soothe_sdk.client.*` imports working
- [x] SDK package description reflects slim contracts (no transport client)
- [x] `./scripts/verify_finally.sh` green

### Phase C
- [x] `packages/soothe-cli` has no `soothe.*` (core) imports
- [x] `/context` goals load via daemon session RPC (not core persistence)
- [x] Shared tool-error text helper lives in slim SDK
- [x] `./scripts/verify_finally.sh` green

### Phase D (Python appkit)

Promote product-agnostic CLI turn/session mechanics into `soothe_client.appkit`
(parity vocabulary with Go/TS **plus** CLI-grade daemon interaction Go/TS lack).

| Component | Status |
|-----------|--------|
| `unwrap_next` / `is_loop_scoped_event` | ✓ |
| `QueryGate` | ✓ |
| `TurnEventPipeline` / `run_turn_pipeline` | ✓ (CLI re-exports) |
| `SessionStore` Protocol | ✓ |
| Layer 0 `loop_*` RPCs + helpers | ✓ |
| `DaemonSession` + `iter_turn_chunks` (dual-socket, post-idle drain) | ✓ |
| `EventClassifier` / `extract_thinking_step` / `SSEBroadcaster` | ✓ |
| `ReattachAndProbe` / `Disconnected` | ✓ |
| `ConnectionPool` / `TurnRunner` | ✓ |
| Idle / soft-complete / attachments (IG-651 parity) | ✓ |

- [x] `soothe_client.appkit` package exists with unit tests
- [x] CLI turn pipeline + `_unwrap_next` duplicates removed (shims / imports)
- [x] CLI `TuiDaemonSession` wraps `DaemonSession`
- [x] Python client unit tests green (`client/python`)

**Status**: Phase D + IG-651 lifecycle + packaging (2026-07-16)
