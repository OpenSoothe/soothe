# Project Reference

> Structure, quick reference, plugin system, and ecosystem reuse guidance.

## Structure

Import/placement rules: see [package-boundaries.md](package-boundaries.md). Do not reverse the DAG.

```
packages/
├── soothe-sdk/        # OWNED — shared contracts (events, wire, display, protocols)
├── soothe/             # OWNED — StrangeLoop, CE, runner
├── soothe-autopilot/   # OWNED — Autopilot, rails, verify, dispatch
├── soothe-daemon/      # OWNED — soothed process, cron
└── soothe-cli/         # OWNED — Typer CLI + Textual TUI

# Submodules (consume only — format/lint/test/release in their own repos):
#   client/{python,go,typescript,rust}
# PyPI-only (not vendored here): soothe-nano, soothe-deepagents
```

Do **not** run monorepo format/lint/test/publish against submodule trees. Bump submodule pins / PyPI floors when consuming new upstream versions; release those packages from their repositories.

**Key docs**: see `docs/specs/` for architecture and plugin extension design.

## Quick Reference

| What | Where |
|------|-------|
| Nano agent factory | `soothe_nano.agent.factory.create_nano_agent` (PyPI `soothe-nano`) |
| Host agent factory | `packages/soothe/src/soothe/coreagent/factory.py` (`create_soothe_agent`) |
| Nano config | `soothe_nano.config.settings` (PyPI `soothe-nano`) |
| Host config | `packages/soothe/src/soothe/config/settings.py` |
| Shared protocols | `packages/soothe-sdk/src/soothe_sdk/protocols/` |
| Loop protocols | `packages/soothe/src/soothe/protocols/` |
| Design docs | `docs/impl/` |
| Debug guide | `docs/wiki/howto_debug.md` |
| Archived docs | `docs/archive/` (historical only) |

## Plugin System

```python
from soothe_sdk.plugin import plugin, tool, subagent
from soothe.events.catalog import register_event

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool", description="...")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"

# Register custom events at module load
register_event(MyCustomEvent, summary_template="Custom: {data}")
```

## What NOT to Implement

**deepagents** provides: file ops, shell, task tracking, SubAgent, Skills, Memory, Summarization middleware.
**langchain** provides: web search (Tavily, DuckDuckGo), ArXiv, Wikipedia, GitHub, Gmail, document loaders, `init_chat_model()`.

**Check these first.**
