# IG-656: Protocol-1 autopilot_* request RPCs

**Guide**: IG-656  
**Title**: Register `autopilot_*` as protocol-1 request methods for CLI / AsyncCommandClient  
**Created**: 2026-07-16  
**Related**: IG-655, RFC-450, RFC-228  
**Status**: implemented (2026-07-16) — restart running `soothed` to activate handlers

---

## Goal

`AsyncCommandClient` / `soothe autopilot` send protocol-1 `request` envelopes with
methods like `autopilot_status`. Envelope-only daemons rejected these as unknown
methods (legacy path was flat `type=command`, which validation also rejects).

## Scope

1. Shared `run_autopilot_action` used by WebSocket channel + MessageRouter.
2. PARAMS_REGISTRY entries + `_handle_autopilot_*` router methods.
3. CLI polish: import `ProtocolError` from `soothe_client`; pin `>=0.9.5`.

## Exit

- [x] Shared dispatch + registry + router handlers
- [x] Daemon unit tests for registry + dispatch smoke
- [x] CLI `ProtocolError` from `soothe_client`; pins `soothe-client-python>=0.9.5`
- [x] Client integration asserts when daemon is new enough (skips stale process)
- [ ] Live verify after `soothed` restart (`autopilot_status` → result envelope)
- [x] AsyncAPI `docs/specs/asyncapi.yaml` + client `protocol_params` updated (drift check green)
