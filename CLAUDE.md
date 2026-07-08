# Soothe Development Guide

> Goal-driven orchestration framework for 24/7 autonomous agents. Extends deepagents with planning, durability, and remote agent interop.

---

## ⚠️ CRITICAL RULES

### 1. Implementation Guides (IGs)
- **Substantial work**: Create IG in `docs/impl/` (`IG-XXX-brief-title.md`) to track scope
- **Minor changes**: No verbose IG—use commit/PR context, or minimal stub only

### 2. Config Sync
When editing `config/config.template.yml`, MUST also update `config/develop/config.yml` with matching structure.

### 3. Ecosystem First
Check `langchain-core`, `langchain-community`, `deepagents` before implementing anything:
- Tools: `BaseTool`, `@tool`
- Subagents: `SubAgent`, `CompiledSubAgent`
- MCP: `langchain-mcp-adapters`
- Memory: `deepagents.MemoryMiddleware`

### 4. Test Location
Tests go in package directories: `packages/<pkg>/tests/unit/` or `tests/integration/` — NOT root `tests/`.

### 5. Verification Required
Run `./scripts/verify_finally.sh` before ANY commit. Zero lint errors, all tests pass.

### 6. Finish Work: Clean Up, Verify, Fix
Before marking work done (commit, PR, or handoff), you MUST:

1. **Remove related legacy and dead code** — delete superseded helpers, unused exports, stale tests/docs tied to the change; do not leave parallel old paths.
2. **Run verification** — `./scripts/verify_finally.sh`
3. **Fix all errors** — lint, format, tests, vulture; do not stop with a failing verify

### 7. Terminology
- NEVER use "layer N" — use concrete names (CoreAgent, StrangeLoop, GoalEngine)
- NEVER expose IG-XXX/RFC-XXX in user-facing text (logs, CLI, errors)—internal only
- IG-XXX/RFC-XXX references are allowed ONLY in internal code: docstrings, comments, and internal documentation. They must never appear in runtime strings visible to users.
- DO NOT refer to docs/draft in the codebase. Only docs/specs/ (RFCs) and docs/impl/ (IGs) are allowed for reference.
- When writing log messages, error text, CLI output, config field descriptions, or any user-visible string, omit all IG-/RFC- identifiers.

### 8. DO NOT Cheat Tests
Fix the implementation, not test expectations. "Passing tests" ≠ "Working correctly"

### 9. No Keyword Heuristics (RFC-630)
Prefer **structured light-LLM fields** or **declarative config rules** over keyword/regex content-judgment heuristics.

- **Content judgment** (intent, identity, routing hints, failure classification): use Pass 1/2 structured output or a dedicated fast-model call — not keyword lists or regex on user text.
- **Structural controls** (e.g. `continue`/`resume`, checkpoint gates, status vocabulary): deterministic rules are fine.
- **Thresholds and banned patterns**: put in config (`agent.loop.rules`, etc.), not magic numbers or inline regex in module bodies.
- **If a keyword/regex heuristic seems required**: stop and ask the user to confirm before implementing. Propose the LLM or config-rules alternative first.

See [IG-567](docs/impl/IG-567-heuristic-to-rules-migration.md) for the StrangeLoop migration pattern.

---

## 📁 Structure

```
packages/
├── soothe/          # Core framework: GoalEngine/StrangeLoop/CoreAgent, protocols, backends, middleware
├── soothe-daemon/   # Daemon server (soothed): WebSocket/HTTP transports, event bus, client sessions
├── soothe-cli/      # Typer CLI + Textual TUI client (talks to daemon via WebSocket)
├── soothe-sdk/      # WebSocket client, protocol params, plugin decorators (@plugin/@tool/@subagent)
└── soothe-plugins/  # Community plugins (delegated subagents)
```

**Key docs**: [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for architecture, [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) for plugins.

---

## 🔧 Quick Reference

| What | Where |
|------|-------|
| Agent factory | `packages/soothe/src/soothe/foundation/core/agent/_builder.py` |
| Config | `packages/soothe/src/soothe/config/settings.py` |
| Protocols | `packages/soothe/src/soothe/protocols/` |
| RFCs | `docs/specs/` |
| IGs | `docs/impl/` |
| Debug guide | `docs/wiki/howto_debug.md` |

---

## 🔌 Plugin System

```python
from soothe_sdk.plugin import plugin, tool, subagent
from soothe.core.event_catalog import register_event

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool", description="...")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"

# Register custom events at module load
register_event(MyCustomEvent, summary_template="Custom: {data}")
```

---

## 🎨 Code Style

- Python ≥3.11, type hints on public functions
- Google-style docstrings (Args, Returns, Raises)
- Ruff for linting/formatting, no bare `except:`
- Single backticks in docstrings: `create_agent()` not ``create_agent()``

---

## 🛠️ What NOT to Implement

deepagents provides: file ops, shell, task tracking, SubAgent, Skills, Memory, Summarization middleware.

langchain provides: web search (Tavily, DuckDuckGo), ArXiv, Wikipedia, GitHub, Gmail, document loaders, `init_chat_model()`.

**Check these first.**

---

## 🚦 Workflow

1. **Plan**: Explore codebase → ask when alternatives exist → ExitPlanMode for approval
2. **Implement**: Read existing → check ecosystem → follow patterns → run `make lint`
3. **Clean up**: Remove related legacy/dead code from the change (see Critical Rule 6)
4. **Verify**: `./scripts/verify_finally.sh` — must pass; fix all errors before commit
5. **GitHub Actions**: Use `GITHUB_PAT` env var; `export GH_TOKEN="$GITHUB_PAT"` for `gh` CLI

---

## 🆘 Help

- Architecture → `docs/specs/RFC-*.md`
- Patterns → `docs/impl/IG-*.md`
- APIs → `thirdparty/` (reference only, don't import)
- Debug → `docs/wiki/howto_debug.md`
- Config → `config/config.template.yml`