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

## Later phases (not A)

- **B**: Slim SDK further (plugins + contracts only; relocate wire if needed).
- **C**: Thin CLI onto client; remove `soothe.*` leaks.
- **D**: Python `appkit` (promote CLI session/turn generics).

## Exit criteria

- [x] `client/python` is a uv workspace member
- [x] Unit tests for Layer 0 live under `client/python/tests`
- [x] CLI + daemon transport imports use `soothe_client`
- [x] SDK no longer depends on `websockets` for runtime
- [x] `./scripts/verify_finally.sh` green

**Status**: Phase A complete (2026-07-15)
