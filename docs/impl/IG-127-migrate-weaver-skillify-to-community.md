# IG-127: Migrate Weaver & Skillify to Community (RFC-600)

## Summary
Migrated Weaver and Skillify subagents from `src/soothe/` to `community/src/soothe_community/` as separate RFC-600 plugins. Soothe core is now completely unaware of these agents.

## Changes

### Community (Added)
- `community/src/soothe_community/skillify/` -- Skillify plugin with `SkillifyPlugin` class
- `community/src/soothe_community/weaver/` -- Weaver plugin with `WeaverPlugin` class
- Both use `@plugin` + `@subagent` decorators, following the PaperScout pattern
- Entry points registered in `community/pyproject.toml`
- Weaver depends on Skillify (cross-plugin imports use `soothe_community.skillify.*`)
- Lifecycle management (indexer stop, reuse index close) in `on_unload` hooks

### Core (Removed)
- Deleted `src/soothe/subagents/skillify/` and `src/soothe/subagents/weaver/`
- Removed all references from:
  - `plugin/discovery.py` (built-in list)
  - `core/resolver/_resolver_tools.py` (factories, generated agents, special kwargs)
  - `config/models.py` (SkillifyConfig, WeaverConfig, VectorStoreRouter roles)
  - `config/settings.py` (builtin subagents, config fields)
  - `core/event_catalog.py` (event module imports)
  - `core/runner/__init__.py` (lifecycle cleanup)
  - `ux/shared/subagent_routing.py` (display names)
  - `foundation/slash_commands.py` (commands)
  - `config/prompts.py` (subagent guide)
  - `core/config_driven.py` (skillify_retrieve permission)
  - `core/runner/_runner_steps.py` (system prompt)
  - `cognition/planning/simple.py` (known subagents, hint map)
  - `skills/soothe-checkhealth/scripts/check_subagents.py` (health checks)
  - `config/config.yml` and `config.dev.yml` (config sections)
  - `subagents/__init__.py` (re-exports)
- Deleted examples and implementation guide docs

### Example
- `examples/agents/coreagent_community_loading.py` demonstrates loading community plugins

## Verification
- No residual `skillify`/`weaver` references in `src/soothe/`
- Community plugins import cleanly with `soothe_community.*` paths
- All cross-plugin imports updated from `soothe.subagents.*` to `soothe_community.*`
