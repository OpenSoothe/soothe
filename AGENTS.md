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

### 6. After Code Impl: Cleanse → Verify → Fix (MUST)
After implementing (or changing) code—and before marking work done (commit, PR, or handoff)—you MUST apply this sequence every time:

1. **Cleanse related legacy and dead code** — remove superseded helpers, unused exports, duplicate parallel paths, and stale tests/docs tied to the change. Do **not** change existing functionality while cleansing; cleanup is deletion/consolidation only, not behavior rewrites.
2. **Run verification** — `./scripts/verify_finally.sh`
3. **Fix all errors** — lint, format, tests, vulture; do not stop with a failing verify. Re-cleanse if fixes leave new dead code, then re-run verify until green.

### 7. Terminology
- NEVER use "layer N" — use concrete names (CoreAgent, StrangeLoop, GoalEngine)
- NEVER expose IG-XXX/RFC-XXX in user-facing text (logs, CLI, errors)—internal only
- IG-XXX/RFC-XXX references are allowed ONLY in internal code: docstrings, comments, and internal documentation. They must never appear in runtime strings visible to users.
- Only `docs/specs/` (RFCs) and `docs/impl/` (IGs) are allowed for active reference.
- Archived content in `docs/archive/` (drafts, completed analysis) is for historical reference only.
- When writing log messages, error text, CLI output, config field descriptions, or any user-visible string, omit all IG-/RFC- identifiers.

### 7b. Package-boundary docstring rules (MUST)

`soothe-nano` and `soothe-sdk` are **standalone packages** — they ship
independently (soothe-nano is a separate repo/submodule) and must not reference
parent-workspace documentation or host/daemon concepts. Their docstrings,
comments, and `__init__` package summaries must read as self-contained.

**Rules for `packages/soothe-nano/` and `packages/soothe-sdk/`:**

1. **No IG-XXX / RFC-XXX references** in source (`*.py`), including docstrings
   and comments. These identifiers index into the monorepo's `docs/specs/` and
   `docs/impl/`, which a standalone nano/sdk consumer does not have. Replace
   `(RFC-105)` / `(IG-258 Phase 2)` / `RFC-612 multi-database` style parentheticals
   with a plain-English description of the concept. The only exception is the
   single `__init__.py` package docstring may say "no StrangeLoop/Autopilot" to
   mark the package's scope — but never an IG/RFC number.
2. **No host/daemon concept names** in docstrings or comments: `StrangeLoop`,
   `Autopilot`, `ContextEngine`, `cron`, `intake-only`, `daemon`, `soothed`,
   `routing_classification`, `goal_completion`, `sloop`. Nano does not know
   these concepts. (Mentioning them to say "no StrangeLoop" in the package
   docstring is allowed; using them to describe behavior is not.)
3. **No `soothe.` / `soothe_daemon.` import paths** in docstrings, comments,
   or docstring examples — nano must not reference host/daemon module paths.
   (`TYPE_CHECKING` or runtime `import` of host code is also banned — see §3b.)
4. **Describe behavior, not provenance.** Instead of `IG-517: Batched edit for
   coalescing middleware`, write `Batched edit for coalescing middleware`.
   Instead of `RFC-612 multi-database layout`, write `multi-database PostgreSQL
   layout`. Keep the technical content; drop the tracker identifier.

This rule is enforced structurally: `scripts/check_module_import_boundaries.sh`
rule 3c bans L2/L3 symbol names in nano, and `scripts/check_nano_duplicate_symbols.py`
bans dead-duplicate host symbols in nano. A docstring scanner for IG/RFC refs
is a TODO (PR-10 follow-on); for now, reviewers must enforce by eye.

Host packages (`soothe`, `soothe-daemon`, `soothe-cli`, `soothe-plugins`) MAY
reference IG-XXX/RFC-XXX in docstrings and comments (they live in the monorepo
alongside `docs/`).

### 8. DO NOT Cheat Tests
Fix the implementation, not test expectations. "Passing tests" ≠ "Working correctly"

### 9. No Keyword Heuristics (RFC-630)
Prefer **structured light-LLM fields** or **declarative config rules** over keyword/regex content-judgment heuristics.

