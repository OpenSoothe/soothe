# Soothe Development Guide

> Goal-driven orchestration framework for 24/7 autonomous agents. Extends deepagents with planning, durability, and remote agent interop.

---

## ⚠️ CRITICAL RULES

### 1. Implementation Guides (IGs)
- **Substantial work**: Create IG in `docs/impl/` (`IG-XXX-brief-title.md`) to track scope
- **Minor changes**: No verbose IG—use commit/PR context, or minimal stub only

### 2. Config Sync
When editing `config/nano.template.yml`, MUST also update `config/develop/nano.yml` with matching structure.

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
place them in the correct package. **Never reverse an arrow.** Enforcement:
`scripts/check_module_import_boundaries.sh` and
`scripts/check_nano_duplicate_symbols.py` (wired into `./scripts/verify_finally.sh`).

#### Dependency DAG (allowed direction only)

```text
soothe-sdk            ← shared contracts (leaf; no upward imports)
soothe-deepagents     ← deepagents fork (leaf)
        ↓
soothe-nano           ← Coding CoreAgent (standalone; mirasoth/soothe-nano)
        ↓
soothe                ← host: StrangeLoop, Autopilot, CE, cron, runner
        ↓
soothe-daemon         ← soothed process (soothe + soothe-sdk; nano via soothe)
        ↑
soothe-client-python  ← WebSocket transport (sdk only among workspace pkgs)
        ↑
soothe-cli            ← Typer + Textual TUI (sdk + client; talks over wire)
```

#### Placement (where new code goes)

| Concern | Package |
|---------|---------|
| Shared events, wire, display, plugin contracts, protocols | `soothe-sdk` |
| Coding CoreAgent, skills/MCP/backends used in-proc | `soothe-nano` |
| StrangeLoop, Autopilot, Context Engine, cron, identity, host runner | `soothe` |
| Process lifecycle, channels, HTTP/WS server, admin IO | `soothe-daemon` |
| Human CLI / TUI | `soothe-cli` |
| Language WS clients | `client/*` (`soothe-client-python`, etc.) |

#### Import allow / deny (MUST)

| Package | May import (workspace) | Must NOT import |
|---------|------------------------|-----------------|
| `soothe-sdk` | — | any other workspace package |
| `soothe-deepagents` | — | any `soothe*` package |
| `soothe-nano` | `soothe-sdk`, `soothe-deepagents` | `soothe`, `soothe_daemon`, `soothe_cli` |
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_daemon`, `soothe_cli` |
| `soothe-daemon` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` |
| `soothe-client-python` | `soothe-sdk` | `soothe`, `soothe_daemon`, `soothe_cli` |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket, not Python imports) |

Additional hard bans:

1. **CLI sits above the daemon** — `soothe_cli` must not import daemon/host; communicate via wire contracts in sdk + `soothe-client-python`.
2. **Daemon does not depend on the WS client** — `soothe_daemon` must not import `soothe_client` in runtime source; admin RPCs use `soothe_sdk.wire` (tests may use the client via the `dev` extra).
3. **Nano is standalone** — no host/daemon imports (`TYPE_CHECKING` included). No host-only symbols in nano source: `StrangeLoop`, `Autopilot`, `ContextEngine`, `cron`, intake-only, `sloop`, goal-completion hooks, identity runtime/middleware, daemon heartbeat events, etc. (literal ban in `check_module_import_boundaries.sh` rule 3c).
4. **Private nano middleware is closed** — other packages must not import `soothe_nano.middleware._*`.
5. **No dead duplicates** — do not redefine in nano a public symbol the host/daemon already owns; host is canonical (`check_nano_duplicate_symbols.py`).

#### Standalone docstring / comment rules (`soothe-sdk`, `soothe-nano`)

These packages ship independently and must not reference monorepo docs or
host/daemon concepts. Docstrings, comments, and `__init__` summaries must
read as self-contained.

1. **No IG-XXX / RFC-XXX** in source (`*.py`), including docstrings and
   comments. Replace `(RFC-105)` / `(IG-258 Phase 2)` style parentheticals
   with a plain-English description. Exception: the single nano `__init__.py`
   package docstring may say "no StrangeLoop/Autopilot" to mark scope — never
   an IG/RFC number.
2. **No host/daemon concept names** in docstrings or comments: `StrangeLoop`,
   `Autopilot`, `ContextEngine`, `cron`, `intake-only`, `daemon`, `soothed`,
   `routing_classification`, `goal_completion`, `sloop`. (Saying "no
   StrangeLoop" in the package docstring is allowed; using them to describe
   behavior is not.)
3. **No `soothe.` / `soothe_daemon.` paths** in docstrings, comments, or
   docstring examples.
4. **Describe behavior, not provenance.** Write `Batched edit for coalescing
   middleware`, not `IG-517: Batched edit…`. Write `multi-database PostgreSQL
   layout`, not `RFC-612 multi-database layout`.

Host packages (`soothe`, `soothe-daemon`, `soothe-cli`) MAY reference
IG-XXX/RFC-XXX in docstrings and comments (they live beside `docs/`).
Standalone packages (`soothe-sdk`, `soothe-nano`) must not.

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
├── soothe-sdk/         # Shared contracts submodule (mirasoth/soothe-sdk) — leaf
├── soothe-deepagents/  # deepagents fork submodule (mirasoth/soothe-deepagents) — leaf
├── soothe-nano/        # Coding CoreAgent submodule (mirasoth/soothe-nano); no StrangeLoop/Autopilot
├── soothe/             # Host: StrangeLoop, Autopilot, CE, cron, runner (depends on nano)
├── soothe-daemon/      # Daemon server (soothed); depends on soothe + soothe-sdk (nano via soothe)
└── soothe-cli/         # Typer CLI + Textual TUI (sdk + client over WebSocket; not soothe/daemon)

client/
├── go/                 # soothe-client-go
├── typescript/         # @mirasoth/soothe-client
├── rust/               # soothe-client-rust (if present)
└── python/             # soothe-client-python (WebSocket transport; sdk only)
```

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