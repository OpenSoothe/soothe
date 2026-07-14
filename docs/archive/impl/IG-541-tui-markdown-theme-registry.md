# IG-541: TUI Markdown Theme Registry

## Summary

Introduce named markdown appearance presets for TUI Rich rendering, CLI
configuration, and unified styling across assistant and skill markdown surfaces.

## Scope

- `soothe_cli/tui/markdown_theme.py` — registry, recipes, `build_markdown()`
- CLI `--markdown-theme` + `CLIConfig.markdown_theme`
- TUI preferences: `ui.markdown_theme` in `~/SOOTHE_HOME/config/config.yml` (CLI client only; not daemon repo config)
- Wire `AssistantMessage` and `SkillMessage` to `build_markdown()`
- RFC-500 § Markdown rendering (TUI)
- Remove ad-hoc `_CODE_THEME_MAP` / goal-completion-only boolean flags

## Presets (v1)

| ID | Label |
|----|-------|
| `match-app` | Match App Theme (default) |
| `langchain` | LangChain |
| `langchain-light` | LangChain Light |
| `standard` | Standard |
| `minimal` | Minimal |

## Status

Implemented.

## Verification

```bash
./scripts/verify_finally.sh
```

Key tests:

- `packages/soothe-cli/tests/unit/ux/tui/test_markdown_theme.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_assistant_message_markdown.py`
- `packages/soothe-cli/tests/unit/config/test_cli_config_loader.py`

## Related

- Design draft: `docs/archive/drafts/2026-07-02-tui-markdown-theme-design.md`
- RFC-500 § Markdown rendering (TUI)
