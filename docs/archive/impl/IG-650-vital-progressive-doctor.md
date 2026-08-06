# IG-650 Vital Progressive `soothed doctor`

## Goal

Redesign `soothed doctor` to focus on vitals required for a working soothed
process, with progressive diagnosis output as each category completes.

## Scope

- Default vitals: `configuration`, `tool_deps`, `persistence`, `providers`,
  `observability`, `host`, `daemon`
- New `tool_deps`: `rg`, `fd` (via nano filesystem helpers / `soothe_nano.diagnose`)
- Persistence gated on `persistence.default_backend`
- Providers: only configured entries; live invoke opt-in (`--live-llm`)
- Langfuse: live health when enabled
- Progressive text UX; json/markdown remain batch
- `--deep` adds vector_stores, protocols, models, mcp_servers, external_apis
- Package APIs: see [IG-651](IG-651-package-diagnose-apis.md)

## Non-goals

- Changing daemon runtime health endpoints
- Keyword heuristics for content judgment

## Validation

- Unit tests for tool_deps, persistence gating, providers, progressive printer
- `./scripts/verify_finally.sh`
