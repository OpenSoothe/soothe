# IG-657: Thin soothe-cli onto soothe-client abstractions

**Guide**: IG-657  
**Title**: Migrate remaining soothe-cli daemon I/O onto DaemonSession / shared client helpers  
**Created**: 2026-07-16  
**Related**: IG-655, RFC-450, RFC-629  
**Status**: Done (2026-07-16)

---

## Goal

Finish CLI thinning after IG-655: stop hand-rolling `WebSocketClient` connect/handshake/read loops where `DaemonSession` or shared oneshot RPC helpers already exist.

```
soothe-cli (UI) → soothe_client (DaemonSession / helpers / AsyncCommandClient) → daemon
```

## Scope

| Area | Change |
|------|--------|
| Headless `cli/execution/daemon.py` | `DaemonSession` for connect / send_turn / cancel / close; keep `EventProcessor` on stream frames from `session.client` |
| Typer `loop_cmd` / `status_cmd` / `config_cmd` | Shared `protocol1_rpc` / `connected_websocket` in `soothe_client.helpers` |
| TUI skills discovery | Prefer existing session client when available; oneshot fallback |
| TUI `model_config` fetches | Use shared connected helper |
| `command_router` | Prefer `DaemonSession.client` / `loop_id` when a session is passed (compat overload) |

Out of scope: rewriting `EventProcessor` / Textual apply path onto `TurnRunner`; moving chunk_filter into client.

## Exit criteria

- [x] Headless uses `DaemonSession` lifecycle
- [x] One-shot Typer RPCs share `soothe_client.helpers.protocol1_rpc`
- [x] Skills / model config avoid duplicate connect boilerplate
- [x] Existing headless / loop RPC unit tests updated and green
- [x] No new `soothe.*` (core) imports in CLI

**Status**: Done (2026-07-16)
