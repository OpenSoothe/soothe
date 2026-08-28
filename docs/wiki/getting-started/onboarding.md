---
title: "Onboarding Guide"
parent: Getting Started
grand_parent: Wiki
nav_order: 4
description: >-
  Single-page onboarding path: setup, daily workflow, and debugging for new
  contributors to the Soothe monorepo.
---

# Onboarding Guide

A consolidated path from clone to first merged PR. This page stitches together
the essentials of [Installation](Installation.md), the
[Contributing Guide](../contributing-guide.md), the
[Testing Guide](../testing-guide.md), and the
[Debug Guide](../howto_debug.md) so a new contributor can move without
context-switching. Each section links to the deeper page when you need more.

> **Audience**: contributors to the **owned** monorepo packages
> (`soothe`, `soothe-daemon`, `soothe-cli`). If you only want to *use* Soothe,
> start at [Quick Start](Quick-Start.md) instead.

---

## 1. Setup

### 1.1 Prerequisites

- **Python 3.11+** — `python --version` must report 3.11.x or higher.
- **[uv](https://docs.astral.sh/uv/)** — the workspace package manager used by
  every `make` target and by `verify_finally.sh`.
- **Docker** — required for integration tests and the dev stack
  (PostgreSQL + pgvector + Langfuse).
- **Git** — with submodules enabled (clients are consumed as submodules).

### 1.2 Clone & sync

```bash
git clone https://github.com/mirasoth/soothe.git
cd soothe
make sync            # = uv sync --all-packages --all-extras (then PyPI URL rewrite)
```

`make sync` resolves the full workspace, installs all extras + dev deps, and
rewrites `uv.lock` URLs to canonical PyPI (see `scripts/rewrite_uv_lock_to_pypi.sh`).
If a sync stalls on a mirror, prefer `make sync-no-cache` (uses `--no-cache
--refresh`).

### 1.3 Know the package layout

This repo **owns three packages** (format/lint/test/publish here):

```
packages/
├── soothe-cli/        # CLI + TUI (Typer + Textual)
├── soothe/            # StrangeLoop / Autopilot / host composition (library)
└── soothe-daemon/     # soothed process (WebSocket + HTTP transports)
```

Submodules (`client/{python,go,typescript,rust}`, `soothe-sdk`) are
**consumed as code** — do not format, lint, test, or release them here.
`soothe-nano` and `soothe-deepagents` are PyPI dependencies, not vendored.

### 1.4 Dependency direction (one-way DAG)

```text
soothe-sdk            ← shared contracts (PyPI; leaf)
soothe-deepagents     ← deepagents fork (PyPI; leaf)
        ↓
soothe-nano           ← Coding CoreAgent (PyPI)
        ↓
soothe                ← host: StrangeLoop, Autopilot, CE, cron, runner   ← OWNED
        ↓
soothe-daemon         ← soothed process                                 ← OWNED
        ↑
soothe-cli            ← Typer + Textual TUI                             ← OWNED
```

| Package | May import | Must NOT import |
|---------|------------|-----------------|
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_daemon`, `soothe_cli` |
| `soothe-daemon` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` (runtime) |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket) |

Boundaries are enforced by `scripts/check_module_import_boundaries.sh`, which
runs inside `./scripts/verify_finally.sh`. Reversing an arrow fails CI.

### 1.5 Optional dev services

```bash
make docker-dev-up    # pgvector + Langfuse for integration tests
make docker-dev-ps    # status
make docker-dev-down  # stop
```

### 1.6 First verification

```bash
./scripts/verify_finally.sh
```

