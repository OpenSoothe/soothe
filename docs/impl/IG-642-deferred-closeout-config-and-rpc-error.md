# IG-642: Deferred Closeout (Config Re-exports + RpcProtocolError)

**Guide**: IG-642
**Created**: 2026-07-22
**Related**: IG-638, IG-641, IG-631/675 (config ownership), `AGENTS.md` §7b
**Status**: COMPLETE — `verify_finally.sh` fully green (2026-07-22).

## Context

IG-641 deferred three items. Post-audit:

| Item | Verdict |
|------|---------|
| Injectable `PostgresPoolRegistry` factory | **Closed by IG-641 PR-B** — no factory work |
| `ProtocolError` dual name | Daemon-only rename → `RpcProtocolError` |
| Config models near-duplicates | Models re-export + `AgentConfig` subclass |

## Progress

### W0 — Registry factory (DONE)

Documented closed in IG-641 status note.

### W1 — RpcProtocolError (DONE)

- Daemon `ProtocolError` → `RpcProtocolError` (source + unit tests)
- SDK `ProtocolError` unchanged; docstring notes daemon server type

### W2 — Config models re-export (DONE)

- Host `config/models.py` ~1300 lines: re-exports ~53 nano symbols
- Host-only overlays retained (~25 classes)
- `AgentConfig(NanoAgentConfig)` with host fields only
- Identity tests replace field-parity tests
- Allowlist shrunk (removed 11 split-config mirror entries)

### W3 — Cleanse (DONE)

- Removed unused `ComplexityThresholds`

## Out of scope (unchanged)

- Merging host/nano `SootheConfig` in `settings.py`
- SDK/client `ProtocolError` rename
- `SharedPostgreSQLPool` consolidation

## Verification

`./scripts/verify_finally.sh` **fully green**.
