# IG-619: Cross-Client API Parity (Python Reference)

**Guide**: IG-619  
**Title**: Align Go and TypeScript clients with Python production API semantics  
**Created**: 2026-07-17  
**Status**: Phase A–D complete  
**Related**: RFC-629 (updated), RFC-450, IG-612 (Python extract), IG-617 (TS parity), IG-608 (Go appkit lifecycle)

---

## Goal

Treat `soothe-client-python` **0.10.x** as the reference for user-facing API tiers,
constrained public exposure, turn-session semantics, and production transport
behaviors. Bring `client/go` and `client/typescript` to the same contract.

```
Need                         → Entry point (all languages)
─────────────────────────────────────────────────────────
One conversation, stream     → appkit.DaemonSession
Jobs / cron one-shots        → CommandClient (ephemeral RPC)
Raw protocol / custom        → WebSocketClient / Client
Multi-user HTTP backend      → ConnectionPool + TurnRunner
```

## Non-goals

- Browser port of the TypeScript client
- Auth dial headers / TLS client certs (out of band; same as Python)
- Automatic mid-session reconnect loops (apps still call `EnsureConnected` / listen for disconnect)
- Full typed job result structs in Go (maps remain OK this guide)

## Phases

### Phase A — Spec + vocabulary

- [x] Update RFC-629: Python as third language; API tiers; `DaemonSession`; `CommandClient`; `delivery_ack`
- [x] Update `rfc-namings.md` client terms
- [x] This IG

### Phase B — Go user API + correctness (P0)

- [x] `appkit.DaemonSession` (dual-socket, `SendTurn`, `IterTurnChunks`, `EnsureConnected`)
- [x] Layer-0 helpers: `stream_terminal`, peel-stale, `ReadEventWithTimeout`, `Notify`
- [x] `delivery_ack` on terminal stream frames (parity with Python)
- [x] Fix job blocking helpers (single `RequestResponse`; no double-send)
- [x] `CommandClient` for ephemeral job/cron/autopilot RPCs
- [x] Unit tests for DaemonSession turn-end + job single-RPC
- [x] Full `autopilot_*` WebSocket RPCs on `Client` + `CommandClient` (parity with Python)

### Phase C — TypeScript productization (P0/P1)

- [x] Wire `delivery_ack` on terminal frames (capability already declared)
- [x] `CommandClient` ephemeral RPC (jobs/cron/autopilot)
- [x] Slim root exports toward Python tiers (keep advanced via explicit imports / submodules)
- [x] Public-API contract test (allowlist / denylist)
- [x] Align handshake `CLIENT_VERSION` with package version
- [x] Full `autopilot_*` WebSocket RPCs on `Client` + `CommandClient` (parity with Python)

### Phase D — Shared production transport (P2, follow-up OK)

- [x] Priority-aware inbound backpressure (Python 20k queue model) — Go + TS
- [x] Stream-degraded callback + drop counters on Go/TS Client
- [x] Pool idle / health knobs: `MaxIdleTime` enforced on Acquire (all three); `HealthCheckInterval` reserved
- [x] Progressive examples `01`–`06` on Go/TS mirroring Python

**Status**: Phase A–D complete

## Acceptance

| Check | Criterion |
|-------|-----------|
| API tiers | README of each client documents the same four entry points |
| DaemonSession | Go + TS: connect → sendTurn → iterTurnChunks until idle/stream.end |
| CommandClient | Go + TS: `JobCreate` one request envelope; no second send |
| delivery_ack | Terminal stream frames trigger `delivery_ack` notification |
| Public surface | TS root export test excludes demoted internals (Python-style) |
| Verify | `go test ./...` in `client/go`; `npm test` in `client/typescript` |

## Key files

| Area | Paths |
|------|-------|
| Spec | `docs/specs/RFC-629-client-appkit-architecture.md` |
| Go session | `client/go/appkit/daemon_session.go`, `stream_terminal.go` |
| Go jobs | `client/go/job.go`, `client/go/command_client.go` |
| Go ack | `client/go/client.go` (delivery ack tracking) |
| TS ack / cmd | `client/typescript/src/client.ts`, `command_client.ts` |
| TS exports | `client/typescript/src/index.ts`, `test/public_api.test.ts` |
| Backpressure | `client/go/inbound_priority.go`, `client/typescript/src/inbound_priority.ts` |
| Progressive examples | `client/go/examples/progressive/`, `client/typescript/examples/progressive/` |

## Out of scope follow-ups

- IG-608 remaining airway thin-down (product Layer 2)
- Desktop rewire to new TS export tiers (IG-607 successor)

---

*Derived from cross-client gap analysis (2026-07-17); Python `soothe-client` 0.10.0 is the reference.*
