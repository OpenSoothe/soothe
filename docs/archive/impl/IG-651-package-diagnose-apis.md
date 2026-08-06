# IG-651 Package Diagnose APIs for `soothed doctor`

## Goal

Push doctor category checks into package-owned `diagnose()` APIs so
`soothed` only orchestrates process-owned checks and progressive UX.

## Ownership

| Package | Categories |
|---------|------------|
| `soothe-nano` | vital: `tool_deps`, `providers`, `observability`; deep: `mcp_servers`, `vector_stores`, `models`, `protocols` |
| `soothe` | vital: `host` (cron / skillify / autopilot / loop) |
| `soothe-daemon` | vital: `configuration`, `persistence`, `daemon`; deep: `external_apis`; orchestrate |

Packages return dicts matching `CategoryResult.to_dict()`; daemon adapts.

## Non-goals

- Moving health models into `soothe-sdk`
- Changing progressive CLI flags or runtime `/health` endpoints

## Validation

- Unit tests for nano/soothe diagnose + daemon wiring
- `./scripts/verify_finally.sh`
