# IG-017: Progress Events and Tools Polish

## Objective

Polish Soothe's progress events, logging, and tool ecosystem for production
readiness. Standardise subagent event naming, unify emission patterns,
consolidate rendering helpers, suppress third-party log noise, and provide
a set of out-of-box default tools that work without API keys.

## Scope

1. **Event naming**: Rename all subagent event types to `soothe.<subagent>.<action>`.
2. **Event emission**: Migrate Browser and Claude subagents to `emit_progress()`.
3. **Verbosity classification**: Teach `classify_custom_event()` to distinguish
   subagent events from protocol events within the `soothe.*` namespace.
4. **Rendering consolidation**: Merge duplicate headless / TUI helpers into
   `tui_shared.py` as single source of truth.
5. **TUI / headless updates**: Update `_handle_subagent_custom()` and
   `_render_progress_event()` for new event names.
6. **Third-party logger suppression**: Centralise noisy logger muting in
   `setup_logging()`.
7. **Session logger tagging**: Add `classification` field to custom event records.
8. **Datetime tool**: New `current_datetime` tool for time-awareness.
9. **Search tool consolidation**: Remove `tavily` / `duckduckgo` tool groups;
   wizsearch becomes the single search tool with multi-engine defaults.
10. **Default tools**: Out-of-box `["datetime", "arxiv", "wikipedia", "wizsearch"]`.
11. **Dependency cleanup**: Move `langchain-tavily` from core to optional deps.
12. **Spec update**: Align RFC-500 and AGENTS.md with changes.
13. **Tests**: Update verbosity, tools, and config test suites.

## References

- [RFC-500](../specs/RFC-500-cli-tui-architecture.md) — CLI TUI Architecture Design
- [RFC-000](../specs/RFC-000-system-conceptual-design.md) — System Conceptual Design

## Design Decisions

### Event naming convention

All subagent custom events follow `soothe.<subagent>.<action>`:

| Before | After |
|--------|-------|
| `research_generate_query` | `soothe.research.generate_query` |
| `research_web_search` | `soothe.research.web_search` |
| `browser_step` | `soothe.browser.step` |
| `claude_text` | `soothe.claude.text` |
| `claude_tool_use` | `soothe.claude.tool_use` |
| `claude_result` | `soothe.claude.result` |

Skillify (`soothe.skillify.*`) and Weaver (`soothe.weaver.*`) already follow
this convention. Protocol events (`soothe.plan.*`, `soothe.policy.*`, etc.)
remain unchanged.

### Verbosity classification

`classify_custom_event()` uses an explicit `_SUBAGENT_PREFIXES` frozenset to
distinguish `subagent_custom` from `protocol` within the `soothe.*` namespace.
At "normal" verbosity, protocol events display but subagent events do not.

### Default tools

The default tool set provides out-of-box utility without requiring API keys
for basic operation:

- `datetime` — Current date/time awareness (new, zero-dependency)
- `arxiv` — Academic paper search (langchain_community, no API key)
- `wikipedia` — Encyclopedia lookup (langchain_community, no API key)
- `wizsearch` — Multi-engine web search (graceful degradation if engines unavailable)

## File Changes

### New files

| File | Purpose |
|------|---------|
| `src/soothe/tools/datetime.py` | `CurrentDateTimeTool` + factory |

### Modified files

| File | Change |
|------|--------|
| `src/soothe/subagents/research.py` | Rename event types to `soothe.research.*` |
| `src/soothe/subagents/browser.py` | Use `emit_progress()`, rename to `soothe.browser.step` |
| `src/soothe/subagents/claude.py` | Use `emit_progress()`, rename to `soothe.claude.*` |
| `src/soothe/cli/progress_verbosity.py` | Add `_SUBAGENT_PREFIXES`, update classifier |
| `src/soothe/cli/tui_shared.py` | Update `_handle_subagent_custom()` for new names |
| `src/soothe/cli/main.py` | Consolidate helpers, suppress loggers, fix idioms |
| `src/soothe/cli/thread_logger.py` | Add `classification` field to event records |
| `src/soothe/core/resolver.py` | Remove tavily/duckduckgo, add datetime group |
| `src/soothe/tools/wizsearch.py` | Update default engines |
| `src/soothe/config.py` | Default tools list |
| `config/config.yml` | Update tools section |
| `pyproject.toml` | Move langchain-tavily to optional |
| `docs/specs/RFC-500-cli-tui-architecture.md` | Align event names and logging docs |
| `AGENTS.md` | Add IG-017 to table |
| `tests/unit_tests/test_progress_verbosity.py` | Update event classification tests |
| `tests/unit_tests/test_tools.py` | Add datetime tool tests, update wizsearch defaults |
| `tests/unit_tests/test_config.py` | Update default tools assertion |

## Checklist

- [ ] Subagent event naming standardised
- [ ] Browser and Claude use `emit_progress()`
- [ ] `classify_custom_event()` subagent-aware
- [ ] Rendering helpers consolidated in `tui_shared.py`
- [ ] TUI and headless renderers updated
- [ ] Third-party logger suppression centralised
- [ ] Session logger adds `classification` field
- [ ] `CurrentDateTimeTool` created and wired
- [ ] Tavily/DuckDuckGo tool groups removed from resolver
- [ ] Wizsearch default engines updated
- [ ] Default tools set in config
- [ ] `langchain-tavily` moved to optional deps
- [ ] RFC-500 updated
- [ ] Tests passing
