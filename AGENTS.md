# Soothe Development Guide

> Goal-driven orchestration framework for 24/7 autonomous agents. Extends deepagents with planning, durability, and remote agent interop.

---

## ⚠️ CRITICAL RULES

### 1. Implementation Guides (IGs)
- **Substantial work**: Create IG in `docs/impl/` (`IG-XXX-brief-title.md`) to track scope
- **Minor changes**: No verbose IG — use commit/PR context, or minimal stub only

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
Before marking work done (commit, PR, or handoff), apply this sequence every time:

1. **Ask user before cleansing** — for each implementation finished, ask whether to cleanse legacy code, backward compat shims, and dead code related to the change.
2. **Cleanse** — if approved, remove superseded helpers, unused exports, duplicate paths, compat shims, and stale tests/docs. Deletion/consolidation only; **no behavior rewrites**.
3. **Verify** — `./scripts/verify_finally.sh`
4. **Fix to green** — lint, format, tests, vulture. Re-cleanse if fixes leave new dead code, then re-verify until green.

### 7. Terminology
- NEVER use "layer N" — use concrete names (CoreAgent, StrangeLoop, GoalEngine)
- NEVER expose IG-XXX/RFC-XXX in user-facing text (logs, CLI, errors, config descriptions). They are internal only — allowed in docstrings, comments, and internal docs.
- Only `docs/specs/` (RFCs) and `docs/impl/` (IGs) are active references. `docs/archive/` is historical only.

### 7b. Package Boundaries (MUST)

Soothe is a **one-way dependency DAG**. Place code in the correct **monorepo-owned** package. **Never reverse an arrow.**
Enforcement: `scripts/check_module_import_boundaries.sh` (wired into `./scripts/verify_finally.sh`).

**Owned**: `soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`, `soothe-sdk`.
**Submodules** (`client/*`): consumed as code — do **not** format/lint/test/release them here.
**PyPI-only**: `soothe-nano`, `soothe-deepagents` (maintain/release in their own repos).

> `soothe-sdk` keeps its own `VERSION` file (1.x line) because `soothe-nano` (PyPI) depends on `soothe-sdk>=1.0.7`. All other owned packages use the root `VERSION` file (0.x line).

#### Dependency DAG (allowed direction only)

```text
soothe-sdk            ← shared contracts (monorepo; leaf)               ← OWNED
soothe-deepagents     ← deepagents fork (PyPI; leaf)
        ↓
soothe-nano           ← Coding CoreAgent (PyPI)
        ↓
soothe                ← host: StrangeLoop, CE, runner                   ← OWNED
        ↓
soothe-autopilot      ← goal orchestration: Autopilot, rails, verify    ← OWNED
        ↓
soothe-daemon         ← soothed process (channels, cron)                ← OWNED
        ↑
soothe-client-python  ← WebSocket transport (submodule)
        ↑
soothe-cli            ← Typer + Textual TUI                             ← OWNED
```

#### Placement (where new code goes)

| Concern | Package |
|---------|---------|
| Shared events, wire, display, plugin contracts, protocols | `soothe-sdk` (`packages/soothe-sdk`) |
| Coding CoreAgent, skills/MCP/backends in-proc | `soothe-nano` (PyPI) |
| StrangeLoop, Context Engine, identity, host runner | `soothe` |
| Autopilot (scheduling, dispatch, monitor, rails, verify, notify) | `soothe-autopilot` |
| Process lifecycle, channels, HTTP/WS server, admin IO, cron | `soothe-daemon` |
| Human CLI / TUI | `soothe-cli` |
| Language WS clients | `client/*` (submodules) |

#### Import allow / deny (MUST)

| Package | May import | Must NOT import |
|---------|------------|-----------------|
| `soothe-sdk` | `pydantic`, `langchain-core` only | `soothe`, `soothe_autopilot`, `soothe_daemon`, `soothe_cli` |
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_autopilot`, `soothe_daemon`, `soothe_cli` |
| `soothe-autopilot` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_daemon`, `soothe_cli`, `soothe_client` |
| `soothe-daemon` | `soothe`, `soothe-autopilot`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket, not Python imports) |

Hard bans (owned packages):
1. **CLI sits above the daemon** — `soothe_cli` must not import daemon/host; communicate via wire contracts in sdk + `soothe-client-python`.
2. **Daemon does not depend on the WS client** — `soothe_daemon` must not import `soothe_client` in runtime source; admin RPCs use `soothe_sdk.wire` (tests may use the client via the `dev` extra).
3. **Private nano middleware is closed** — owned packages must not import `soothe_nano.middleware._*`.

