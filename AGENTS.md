# Soothe Development Guide

> Goal-driven orchestration framework for 24/7 autonomous agents. Extends deepagents with planning, durability, and remote agent interop.

---

## ⚠️ CRITICAL RULES

### 1. Implementation Guides (IGs)
- **Substantial work**: Create IG in `docs/impl/` (`IG-XXX-brief-title.md`) to track scope
- **Minor changes**: No verbose IG—use commit/PR context, or minimal stub only

### 2. Config Sync
When editing `config/nano.template.yml`, MUST also update `config/develop/nano.yml` with matching structure.
When editing any `config/*.template.yml`, also sync the packaged copies under
`packages/soothe-daemon/src/soothe_daemon/setup/templates/` (used by `soothed setup`).

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

### 7b. Package Boundaries (MUST)

Soothe is a **one-way dependency DAG**. Before adding code, imports, or types,
place them in the correct **monorepo-owned** package. **Never reverse an arrow.**
Enforcement for owned packages: `scripts/check_module_import_boundaries.sh`
(wired into `./scripts/verify_finally.sh`).

**This monorepo owns** `soothe`, `soothe-daemon`, and `soothe-cli` only.
Submodules (`soothe-sdk`, `soothe-nano`, `client/*`, desktop) are **consumed as
code** — do **not** format, lint, test, or release them from this repo. Maintain
those packages in their own repositories.

#### Dependency DAG (allowed direction only)

```text
soothe-sdk            ← shared contracts (submodule; leaf)
soothe-deepagents     ← deepagents fork (PyPI; leaf)
        ↓
soothe-nano           ← Coding CoreAgent (submodule)
        ↓
soothe                ← host: StrangeLoop, Autopilot, CE, cron, runner   ← OWNED
        ↓
soothe-daemon         ← soothed process                                 ← OWNED
        ↑
soothe-client-python  ← WebSocket transport (submodule)
        ↑
soothe-cli            ← Typer + Textual TUI                             ← OWNED
```

#### Placement (where new code goes)

| Concern | Package |
|---------|---------|
| Shared events, wire, display, plugin contracts, protocols | `soothe-sdk` (external submodule) |
| Coding CoreAgent, skills/MCP/backends used in-proc | `soothe-nano` (external submodule) |
| StrangeLoop, Autopilot, Context Engine, cron, identity, host runner | `soothe` |
| Process lifecycle, channels, HTTP/WS server, admin IO | `soothe-daemon` |
| Human CLI / TUI | `soothe-cli` |
| Language WS clients | `client/*` (external submodules) |

#### Import allow / deny (MUST) — monorepo-owned packages

| Package | May import | Must NOT import |
|---------|------------|-----------------|
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_daemon`, `soothe_cli` |
| `soothe-daemon` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket, not Python imports) |

Additional hard bans (owned packages):

1. **CLI sits above the daemon** — `soothe_cli` must not import daemon/host; communicate via wire contracts in sdk + `soothe-client-python`.
2. **Daemon does not depend on the WS client** — `soothe_daemon` must not import `soothe_client` in runtime source; admin RPCs use `soothe_sdk.wire` (tests may use the client via the `dev` extra).
3. **Private nano middleware is closed** — owned packages must not import `soothe_nano.middleware._*`.

Host packages (`soothe`, `soothe-daemon`, `soothe-cli`) MAY reference
IG-XXX/RFC-XXX in docstrings and comments (they live beside `docs/`).


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

Import/placement rules: **§7b Package Boundaries (MUST)**. Do not reverse the DAG.

```
packages/
├── soothe/             # OWNED — StrangeLoop, Autopilot, CE, cron, runner
├── soothe-daemon/      # OWNED — soothed process
└── soothe-cli/         # OWNED — Typer CLI + Textual TUI

# Submodules (consume only — format/lint/test/release in their own repos):
#   packages/soothe-sdk      mirasoth/soothe-sdk
#   packages/soothe-nano     mirasoth/soothe-nano
#   client/{python,go,typescript,rust}
#   apps/soothe-desktop
```

Do **not** run monorepo format/lint/test/publish against submodule trees. Bump
submodule pins when consuming new upstream versions; release those packages from
their repositories.

**Key docs**: [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for architecture, [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) for plugins.

---

## 🔧 Quick Reference

| What | Where |
|------|-------|
| Nano agent factory | `packages/soothe-nano/src/soothe_nano/agent/factory.py` (`create_nano_agent`) |
| Host agent factory | `packages/soothe/src/soothe/coreagent/factory.py` (`create_soothe_agent`) |
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
from soothe.events.catalog import register_event

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
2. **Implement**: Place code per §7b Package Boundaries → check ecosystem → follow patterns → run `make lint`
3. **Cleanse → Verify → Fix** (Critical Rule 6 — MUST after every code impl): remove related legacy/dead code **without changing existing functionality**, then `./scripts/verify_finally.sh`, then fix until green
4. **GitHub Actions**: Use `GITHUB_PAT` env var; `export GH_TOKEN="$GITHUB_PAT"` for `gh` CLI

---

## 🆘 Help

- Architecture → `docs/specs/RFC-*.md`
- Patterns → `docs/impl/IG-*.md`
- APIs → `thirdparty/` (reference only, don't import)
- Debug → `docs/wiki/howto_debug.md`
- Config → `config/nano.template.yml` (+ `config/soothe.template.yml` host overlay)