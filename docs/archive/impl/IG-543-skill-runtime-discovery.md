# IG-543: Skill Runtime Discovery (RFC-105 P1)

**IG**: 543  
**Title**: Skill Runtime Discovery — Core/Deferred Partition, search_skills, invoke_skill  
**Status**: Complete  
**Created**: 2026-07-03  
**Dependencies**: RFC-105 (Progressive Skill Loading), IG-519 (middleware caching)  
**Design Draft**: [2026-07-03-skill-runtime-discovery-design.md](../archive/drafts/2026-07-03-skill-runtime-discovery-design.md)

---

## Summary

Extend RFC-105 with a unified runtime discovery model:

1. **Core/deferred catalog partition** — turn-0 lists only core skills (built-ins by default).
2. **`search_skills` tool** — model-driven discovery of deferred skills (substring P0).
3. **`invoke_skill` tool** — model loads full SKILL.md body (parity with CLI `/skill:`).
4. **`discover()` registry helper** — single mutation for path, search, and explicit channels.

LoopState snapshot field names are unchanged (`activated_skill_names` = discovered set).

---

## Scope

| In Scope | Out of Scope |
|----------|--------------|
| `partition_core_deferred`, `search_deferred`, `discover` | LoopState field rename |
| `search_skills` + `invoke_skill` tool stubs + middleware handlers | MCP skill integration |
| `core:` frontmatter + `core_skills` config | |
| Skillify vector backend in `search_skills` (P1 follow-on) | |
| Turn-0 intent prefetch from user goal (P2 follow-on) | |
| System prompt hint for deferred skills | |
| Unit tests + config sync | |

---

## Files

| File | Action |
|------|--------|
| `docs/archive/drafts/2026-07-03-skill-runtime-discovery-design.md` | Create |
| `docs/specs/RFC-105-progressive-skill-loading.md` | Update — §Revision 2026-07-03 |
| `docs/impl/IG-543-skill-runtime-discovery.md` | Create — this document |
| `skills/registry.py` | Modify — core/deferred, search, discover |
| `skills/index.py` | Modify — parse `core:` frontmatter |
| `skills/catalog.py` | Modify — expose `core` in metadata parse |
| `skills/discovery_tools.py` | **Create** — `create_search_skills_tool`, `create_invoke_skill_tool` |
| `skills/search.py` | **Create** — unified substring + Skillify semantic search |
| `subagents/skillify/runtime.py` | **Removed** — replaced by `foundation/skillify/service.py` (IG-562) |
| `middleware/skill_activation.py` | Modify — handle search/invoke; path uses `discover` |
| `middleware/system_prompt.py` | Modify — core/deferred in `_compose_skills_block` |
| `foundation/core/agent/_builder.py` | Modify — register discovery tools when enabled |
| `config/models.py` | Modify — `core_skills`, `search_skills_enabled` |
| `config/config.template.yml` | Modify |
| `config/develop/config.yml` | Modify — mirror structure |
| `foundation/sloop/prompts/system_templates.py` | Modify — skill discovery hint |
| `tests/unit/skills/test_skill_registry.py` | Modify — core/deferred + search tests |
| `tests/unit/middleware/test_skill_discovery_middleware.py` | **Create** |
| `tests/unit/middleware/test_system_prompt.py` | Modify if needed |

---

## Implementation Sequence

1. Draft + RFC revision + IG (this file)
2. Registry: `DEFAULT_CORE_SKILL_NAMES`, `partition_core_deferred`, `search_deferred`, `discover`
3. Index/catalog: `core` frontmatter field on `SkillIndexEntry`
4. Config: `core_skills`, `search_skills_enabled`
5. `skills/discovery_tools.py` tool factories
6. `SkillActivationMiddleware`: intercept `search_skills`, `invoke_skill`; return `Command` with state
7. `_compose_skills_block`: core ∪ activated candidates
8. Agent builder: append tools when `search_skills_enabled`
9. System prompt hint
10. Tests + `./scripts/verify_finally.sh`

---

## Detailed Design

### 1. Core tier resolution

```python
DEFAULT_CORE_SKILL_NAMES = frozenset({"weather", "github", "clawhub", "skill-creator"})

def resolve_core_names(config: SootheConfig) -> frozenset[str]:
    cfg = config.progressive_skills.core_skills
    if cfg:
        return frozenset(n.lower() for n in cfg)
    return DEFAULT_CORE_SKILL_NAMES

def is_core(entry: SkillIndexEntry, core_names: frozenset[str]) -> bool:
    if entry.core is False:
        return False
    if entry.name.lower() in core_names:
        return True
    if entry.core is True:
        return True
    if entry.source == "builtin":
        return True
    return False
```

### 2. Middleware tool handlers

**search_skills** — mirror `ProgressiveToolMiddleware._handle_search_tools`:

```python
matches = registry.search_deferred(query, deferred, activated=activation["activated"], limit=limit)
registry.discover(activation, [m.name for m in matches], via="search")
return ToolMessage(...) + Command(update={"skill_activation": snapshot(activation)})
```

**invoke_skill**:

```python
meta = resolve_skill_directory(config, name, workspace)
markdown = read_skill_markdown(meta)
body = build_skill_context_text(meta, markdown)
registry.discover(activation, [name], via="explicit")
registry.mark_invoked(activation, name, body)
```

**Path hook** — replace `mark_activated` with `discover(..., via="path")`.

### 3. State snapshot for Command.update

Add `snapshot_skill_activation(activation) -> dict` in registry (sets only, no transient `just_invoked`).

### 4. Backward compatibility

- Skills without `paths:` that are **not** core become deferred (hidden until search). Built-ins remain core.
- `partition()` kept as alias delegating to core/deferred for existing tests (deprecated).

---

## Verification

```bash
./scripts/verify_finally.sh
pytest packages/soothe/tests/unit/skills/test_skill_registry.py -q
pytest packages/soothe/tests/unit/middleware/test_skill_discovery_middleware.py -q
pytest packages/soothe/tests/unit/skills/test_skill_search.py -q
```

---

## Follow-ons (P1 / P2)

| Item | Implementation |
|------|----------------|
| P1: Skillify vector backend in `search_skills` | `skills/search.py` merges substring + `start_skillify_service()` when `semantic_search_enabled` |
| P2: Turn-0 intent prefetch | `SkillActivationMiddleware.abefore_agent` calls `search_deferred_skills` on first user message; `intent_prefetched` in activation state |

Config (`progressive_skills`): `semantic_search_enabled`, `semantic_search_min_score`, `intent_prefetch_enabled`, `intent_prefetch_top_k`, `intent_prefetch_min_query_chars`.

Manual smoke (continued):

4. Long first user message mentioning a deferred skill → metadata in turn-0 `<AVAILABLE_SKILLS>` without `search_skills`.
5. `search_skills` with semantic enabled → vector-only skills can match when substring misses.

1. Install a user skill without `core:` → not in turn-0 `<AVAILABLE_SKILLS>`.
2. `search_skills("my-skill")` → next hop lists metadata.
3. `invoke_skill("my-skill")` → `<SKILL_CONTEXT>` on following hop.

---

## Related Documents

- [RFC-105: Progressive Skill Loading](../specs/RFC-105-progressive-skill-loading.md)
- [Design Draft](../archive/drafts/2026-07-03-skill-runtime-discovery-design.md)
- [IG-519: Middleware Efficiency](../impl/IG-519-middleware-efficiency-optimization.md)