Host packages (`soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`, `soothe-sdk`) MAY reference IG-XXX/RFC-XXX in docstrings and comments.

### 8. DO NOT Cheat Tests
Fix the implementation, not test expectations. "Passing tests" ≠ "Working correctly."

### 9. No Keyword Heuristics (RFC-630)
Prefer **structured light-LLM fields** or **declarative config rules** over keyword/regex content-judgment heuristics.

- **Content judgment** (intent, identity, routing, failure classification): use Pass 1/2 structured output or a dedicated fast-model call — not keyword lists or regex on user text.
- **Structural controls** (`continue`/`resume`, checkpoint gates, status vocabulary): deterministic rules are fine.
- **Thresholds and banned patterns**: put in config (`agent.loop.rules`, etc.), not magic numbers or inline regex.
- **If a keyword/regex heuristic seems required**: stop and ask the user. Propose the LLM or config-rules alternative first.

See [IG-567](docs/impl/IG-567-heuristic-to-rules-migration.md) for the StrangeLoop migration pattern.

### 10. Unified Persistence Backend (MUST)
`persistence.default_backend` is **one mode for the whole process**: `postgresql` or `sqlite`. **Never mix** the two in the same daemon/runtime.

- **Postgres mode** → all daemon-owned durable stores MUST use PostgreSQL (RFC-612 databases under `postgres_base_dsn` / `postgres_databases`). No SQLite "for convenience" for cron, identity, display cards, checkpoints, Context Engine, durability, or autopilot.
- **SQLite mode** → use local `$SOOTHE_HOME` / `$SOOTHE_DATA_DIR` SQLite files. Do not open a parallel Postgres path for any subset of features.
- Overrides (`agent.protocols.durability.backend` / `.checkpointer`) MUST stay `"default"` unless the operator intentionally switches the **entire** process.
- Vector stores follow the same rule: Postgres → `pgvector`; SQLite → `sqlite_vec` (in-memory for tests only).
- New persistence features MUST branch on `persistence.default_backend` (or a shared factory) — never hard-code SQLite when Postgres is configured.
- Leftover SQLite files under `$SOOTHE_DATA_DIR` in Postgres mode are legacy only; do not write new runtime state to them.

### 11. No AI Co-Authors (MUST)
AI agents MUST NOT add AI tools or assistants as co-authors, reviewers, or attributions in commits, PRs, or any git metadata. This includes Cursor, Claude, Grok, GitHub Copilot, ChatGPT, Gemini, Cody, Continue, Cline, and similar.

- No `Co-authored-by:` trailers (e.g. `Co-authored-by: Cursor <noreply@cursor.com>`).
- No `Generated-with:`, `Assisted-by:`, `Reviewed-by:` (for AI), or equivalent trailers.
- No AI-tool names in `AUTHORS`, `CONTRIBUTORS`, `.mailmap`, release notes, or changelog author lines.
- No `--trailer` / `git commit --trailer` attributing any AI tool.
- `git log` reflects **human contributors only**. AI assistance may be disclosed in PR description prose, but **never** in commit metadata.

If a hook or template inserts an AI co-author trailer, remove it before committing.

### 12. Drift Governance (MUST)
Spec↔code drift is tracked through **canonical documentation mechanisms only** — not ad-hoc dashboards, cron jobs, or parallel tracking systems.

- **No drift-refresh cron infrastructure** — do not re-introduce `DriftRefreshConfig`, `DriftTriggerHook`, `builtin:drift-refresh-*` cron jobs, or drift-dashboard data dictionaries. They duplicated the RFC/IG review process without adding value.
- **Gap-tracking scripts** (`scripts/auto_gap_report.py`, `scripts/create_drift_backlog_issues.sh`) MUST write output into `docs/impl/` with an `IG-` prefix and be triaged through the standard IG lifecycle — never a separate dashboard or backlog.
- **Drift findings are IGs, not dashboards** — file `IG-XXX-gap-*.md` in `docs/impl/`. Do not create standalone drift-tracking documents outside the numbered IG process.
- **Config fields** — do not add `cron.drift_refresh` or equivalent drift-dashboard blocks to any `config/*.template.yml` or packaged copy. Drift governance is a documentation process, not a runtime config concern.
- **Wiki/docs** — deployment guides and troubleshooting indexes MUST NOT link to drift runbooks or dashboards. Document drift content under the IG that addresses the specific gap.
- **Incidental "drift" mentions** — the word "drift" describing unrelated concepts (timestamp drift, message-shape drift, pin drift) in comments/docstrings/errors is fine. This rule governs spec↔code drift infrastructure only.

