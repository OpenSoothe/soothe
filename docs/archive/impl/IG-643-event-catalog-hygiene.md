# IG-643: Event Catalog Hygiene

**Guide**: IG-643
**Created**: 2026-07-22
**Related**: IG-637 (registry ownership / dead veritas), `soothe_sdk.core.registry`
**Status**: COMPLETE — `verify_finally.sh` fully green (2026-07-22).

## Context

Shared index: `soothe_sdk.core.registry.REGISTRY`. Hygiene pass after the catalog
audit: register live-but-unregistered emitters, delete dead exported constants,
drop redundant host re-registration of nano primitives.

## Ownership map

| Layer | Owns | Registers into `REGISTRY` |
|-------|------|---------------------------|
| **SDK** | Bases (`SootheEvent`, …), shared wire string consts, `REGISTRY` / `register_event` | None (contracts only) |
| **Nano** | Protocol primitives (stream end, LLM retry, memory, policy, `ERROR`) + MCP / skills / plugins / built-in subagents | Yes, at import |
| **Host** | StrangeLoop / goals / autopilot / branch / system / clarification | Yes; must not re-`_reg` nano primitives |
| **Daemon** | Skillify wire events; channel/output models (bus, not catalog) | Skillify only |
| **Plugins** | Community events (e.g. weaver) | **Self-register on plugin load only** |

### Weaver (plugins-only)

Community plugins self-register via `register_event` inside the plugin package.
Core packages (sdk / nano / host / daemon) stay **weaver-blind**: no imports,
constants, catalog side-imports, or core tests that assert weaver registry
entries. Types appear in `REGISTRY` only after the plugin is imported.

### Not in catalog (intentional)

- Host `internal_events` → `internal_bus` (AL ↔ GE ↔ AP)
- Daemon `soothe.channel.*` / `soothe.output.*` → ChannelManager

## Workstreams

- W0 Doc (this file)
- W1 Skillify index ×4 `register_event`
- W2 Weaver self-register (plugins only)
- W3 `ErrorGeneralEvent` + delete dead consts + SDK docstring
- W4 Drop host `_reg` for `STREAM_END` / `MEMORY_*` / `POLICY_*`
- W5 Tests + `verify_finally.sh`

## Acceptance

- Skillify index + `ERROR` resolve via `REGISTRY.get_meta` after normal nano/daemon import
- Weaver types in `REGISTRY` only after importing the plugin package
- Dead consts removed: detached / reattach / anchor / tool / message / iterated
- Host does not double-register nano stream/memory/policy
- `./scripts/verify_finally.sh` green

## Out of scope

- Channel/output into `REGISTRY`
- Merging `internal_events` into client catalog
- Skillify snake-glue renames (IG-637 C-series)
