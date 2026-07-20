# IG-565: Daemon Legacy and Dead Code Cleanup

## Status

Completed

## Goal

Remove confirmed dead legacy code from `soothe-daemon`: TCP line-protocol transport, unused client→checkpoint mappings, and the deprecated `_query_running` flag. Simplify router handshake logic and trim stale legacy comments in hot paths.

## Removed

| Item | Reason |
|------|--------|
| `_ClientConn`, `_handle_client`, `_send`, `_clients`, `_server` (core/handlers) | Legacy line-protocol TCP transport; production uses WebSocket only (IG-102) |
| Router `_lookup_client_conn` / `legacy:` client ids | Only served removed TCP path |
| `ThreadStateRegistry.set_client_thread` / `get_client_thread` / `_client_active_thread` | Zero production writers |
| `_query_running` | Deprecated duplicate of `_active_threads`; replaced by `_has_active_queries()` |

## Retained (operational, not dead)

| Item | Reason |
|------|--------|
| Legacy flat→envelope rejection in router | Active migration guard for protocol-1 clients |
| `write_legacy_assistant_row` in query engine | Fallback when phase-tagged rows absent |
| `DEPRECATED_LOOP_AUTOPILOT_MODE` wire field | Clients still expect `autopilot_mode` on subscribe |
| Session legacy→`next` frame translation | RFC-450 protocol-1 requirement |
| Ray runner modules | Optional distributed mode (RFC-221) |
| `response_bridge._pending_slots` legacy export | Tests patch it |

## Verification

`./scripts/verify_finally.sh`