### 13. Changelog (MUST)
Keep changelogs **brief and sharp**. Each entry is a single scannable line telling *what changed and why* — nothing more.

- **One line per change** — no multi-paragraph prose, no preamble, no "This PR..." narration.
- **Lead with user-facing effect**, not implementation detail.
- **Active voice, imperative mood** — "Add retry backoff to channel sends", not "Retries were added".
- **Concrete and specific** — name the component, config key, or command. Avoid "various improvements", "misc fixes".
- **Group by release section** (`Added` / `Changed` / `Fixed` / `Removed`); most impactful first.
- **No internal jargon** — omit IG-XXX/RFC-XXX, ticket IDs, commit hashes from the body (per §7). Link from release notes if needed.
- **No AI attribution** (per §11).
- **If a change isn't user-visible, it probably doesn't belong in the changelog.** Internal refactors, test additions, and tooling that don't alter behavior are omitted unless they affect operators.

Good: `Add \`persistence.default_backend\` validation that rejects mixed sqlite/postgres in one process.`

Bad: `This PR updates the persistence layer to add a check for the default backend config so that users don't accidentally mix backends. See IG-612 for details. (#1234, authored by...)`

### 14. Release (MUST)
A **release** = publishing a new version of a Soothe package on PyPI via the GitHub release workflow. Before cutting any release:

1. **Verify upstream libs** — check whether `soothe-sdk`, `soothe-client-python` (submodule), `soothe-deepagents`, and `soothe-nano` require updating. Bump submodule pins / PyPI floors when consuming new upstream versions; release those packages from their own repositories first, then pin a compatible version range here.
2. **Default to patch** — release a **patch** bump (e.g. `0.x.y → 0.x.y+1`). Do **not** cut minor/major unless explicitly approved; those require a documented breaking change and sign-off.
3. **Release = PyPI via GitHub workflow** — publishing happens through `.github/workflows/`, not a manual `twine upload` or local build. Tag the release and let CI publish.
4. **Verify before release** — `./scripts/verify_finally.sh` MUST pass (zero lint errors, all tests green) on the commit being tagged. Pre-release CI MUST also pass before the publish job runs. Do not tag or release off a red build.

---

## 📁 Structure

Import/placement rules: **§7b Package Boundaries (MUST)**. Do not reverse the DAG.

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

**Key docs**: [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for architecture, [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) for plugins.

---

## 🔧 Quick Reference

| What | Where |
|------|-------|
| Nano agent factory | `soothe_nano.agent.factory.create_nano_agent` (PyPI `soothe-nano`) |
| Host agent factory | `packages/soothe/src/soothe/coreagent/factory.py` (`create_soothe_agent`) |
| Nano config | `soothe_nano.config.settings` (PyPI `soothe-nano`) |
| Host config | `packages/soothe/src/soothe/config/settings.py` |
| Shared protocols | `packages/soothe-sdk/src/soothe_sdk/protocols/` |
| Loop protocols | `packages/soothe/src/soothe/protocols/` |
| RFCs | `docs/specs/` |
| IGs | `docs/impl/` |
| Debug guide | `docs/wiki/howto_debug.md` |
| Archived docs | `docs/archive/` (historical only) |

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

**deepagents** provides: file ops, shell, task tracking, SubAgent, Skills, Memory, Summarization middleware.

**langchain** provides: web search (Tavily, DuckDuckGo), ArXiv, Wikipedia, GitHub, Gmail, document loaders, `init_chat_model()`.

**Check these first.**

---

## 🚦 Workflow

1. **Plan**: Explore codebase → ask when alternatives exist → ExitPlanMode for approval
2. **Implement**: Place code per §7b → check ecosystem → follow patterns → `make lint`
3. **Cleanse → Verify → Fix** (Critical Rule 6 — MUST after every code impl): remove related legacy/dead code **without changing existing functionality**, then `./scripts/verify_finally.sh`, then fix until green
4. **GitHub Actions / `gh` CLI**: Use the `GH_TOKEN` env var

---

## 🆘 Help

- Architecture → `docs/specs/RFC-*.md`
- Patterns → `docs/impl/IG-*.md`
- APIs → `thirdparty/` (reference only, don't import)
