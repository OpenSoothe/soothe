# Handover: soothe-nano extract (`feat/nano-agent`)

**Date**: 2026-07-20  
**Branch**: `feat/nano-agent` (synced with `origin/feat/nano-agent`)  
**HEAD**: `58ec867b` — *chore(nano): declare direct deps, polish agent gate, version 0.9.0*  
**Tracking IG**: [IG-668](IG-668-soothe-nano-package-extract.md)  
**Working tree**: dirty — intake-catalog extract uncommitted (see below)

Use this to continue without re-deriving context. Prefer IG-668 + this file over chat history.

---

## Goal (locked)

Extract a **batteries-included Coding CoreAgent** into `soothe-nano`. Full `soothe` owns StrangeLoop / Autopilot / Context Engine / cron / identity **service** / runner.

**Hard rule**: `soothe_nano` must never import `soothe` (or cli/daemon). Enforced by `scripts/check_module_import_boundaries.sh` Rule 3b/3c and `verify_finally.sh`.

---

## Dependency graph (current)

```
soothe-deepagents → soothe-sdk → soothe-nano → soothe → soothe-daemon / soothe-cli
                         ↑_______________|
soothe-plugins  → soothe-nano (+ soothe-sdk)
soothe-daemon   → soothe + soothe-nano (direct) + soothe-sdk
```

| Package | Version source | Current |
|---------|----------------|---------|
| `soothe` / `soothe-cli` / `soothe-daemon` | Root `VERSION` | `0.8.5` |
| `soothe-nano` | Own `pyproject.toml` | **`0.9.0`** (independent) |
| `soothe-sdk` | Own `pyproject.toml` | `1.0.1` |
| `soothe-plugins` | Own `pyproject.toml` | `0.2.6` |

Dependents pin: `soothe-nano>=0.9.0,<1.0.0` (`soothe`, `soothe-daemon`, `soothe-plugins`).

Release: `.github/workflows/release.yml` has `deploy-nano` (reads nano `pyproject.toml`); core/plugins wait on nano PyPI before publish.

---

## Commits on this branch (vs main, high signal)

| Commit | Summary |
|--------|---------|
| `b10167c6` | Extract Coding CoreAgent into `soothe-nano` (IG-668 scaffold) |
| `bb23c3d9` | Purify nano of L2/L3; direct `soothe_nano.*` imports; delete leaf shims |
| `a93efcf4` | Move shared protocols to `soothe_sdk.protocols`; delete nano protocols package |
| `72ee6a9b` | Skillify → `soothe_daemon.skillify`; DTOs → `soothe_sdk.skillify`; nano search substring-only |
| `58ec867b` | Direct nano deps; merge `execute_stream` into `core_agent`; nano **0.9.0** |

---

## Ownership map (do not reverse)

| Concern | Canonical home |
|---------|----------------|
| Coding CoreAgent / builder / lazy | `soothe_nano.agent` |
| Ephemeral execute gate | `soothe_nano.agent.core_agent.ephemeral_execute_stream_enabled` (no `execute_stream.py`) |
| Skills catalog / progressive substring search | `soothe_nano.skills` |
| Skillify service (index/retrieve) | `soothe_daemon.skillify` |
| Skillify DTOs | `soothe_sdk.skillify` |
| Shared protocols (planner, memory, core_agent, …) | `soothe_sdk.protocols` |
| Identity error hierarchy (RFC-307) | `soothe_sdk.identity.errors` (service remains `soothe.foundation.identity`) |
| Base event classes / wire constants | `soothe_sdk.core.events` |
| `extract_text_from_ai_message` | `soothe_sdk.display.text_extract` (`soothe.foundation` re-exports) |
| CoreAgent system prompts / identity / context XML | `soothe_nano.prompts` (slim fragments: default/simple/medium + assistant_identity) |
| Host loop / intake / plan / synthesis prompts | `soothe.prompts` (`foundation.sloop.prompts` is a shim) |
| Intake-only subagent catalog + partition | `soothe.foundation.sloop.subagent_catalog` |
| Intake-only ``task`` guard middleware | `soothe.foundation.sloop.middleware.intake_task_guard` |
| Nano subagent helper (name only) | `soothe_nano.agent.subagent_catalog.spec_subagent_name` |
| Loop-only protocols | `soothe.protocols` (thin) |
| Host `create_soothe_agent` + planner + intake bind | `soothe.foundation.coreagent.coding` |
| Host config (`skillify:`, loop, autopilot, …) | `soothe.config` |
| Nano config slice | `soothe_nano.config` (`extra="ignore"` for host-only YAML keys) |

