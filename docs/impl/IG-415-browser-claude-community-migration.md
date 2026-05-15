# IG-415: Migrate Browser and Claude Subagents to soothe-community

**Status**: Implemented  
**Created**: 2026-05-15  
**Depends on**: RFC-600 (plugin system), RFC-601 split (community agents)

## Goal

Move the **Browser** (browser-use) and **Claude** (Claude Code / claude-agent-sdk) subagents out of the core `soothe` package into **`soothe-community`**, validate the RFC-600 self-contained plugin pattern, and remove core defaults and discovery entries so the orchestrator no longer implies those agents exist without the optional distribution.

## Motivation

- **Lean core**: Heavy optional stacks (Playwright/browser-use, Claude agent SDK) should not ship inside the main framework wheel.
- **Single extension path**: Community plugins already use `@plugin` / `@subagent` + `soothe.plugins` entry points; browser and claude already followed that pattern in-tree—finishing the move makes them indistinguishable from other community plugins.
- **Clear install story**: `pip install soothe-community[browser]` / `[claude]` documents capability boundaries.

## Non-goals

- Renaming curated wire event strings (`soothe.subagent.browser.*`, `soothe.subagent.claude.*`) — they remain in `soothe-sdk` for client stability.
- Removing the word “browser” from unrelated areas (e.g. research `BrowserSource`, Anthropic model ids, `webbrowser` stdlib).
- Splitting research’s optional `browser-use` modality out of core `soothe[websearch]` (still used by research sources).

## Design decisions

1. **Entry points**: `browser = "soothe_community.browser:BrowserPlugin"` and `claude = "soothe_community.claude:ClaudePlugin"` register those names like any other plugin (same manifest keys as before the split).
2. **Optional dependency on `soothe`**: Browser/claude implementations still call `soothe.utils.runtime`, `soothe.utils.browser_cdp`, `soothe.core.FrameworkFilesystem` integration, etc. Re-implementing all of that inside community would duplicate IG-405 virtual-home logic. Therefore `soothe-community[browser]` and `[claude]` declare **`soothe>=0.1.0`** as a co-extra (monorepo uses editable installs in CI).
3. **`BrowserSubagentConfig`**: Moved to `soothe_community.browser.config_model` — core `SootheConfig` no longer exports it.
4. **Wire emission in SDK**: Added `emit_subagent_wire_event` to `soothe_sdk.core.subagent_wire` so community graphs can emit allowlisted events without importing `soothe.utils.subagent_emit`. Core `soothe.utils.subagent_emit` still wraps `emit_progress` for step context parity.
5. **Daemon loop cleanup**: `message_router` uses try-import `soothe_community.claude.session_bridge.cleanup_claude_sessions` so core does not import the package path at module load time.

## Implementation checklist

- [x] Copy `packages/soothe/src/soothe/subagents/{browser,claude}/` → `community/src/soothe_community/{browser,claude}/` and fix imports.
- [x] `community/pyproject.toml`: entry points + `[browser]` / `[claude]` optional extras.
- [x] `plugin/discovery.py`: built-in subagent list = `explore`, `plan`, `research` only.
- [x] `core/resolver/_resolver_tools.py`: drop factories and browser-specific kwargs; keep `model_override = None` for `claude`.
- [x] `config/settings.py`: default `_merge_subagents` without browser/claude.
- [x] `config/models.py` + `config/__init__.py`: remove `BrowserSubagentConfig`.
- [x] `config/config.template.yml`: remove browser/claude blocks; document community in header.
- [x] Tests: move unit tests under `community/tests/unit/subagents/`; add `importorskip("soothe")` where runtime hooks required.
- [x] Delete empty `packages/soothe/src/soothe/subagents/{browser,claude}/`.
- [x] Examples + wiki + RFC cross-links + analysis inventory.
- [x] `packages/soothe/pyproject.toml`: remove `claude` extra; keep `websearch` (research).

## Verification

Run from repo root:

```bash
./scripts/verify_finally.sh
```

## Follow-ups (optional)

- Long-term: move `soothe.utils.runtime` browser helpers behind a small protocol in `soothe-sdk` so community browser can drop the direct `soothe` dependency.
- Consider deduplicating `emit_subagent_wire_event` vs `emit_progress` step injection in one place.

## Files touched (summary)

| Area | Path |
|------|------|
| Community plugins | `community/src/soothe_community/browser/`, `.../claude/`, `community/pyproject.toml` |
| Core discovery/resolver/config | `packages/soothe/src/soothe/plugin/discovery.py`, `.../resolver/_resolver_tools.py`, `.../config/*`, `config/config.template.yml` |
| SDK | `packages/soothe-sdk/src/soothe_sdk/core/subagent_wire.py` |
| Daemon | `packages/soothe-daemon/.../message_router.py` |
| Docs | `docs/specs/RFC-601-built-in-agents.md`, `RFC-403`, `docs/wiki/subagents.md`, `community/docs/RFC-601-community-agents.md`, `docs/analysis/subagents-inventory-soothe-and-deepagents.md` |
| IG | `docs/impl/IG-415-browser-claude-community-migration.md` |