You should see the green summary (workspace integrity → dependency validation →
format → lint → vulture → unit tests). This is the single gate you must clear
before every commit; see [§2.3](#23-the-verification-gate) below.

---

## 2. Workflow

### 2.1 Daily loop

```bash
# 1. branch
git checkout -b feature/my-feature     # or bugfix/...

# 2. edit code + tests together
#    src:    packages/soothe/src/soothe/sloop/engine/strange_loop.py
#    test:   packages/soothe/tests/unit/core/loop/engine/test_strange_loop_*.py

# 3. run the targeted test
cd packages/soothe
uv run pytest tests/unit/core/loop/engine/test_strange_loop_model_roles.py -v

# 4. format + lint (fast feedback)
make format           # write
make format-check    # CI-equivalent
make lint

# 5. full gate before commit
cd - && ./scripts/verify_finally.sh
```

### 2.2 Quality targets (per AGENTS.md)

- **Python ≥ 3.11**, type hints on all public functions, Google-style
  docstrings (`Args`/`Returns`/`Raises`), single backticks for inline code.
- **Naming**: `snake_case` modules/functions, `PascalCase` classes,
  `UPPER_SNAKE_CASE` constants, `_leading_underscore` private.
- **No bare `except:`** — typed exception handling only.
- **No keyword heuristics** for content judgment — use structured light-LLM
  fields or declarative config rules. If a regex/keyword list seems required,
  stop and ask before implementing.
- **Ecosystem first**: check `langchain-core`, `langchain-community`,
  `deepagents` before writing new tools/subagents/MCP/memory middleware.
- **Tests live in packages**: `packages/<pkg>/tests/unit/` or
  `packages/<pkg>/tests/integration/` — never a root `tests/`.

### 2.3 The verification gate

`./scripts/verify_finally.sh` is mandatory before **any** commit. Flags:

| Flag | What it does |
|------|--------------|
| *(none)* | Full suite: sync → deps → format → lint → vulture → unit tests |
| `--quick` | Skip tests (format + lint only) |
| `--fix` | Auto-fix formatting and linting, then re-check |
| `--deps` | Dependency/boundary validation only |

All checks must pass: zero lint errors, all unit tests green (900+). Do not
stop at a failing run — fix the implementation, not the test expectations
(AGENTS.md rule: "Passing tests" ≠ "Working correctly").

### 2.4 After-code cleanse → verify → fix

Per AGENTS.md rule 6, once an implementation is finished (and before marking
work done):

1. **Ask** whether to cleanse legacy code, backward-compat shims, and dead code
   related to the change.
2. If approved, **cleanse** — delete/consolidate only; do not rewrite behavior.
3. **Run** `./scripts/verify_finally.sh`.
4. **Fix** all errors (lint, format, tests, vulture). Re-cleanse if fixes leave
   new dead code, then re-run verify until green.

### 2.5 Config-sync rule

When editing `config/templates/nano.yml`, you **must** also update
`config/develop/nano.yml` with matching structure. The packaged templates under
`packages/soothe-daemon/src/soothe_daemon/setup/templates/` are the SoT;
`config/templates/` are symlinks to them. Enforced by `scripts/check_config_sync.sh` (writes
`config-sync-diff.txt`).

### 2.6 PR process

```bash
./scripts/verify_finally.sh          # MANDATORY, all green
git add -A && git commit -m "feat: ..."   # see commit guidelines in Contributing Guide
git push origin feature/my-feature
# open PR on GitHub using the repo PR template
```

CI (`.github/workflows/alignment-check.yml`) re-runs five checks on PRs to
`main`/`develop`: first-party pin alignment, config-sync, wiki staleness lint,
workflow YAML validate, and RFC metadata. Passing locally with
`verify_finally.sh` makes CI green in the large majority of cases.

---

## 3. Debugging

### 3.1 Log locations

| Log File | Purpose |
|----------|---------|
| `~/.soothe/logs/soothed.log` | Daemon backend (agent execution, protocols, tools) |
| `~/.soothe/logs/soothe-cli.log` | CLI client (connection, UI, event handling) |
| `~/.soothe/data/threads/{thread_id}/logs/` | Thread conversation audit (when `thread_logging.enabled`) |
| `~/.soothe/data/databases/checkpoints.db` | StrangeLoop + LangGraph checkpoints |
| `~/.soothe/data/databases/metadata.db` | Metadata / durability |

### 3.2 Enabling debug logging

**Quick (env, no restart of CLI):**

```bash
export SOOTHE_DEBUG=true            # global verbose behavior logging
export SOOTHE_LOG_LEVEL=DEBUG       # file logging to DEBUG for daemon + CLI
soothed stop && soothed start
soothe
```

**Persistent (config):** set `debug: true` and `logging.file.level: DEBUG` in
`~/.soothe/config/nano.yml`; optionally enable `thread_logging` for per-thread
audit. Restart the daemon to pick up config changes. CLI picks up
`--log-level` / `SOOTHE_LOG_LEVEL` on every invocation, no restart needed.

> **Verbosity vs log level**: TUI progress verbosity is a client-side
> preference (`quiet` / `normal` / `debug`) controlling what events are
> displayed. `--log-level` / `SOOTHE_LOG_LEVEL` controls what gets written
> to the CLI log file (Python logging). They are independent.

### 3.3 Live log inspection

```bash
tail -f ~/.soothe/logs/soothed.log         # daemon backend
tail -f ~/.soothe/logs/soothe-cli.log      # CLI client
grep -i "error\|exception\|failed" ~/.soothe/logs/soothed.log
grep -i "websocket\|connection\|timeout" ~/.soothe/logs/soothe-cli.log
grep -i "subagent" ~/.soothe/logs/soothed.log
```

### 3.4 Common workflows

**Agent behavior** (not executing steps, tools not called, subagent failing):
enable `SOOTHE_LOG_LEVEL=DEBUG`, run `soothe -p "..."`, then watch
`soothed.log` for loop iteration count, planner decisions, tool selection,
subagent delegation, goal state transitions.

**Model/LLM** (wrong model, malformed prompts): enable Langfuse under
`observability.langfuse` in `nano.yml` (`pip install langfuse`), restart the
daemon, run a query, then inspect model resolution, prompt construction, tool
definitions sent, response parsing, token usage in the Langfuse UI (the daemon
log only records that Langfuse is active).

**Daemon request timeout** (`Request exceeded …s`, step cancelled mid-run):
confirm wall-clock vs configured cap:

```bash
rg 'request timeout|Request exceeded|cancelled after' \
   ~/.soothe/logs/daemon.log ~/.soothe/data/loops/*/runner.log
grep -A2 'request_timeout_seconds' ~/.soothe/config/daemon.yml
grep -A2 'goal_deadline_seconds' ~/.soothe/config/nano.yml
```

Defaults (template): **1209600s (14 days)** for both daemon request timeout and
autopilot goal deadline. Resume/re-run with a higher cap if the goal legitimately
needs more wall-clock time.

**Stale worker_pool subprocesses**: enable `worker_pool` + `stale_worker_reap`
in `daemon.yml` (default interval 1800s) for automatic periodic reap while the
daemon runs; for a one-off manual cleanup with the daemon stopped, run
`uv run python -m soothe_daemon.persistence` (add `--dry-run` to preview).
`thread_pool` mode has no spawn workers, so periodic reap is not started.

### 3.5 Troubleshooting cross-refs

For exhaustive error catalogs (API key, subagent disabled, WebSocket refused,
config schema, persistence backend mode), see
[Troubleshooting](../troubleshooting/index.md). For the full debug playbook
(verbosity levels, thread conversation logs, model/connection/stale-worker
workflows), see the [Debug Guide](../howto_debug.md).

---

## 4. Next steps

- **Architecture**: [Architecture Overview](../architecture/index.md),
  [Core Modules](../core/index.md).
- **Configuration**: [Configuration Guide](../configuration-guide/index.md)
  (YAML reference, env vars, provider setup).
- **Reference**: [CLI Reference](../cli-reference.md),
  [TUI Guide](../tui-guide.md), [API Reference](../api-reference/index.md).
- **Specs**: [RFC Index](../../specs/rfc-index.md) for design context
  (internal-only references — never surfaced to users in runtime strings).
