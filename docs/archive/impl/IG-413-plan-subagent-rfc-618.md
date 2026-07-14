# IG-413: Plan subagent (RFC-618)

**Status**: Completed  
**RFC**: RFC-618  
**Created**: 2026-05-11

## Goal

Implement the built-in plan subagent per RFC-618: LangGraph delegate with **agentic collection** (multi-round, multi–explore-task batches via direct explore runnable invokes) and **agentic plan design** loops, then a single delegate final.

## Scope

- `packages/soothe/src/soothe/subagents/plan/` — schemas, engine, implementation, plugin `__init__.py`
- Resolver, discovery, defaults (`settings.py`), reflection list, system prompt line
- `config/config.template.yml` — `plan` subagent block
- Unit tests under `packages/soothe/tests/unit/subagents/plan/`

## Done when

- `./scripts/verify_finally.sh` passes
- RFC-618 and index/history updated
