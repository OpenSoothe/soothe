# IG-617: TypeScript Client Production Parity

**Guide**: IG-617  
**Title**: Bring `@mirasoth/soothe-client` to Go/Python production parity  
**Status**: Complete  
**Related**: RFC-629, IG-608 (Go appkit lifecycle), IG-615 (stale turn-end peel), SIL-04  

---

## Scope

`client/typescript/` only — no desktop/CLI rewiring, no npm publish in this guide.

| Phase | Deliverable |
|-------|-------------|
| A | TurnRunner idle/soft-complete/attachments + Classifier `treatStatusIdleAsComplete` |
| B | `stream_terminal`, `DaemonSession`, chunk_filter / unwrap_next / TurnEventStats |
| C | Helpers (`connectedWebsocket`, `protocol1Rpc`), CHANGELOG, README, `0.3.0` |

## Checklist

- [x] Phase A green with Go-mirrored lifecycle tests
- [x] Phase B DaemonSession peel + turn-end tests
- [x] Phase C exports + `0.3.0` docs
- [x] `make verify` in `client/typescript`
