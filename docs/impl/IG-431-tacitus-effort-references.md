# IG-431: Tacitus effort levels and reference bibliography

**Status**: Completed  
**Created**: 2026-05-25  

## Goal

Optimize Tacitus performance via effort levels (`normal`, `high`, `xhigh`) that scale question/query/loop depth. Collect structured references during gather and append a formatted `## References` section to the synthesized report.

## Scope

- `packages/soothe/src/soothe/subagents/tacitus/effort.py` (new)
- `packages/soothe/src/soothe/subagents/tacitus/references.py` (new)
- `protocol.py`, `engine.py`, `implementation.py`, `__init__.py`
- `sources/web_search.py`, `sources/academic.py`
- `config/config.template.yml`, `config/config.dev.yml`
- Unit tests under `packages/soothe/tests/unit/subagents/tacitus/`

## Decisions

- Default effort: **normal** (2 loops, tighter caps).
- Resolution: task text `effort:` → context → YAML → default.
- `context.max_loops` still overrides profile when explicitly set.

## Tasks

- [x] effort profiles + TacitusConfig.effort
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
