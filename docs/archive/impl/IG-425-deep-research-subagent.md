# IG-425: Deep Research subagent (RFC-619)

**Status**: Completed  
**RFC**: RFC-619  
**Created**: 2026-05-21  

## Goal

Rename the built-in research subagent to **deep_research**, restrict gather to **public-domain tools**, and replace keyword routing with **semantic capability routing**.

## Scope

### Package

- `packages/soothe/src/soothe/subagents/deep_research/` (renamed from `research`)
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

- `soothe/subagents/deep_research/events.py` — `SUBAGENT_DEEP_RESEARCH_*` (registered via `register_event`)
- `deep_research/events.py` — register deep_research events
- `soothe-cli` — `/deep_research`, display policy

### Integration

- `resolver/_resolver_tools.py`, `plugin/discovery.py`, `config/settings.py`
- `config/config.template.yml`, `config/config.dev.yml`
- `trigger_registry.py` — `DEEP_RESEARCH_RULES`

### Tests

- `packages/soothe/tests/unit/subagents/deep_research/` — update imports and router/source tests
- Remove tests for filesystem/cli/document sources

## Tasks

- [x] RFC-619
- [x] IG-425
- [x] Protocol + Deep ResearchConfig + capability ids
- [x] Public sources + semantic router
- [x] Engine/plugin/events rename
- [x] SDK + CLI + config + resolver
- [x] Unit tests
- [x] `./scripts/verify_finally.sh`

## Done when

- `./scripts/verify_finally.sh` passes
- `task(subagent_type="deep_research")` and `/deep_research` route correctly
- No keyword routing in deep_research router or source gates
