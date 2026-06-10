# Soothe Development Guide

> Goal-driven orchestration framework for 24/7 autonomous agents. Extends deepagents with planning, durability, and remote agent interop.

---

## ⚠️ CRITICAL RULES

### 1. Implementation Guides (IGs)
- **Substantial work**: Create IG in `docs/impl/` (`IG-XXX-brief-title.md`) to track scope
- **Minor changes**: No verbose IG—use commit/PR context, or minimal stub only

### 2. Config Sync
When editing `config/config.template.yml`, MUST also update `config/config.dev.yml` with matching structure.

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

### 6. Terminology
- NEVER use "layer N" — use concrete names (CoreAgent, AgentLoop, GoalEngine)
- NEVER expose IG-XXX/RFC-XXX in user-facing text (logs, CLI, errors)—internal only

### 7. DO NOT Cheat Tests
Fix the implementation, not test expectations. "Passing tests" ≠ "Working correctly"

---

## 📁 Structure

```
packages/
├── soothe-sdk/    # WebSocket client, protocol, types
├── soothe-cli/    # Typer CLI + Textual TUI
└── soothe/        # Daemon server (core, protocols, backends, middleware)
```

**Key docs**: [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for architecture, [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) for plugins.

---

## 🔧 Quick Reference

| What | Where |
|------|-------|
| Agent factory | `packages/soothe/src/soothe/foundation/core/agent/_builder.py` |
| Config | `packages/soothe/src/soothe/config/settings.py` |
| Protocols | `packages/soothe/src/soothe/foundation/protocols/` |
| RFCs | `docs/specs/` |
| IGs | `docs/impl/` |
| Debug guide | `docs/howto_debug.md` |

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
3. **Verify**: `./scripts/verify_finally.sh` — must pass before commit
4. **GitHub Actions**: Use `GITHUB_PAT` env var; `export GH_TOKEN="$GITHUB_PAT"` for `gh` CLI

---

## 🆘 Help

- Architecture → `docs/specs/RFC-*.md`
- Patterns → `docs/impl/IG-*.md`
- APIs → `thirdparty/` (reference only, don't import)
- Debug → `docs/howto_debug.md`
- Config → `config/config.template.yml`