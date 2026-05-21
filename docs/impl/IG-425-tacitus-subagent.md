# IG-425: Tacitus subagent (RFC-619)

**Status**: Completed  
**RFC**: RFC-619  
**Created**: 2026-05-21  

## Goal

Rename the built-in research subagent to **tacitus**, restrict gather to **public-domain tools**, and replace keyword routing with **semantic capability routing**.

## Scope

### Package

- `packages/soothe/src/soothe/subagents/tacitus/` (renamed from `research`)
### Sources (public only)

| File | Capability |
|------|------------|
| `sources/web_search.py` | `web_search` |
| `sources/wikipedia.py` | `wikipedia` |
| `sources/academic.py` | `academic_search` |
| `sources/url_crawl.py` | `url_crawl` |

**Remove**: `cli.py`, `filesystem.py`, `document.py`, `_scoring.py`

### Router

- `router.py` — `PublicSemanticRouter` using `soothe.utils.similarity`

### Wire + SDK

- `soothe/subagents/tacitus/events.py` — `SUBAGENT_TACITUS_*` (registered via `register_event`)
- `tacitus/events.py` — register tacitus events
- `soothe-cli` — `/tacitus`, display policy

### Integration

- `resolver/_resolver_tools.py`, `plugin/discovery.py`, `config/settings.py`
- `config/config.template.yml`, `config/config.dev.yml`
- `trigger_registry.py` — `TACITUS_RULES`

### Tests

- `packages/soothe/tests/unit/subagents/tacitus/` — update imports and router/source tests
- Remove tests for filesystem/cli/document sources

## Tasks

- [x] RFC-619
- [x] IG-425
- [x] Protocol + TacitusConfig + capability ids
- [x] Public sources + semantic router
- [x] Engine/plugin/events rename
- [x] SDK + CLI + config + resolver
- [x] Unit tests
- [x] `./scripts/verify_finally.sh`

## Done when

- `./scripts/verify_finally.sh` passes
- `task(subagent_type="tacitus")` and `/tacitus` route correctly
- No keyword routing in tacitus router or source gates
