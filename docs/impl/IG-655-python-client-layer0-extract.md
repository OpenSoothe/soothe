# IG-655: Extract soothe-client-python (Layer 0)

**Guide**: IG-655  
**Title**: Extract WebSocket client from soothe-sdk into `client/python`  
**Created**: 2026-07-15  
**Related**: RFC-629 (Client Appkit), RFC-450 (Protocol-1), RFC-610 (SDK structure)  
**Status**: In progress (Phase A)

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
- **C**: Thin CLI onto client; remove `soothe.*` leaks.
- **D**: Python `appkit` (promote CLI session/turn generics).

## Phase B (slim SDK layout)

| Old path | Canonical path |
|----------|----------------|
| `soothe_sdk.client.wire` | `soothe_sdk.wire.codec` (`soothe_sdk.wire`) |
| `soothe_sdk.client.protocol` | `soothe_sdk.wire.protocol` |
| `soothe_sdk.client.config` | `soothe_sdk.paths` |

Compat shims under `soothe_sdk.client.*` remain for one migration window.

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

**Status**: Phase B complete (2026-07-15)
