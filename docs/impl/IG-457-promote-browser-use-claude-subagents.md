# IG-457: Promote browser_use and claude subagents into soothe core

## Goal
Move the `browser_use` and `claude` subagents from `soothe-plugins` into the core `soothe` package, gated behind opt-in extras so heavy deps are not pulled into the base install.

## Files touched
- New: `packages/soothe/src/soothe/subagents/browser_use/` (moved from `community/src/soothe_plugins/browser_use/`)
- New: `packages/soothe/src/soothe/subagents/claude/` (moved from `community/src/soothe_plugins/claude/`)
- Edit: `packages/soothe/src/soothe/subagents/__init__.py` — import the two events modules so wire types register on package import.
- Edit: `packages/soothe/pyproject.toml` — add `browser_use` / `claude` extras, fold both into `all`, register `[project.entry-points."soothe.plugins"]` for the in-tree plugins.
- Edit: `packages/soothe-daemon/src/soothe_daemon/loop_gc.py` — `soothe_plugins.claude.session_bridge` → `soothe.subagents.claude.session_bridge`.
- Edit: `community/pyproject.toml` — drop `browser-use`, `anthropic`, `claude-agent-sdk`; drop `browser_use` / `claude` from `[project.entry-points."soothe.plugins"]`; drop the matching `[[tool.mypy.overrides]]` modules.
- Edit: `community/tests/integration/test_plugin_loading.py` — remove `browser_use` and `claude` from the expected-plugin lists.
- Moved: `community/tests/unit/subagents/{browser_use,claude,test_browser_claude_subagents.py,test_claude_*.py}` → `packages/soothe/tests/unit/subagents/{browser_use,claude}/`.
- Edit (CHANGELOG): note the move under the `0.5.25` `Changed` section.

## Decisions
- **Form**: kept `@plugin` / `@subagent` decorators with `trust_level="built-in"`. Matches `ExplorePlugin` / `TacitusPlugin`. Loaded through `soothe.plugins` entry points declared in `packages/soothe/pyproject.toml`, so the existing plugin lifecycle (`on_load` dep guards, registry, etc.) keeps working.
- **Deps**: `browser-use>=0.11.0,<0.13.0` and (`anthropic>=0.96.0,<1.0.0`, `claude-agent-sdk>=0.1.0,<1.0.0`) are now opt-in extras (`soothe[browser_use]`, `soothe[claude]`); both are folded into `soothe[all]`. `on_load` raises `PluginError` with the new install hint when the runtime dep is missing; the lifecycle disables the plugin gracefully.
- **Old copies**: deleted from `community/`. Single source of truth in `soothe`. The community `RFC-601-community-agents.md` still documents the historical state — left untouched as a community-side history note.
- **Path helper**: `soothe_plugins._paths.expand_path` → `soothe.utils.path.expand_path` (the helper was a verbatim mirror of that utility).

## Done when
- `./scripts/verify_finally.sh` passes.
- `grep -r soothe_plugins.browser_use\|soothe_plugins.claude packages docs CHANGELOG.md` returns nothing.
- `pip install 'soothe[browser_use]'` and `pip install 'soothe[claude]'` install only the heavy dep for that extra.
