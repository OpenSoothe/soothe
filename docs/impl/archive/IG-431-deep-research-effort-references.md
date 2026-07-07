# IG-431: Deep Research effort levels and reference bibliography

**Status**: Completed  
**Created**: 2026-05-25  

## Goal

Optimize Deep Research performance via effort levels (`normal`, `high`, `xhigh`) that scale question/query/loop depth. Collect structured references during gather and append a formatted `## References` section to the synthesized report.

## Scope

- `packages/soothe/src/soothe/subagents/deep_research/effort.py` (new)
- `packages/soothe/src/soothe/subagents/deep_research/references.py` (new)
- `protocol.py`, `engine.py`, `implementation.py`, `__init__.py`
- `sources/web_search.py`, `sources/academic.py`
- `config/config.template.yml`, `config/config.dev.yml`
- Unit tests under `packages/soothe/tests/unit/subagents/deep_research/`

## Decisions

- Default effort: **normal** (2 loops, tighter caps).
- Resolution: task text `effort:` → context → YAML → default.
- `context.max_loops` still overrides profile when explicitly set.

## Tasks

- [x] effort profiles + Deep ResearchConfig.effort
- [x] Engine caps, prompts, synthesize append
- [x] ResearchReference + gather collection + web URL capture
- [x] Config sync + wiki + tests
- [x] `./scripts/verify_finally.sh`

## Files

| File | Change |
|------|--------|
| `effort.py` | Profiles, parser, resolver |
| `references.py` | Merge, format section |
| `engine.py` | State, caps, append refs |
| `web_search.py` | Structured wizsearch URLs |