Weaver: sdk DTOs + `get_skillify_service` only (no `start_skillify_service` in plugin; no `soothe-daemon` declared dep — runtime import in daemon process).

---

## Verification

Last full gate: `./scripts/verify_finally.sh` green after intake-catalog extract (2026-07-20).

Before next commit/PR: re-run `./scripts/verify_finally.sh` if more edits land.

---

## Suggested next work (uncommitted ideas)

From IG-668 follow-ups and leftover polish:

1. **RFC-100 / NanoConfig slim** — further separate nano config fields from full `SootheConfig` ownership (nano still exposes a large `SootheConfig`-shaped settings model).
2. **Agent package polish** — optional: fold thin `factory.py` into `builder.py` / package `__init__` (explicitly out of last execute_stream plan).
3. **PyPI first publish** — publish `soothe-nano==0.9.0` when cutting a release (trusted publishing job already wired).
4. **PR to main** — branch is ahead of `origin/main` by the commits above; no PR created yet in this session.
5. **Examples outside `core_agent/`** — `examples/agents/*` / `inproc_soothe_agent.py` still use host `create_soothe_agent`; only `examples/core_agent/*` switched to `create_nano_agent`.
6. **Release skill / docs** — nano is listed as standalone; keep sdk/nano/plugins bumps intentional and separate from root `VERSION`.
7. **Identity middleware host move** (optional) — `IdentityMiddleware` / `IdentityConfig` / `IdentityRuntime` still live in `soothe_nano.middleware.identity`; errors already in sdk. Moving middleware into soothe is a larger daemon/builder churn.

**Done in boundary polish (2026-07-20):** identity errors → `soothe_sdk.identity`; deleted nano/soothe duplicate `base_events.py` (canonical `soothe_sdk.core.events`); `extract_text_from_ai_message` → `soothe_sdk.display.text_extract`; nano prompts purified to CoreAgent-only; host loop prompts moved to `soothe.prompts`.

**Done in intake-catalog extract (2026-07-20):** `INTAKE_ONLY_*` / partition helpers moved to `soothe.foundation.sloop.subagent_catalog`; nano builder keeps all specialists on open `task` unless host overrides `_filter_subagents_for_graph`; host `CodingCoreAgent.bind_intake_only_subagents` + `IntakeOnlyTaskGuardMiddleware` (via `_host_middleware_prefix`); Rule 3c bans `INTAKE_ONLY` / `intake_only` / `intake/slash` in nano src.

---

## Key paths (cheat sheet)

```
packages/soothe-nano/src/soothe_nano/agent/     # CoreAgent surface
packages/soothe-sdk/src/soothe_sdk/protocols/   # Shared contracts
packages/soothe-sdk/src/soothe_sdk/skillify/    # SkillBundle DTOs
packages/soothe-daemon/src/soothe_daemon/skillify/
packages/soothe/src/soothe/foundation/coreagent/coding/  # Host wrappers
docs/impl/IG-668-soothe-nano-package-extract.md
scripts/check_module_import_boundaries.sh
./scripts/verify_finally.sh
```

---

## Do not

- Reintroduce `soothe_nano → soothe` imports.
- Put Skillify service back in nano or call `start_skillify_service` from weaver.
- Tie `soothe-nano` version to root `VERSION` again.
- Add `soothe-daemon` as a declared dependency of `soothe-plugins`.
- Expose IG-/RFC- ids in user-facing strings.

---

## Session transcript (optional)

Cursor agent transcript for this arc: project agent-transcripts under id `eaf6b9b9-2b81-417c-a586-f64801985f07` (nano extract → protocols → skillify → deps → execute_stream → 0.9.0).