- **Content judgment** (intent, identity, routing hints, failure classification): use Pass 1/2 structured output or a dedicated fast-model call — not keyword lists or regex on user text.
- **Structural controls** (e.g. `continue`/`resume`, checkpoint gates, status vocabulary): deterministic rules are fine.
- **Thresholds and banned patterns**: put in config (`agent.loop.rules`, etc.), not magic numbers or inline regex in module bodies.
- **If a keyword/regex heuristic seems required**: stop and ask the user to confirm before implementing. Propose the LLM or config-rules alternative first.

See [IG-567](docs/impl/IG-567-heuristic-to-rules-migration.md) for the StrangeLoop migration pattern.

### 10. Unified Persistence Backend (MUST)
`persistence.default_backend` is **one mode for the whole process**: either `postgresql` or `sqlite`. **Never mix** the two in the same daemon/runtime.

- When `default_backend: postgresql`, **all** durable stores that the daemon owns MUST use PostgreSQL (RFC-612 databases under `postgres_base_dsn` / `postgres_databases`). Do **not** leave cron, identity, display cards, checkpoints, Context Engine, durability/metadata, or autopilot on SQLite “for convenience.”
- When `default_backend: sqlite`, use the local `$SOOTHE_HOME` / `$SOOTHE_DATA_DIR` SQLite files; do **not** open a parallel Postgres path for a subset of features.
- Overrides (`agent.protocols.durability.backend` / `.checkpointer`) MUST stay `"default"` unless the operator intentionally switches the **entire** process; do not set them to the opposite of `default_backend`.
- Vector stores follow the same rule in deploy configs: Postgres mode → `pgvector`; SQLite mode → `sqlite_vec` (or in-memory for tests only).
- New persistence features MUST branch on `persistence.default_backend` (or a shared `configure_*` / factory) — never hard-code SQLite when Postgres is configured.
- Leftover SQLite files under `$SOOTHE_DATA_DIR` in Postgres mode are legacy only; do not write new runtime state to them.

---

## 📁 Structure

```
packages/
├── soothe-sdk/      # Shared contracts submodule (mirasoth/soothe-sdk)
├── soothe-nano/     # Coding CoreAgent submodule (mirasoth/soothe-nano); no StrangeLoop/Autopilot
├── soothe/          # Host composition: StrangeLoop, Autopilot, CE, cron, runner (depends on nano)
├── soothe-daemon/   # Daemon server (soothed); depends on soothe + soothe-nano directly
├── soothe-cli/      # Typer CLI + Textual TUI client (talks to daemon via WebSocket)
└── soothe-plugins/  # Community plugins (depends on soothe-nano, not full soothe)

client/
├── go/              # soothe-client-go
├── typescript/      # @mirasoth/soothe-client
└── python/          # soothe-client-python (WebSocket transport client)
```

**Key docs**: [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for architecture, [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) for plugins.

---

## 🔧 Quick Reference

| What | Where |
|------|-------|
| Nano agent factory | `packages/soothe-nano/src/soothe_nano/agent/factory.py` (`create_nano_agent`) |
| Host agent factory | `packages/soothe/src/soothe/foundation/coreagent/coding/factory.py` (`create_soothe_agent`) |
| Nano config | `packages/soothe-nano/src/soothe_nano/config/settings.py` |
| Host config | `packages/soothe/src/soothe/config/settings.py` |
| Shared protocols | `packages/soothe-sdk/src/soothe_sdk/protocols/` |
| Loop protocols | `packages/soothe/src/soothe/protocols/` |
| RFCs | `docs/specs/` |
| IGs | `docs/impl/` |
| Debug guide | `docs/wiki/howto_debug.md` |
| Archived docs | `docs/archive/` (historical reference only) |

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
3. **Cleanse → Verify → Fix** (Critical Rule 6 — MUST after every code impl): remove related legacy/dead code **without changing existing functionality**, then `./scripts/verify_finally.sh`, then fix until green
4. **GitHub Actions**: Use `GITHUB_PAT` env var; `export GH_TOKEN="$GITHUB_PAT"` for `gh` CLI

---

## 🆘 Help

- Architecture → `docs/specs/RFC-*.md`
- Patterns → `docs/impl/IG-*.md`
- APIs → `thirdparty/` (reference only, don't import)
- Debug → `docs/wiki/howto_debug.md`
- Config → `config/config.template.yml`