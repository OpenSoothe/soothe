# IG-663: Rust Client (soothe-client)

**Guide**: IG-663  
**Title**: Implement `soothe-client` Rust crate with RFC-629 API parity  
**Created**: 2026-07-17  
**Status**: In progress  
**Related**: RFC-629, RFC-450, IG-662 (cross-client API parity)

---

## Goal

Ship `client/rust` (`soothe-client` on crates.io, lib `soothe_client`) matching
Python 0.10.x / RFC-629 tiers:

| Need | Entry point |
|------|-------------|
| One conversation, stream | `appkit::DaemonSession` |
| Jobs / cron one-shots | `CommandClient` |
| Raw protocol / custom | `Client` |
| Multi-user HTTP backend | `ConnectionPool` + `TurnRunner` |

## Acceptance

- [x] Protocol-1 handshake, mux, `delivery_ack`, heartbeat
- [x] `CommandClient` job/cron/autopilot method set (Python fullness)
- [x] `DaemonSession` dual-socket turn streaming
- [x] Pool + `TurnRunner` + `QueryGate` + classifier + store
- [x] Examples 01–06; unit (mock) + live integration tests
- [x] GitHub CI + crates.io release workflow
- [x] Live verify against local daemon

**Status**: Complete (2026-07-17)

## Key paths

- Crate: `client/rust/`
- Spec: `docs/specs/RFC-629-client-appkit-architecture.md`
