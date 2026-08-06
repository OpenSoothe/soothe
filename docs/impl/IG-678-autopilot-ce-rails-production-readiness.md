# IG-678: Autopilot / Context Engine / LoopRail Production Readiness

**Created**: 2026-08-04
**Status**: Implemented (Phases 0–2; Phase 3 soak optional follow-on)
**Related**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-624](../specs/RFC-624-context-engine.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[RFC-626](../specs/RFC-626-entity-model-state-consolidation.md),
[RFC-630](../specs/RFC-630-no-keyword-heuristics.md),
[IG-677](IG-677-autopilot-job-loop-index.md),
[IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[IG-RQJ-02](IG-RQJ-02-rail-trace-continuity-analysis.md),
[IG-670](IG-670-daemon-auto-resume-interrupted-goals.md),
[LoopRail draft](../drafts/2026-07-11-loop-rail-design.md)

---

## Executive Summary

Close every gap that blocks treating **Context Engine**, **Autopilot**, and
**LoopRail** as production-ready under real ops scenarios (crash mid-job,
cancel/pause, guidance, consensus, multi-goal failure recovery, declarative
rails).

This IG is the single backlog for the readiness findings of 2026-08-04. It is
phased so each phase leaves the system shippable at a higher trust tier:

| Phase | Trust tier after completion |
|-------|----------------------------|
| **P0** | Solo CE + Autopilot happy-path are *honest* (no silent broken RPCs / dead monitor wires) |
| **P1** | Supervised Autopilot pilot (cancel/pause/crash/retry/capacity) trustworthy |
| **P2** | LoopRail live on submit → interpreter → CE builtins → durable job-scoped trace |
| **P3** | Production soak: real E2E tests, Postgres CE proven, doc/RFC status aligned |

---

## Problem (gap inventory)

### A. Context Engine

| ID | Gap | Impact |
|----|-----|--------|
| CE-1 | Dual CE: daemon `ContextEngine()` is in-memory + DAG snapshot sidecar; worker StrangeLoop CE is loop-scoped sqlite/pgsql | “Sole SoT” claim false across process boundary; crash fidelity thin |
| CE-2 | `job_guidance` awaits sync `absorb_guidance` → production `TypeError`; tests mock it away | Guidance RPC broken |
| CE-3 | `guidance_accumulated` never injected into StrangeLoop / dispatch prompts | Guidance stored, not consumed |
| CE-4 | Persistence `save`/`load` swallow errors → silent durability loss | Crash can drop dirty state unnoticed |
| CE-5 | `recover()` only resets `active→pending`; no `attempts_after_crash++`; no step reset | Thin recovery vs RFC error table |
| CE-6 | Wiki/RFC overclaim: `.on()` callbacks, `fail_goal(allow_retry=…)`, EpisodicSubmodule, atomic DAG+ledger save | Operator/docs drift |
| CE-7 | Postgres CE path unit-selected only; no real-DB integration suite | Deploy risk on `default_backend: postgresql` |
| CE-8 | `tests/integration/context/` empty; no crash→restore→redispatch E2E | Confidence gap |

### B. Autopilot

| ID | Gap | Impact |
|----|-----|--------|
| AP-1 | Default `enabled: true` (was `false`); RFC-222 historically mentioned `agent.autonomous.enabled` | Config drift |
| AP-2 | Monitor subscribes to `"goal_completed"` / `"goal_failed"`; CE never emits those; bus uses `soothe.internal.*` | Reactive monitor paths dead |
| AP-3 | ~~`_apply_backoff_decision` logs only~~ → closed by P1-2 / [IG-697](IG-697-engine-deadlock-recovery.md) (retry or leave failed for engine recovery) | Was: failed goals stuck forever |
| AP-4 | Worker `error` slots never return to idle → pool capacity leak | Throughput death under crashes |
| AP-5 | `job_pause` suspends root only — does not cancel in-flight child workers | “Stop now” unsafe |
| AP-6 | Consensus decision parsing uses substring match, not structured output (RFC-630) | Fragile accept/send_back/suspend |
| AP-7 | Dreaming emits awake/dreaming events only; distillation deferred | Advertised feature stub |
| AP-8 | Daemon WS integration tests mock `submit_task` / CE | Protocol proven, E2E not |
| AP-9 | RFC-228 `verification_rules` TODO; ownership / `JOB_NOT_AUTHORIZED` unenforced | Spec incomplete |
| AP-10 | Snapshot `_persist_goals` failures only warn | Silent DAG loss on restart |

### C. LoopRail

| ID | Gap | Impact |
|----|-----|--------|
| RL-1 | Interpreter never bound from Monitor / Service / daemon / CLI | Rails cannot run in production |
| RL-2 | No `rail_id` on submit (WS / SDK / CLI / TUI) | No operator surface |
| RL-3 | No `RailSelector`; no `agent.autopilot.default_rail` config | Auto-pick / fallback missing |
| RL-4 | Tags / branch / `rail_id` live in in-memory `RailJobState`, not `GoalNode` | Lost on restart; not CE SoT |
| RL-5 | `pause_for_user` sets memory flag only — no IPC / TUI gate / `user_intervention` wire | Human gates fake |
| RL-6 | Decompose builtins use generic scout templates, not LLM/CE decompose | Policy DSL ≠ real planning |
| RL-7 | Trace defaults to memory; JSONL unused; Postgres `rail_trace` absent ([IG-RQJ-02](IG-RQJ-02-rail-trace-continuity-analysis.md)) | No durable job-scoped audit |
| RL-8 | `merge_branches` noop; no CE `branch_manager` | Design §5 incomplete |
| RL-9 | No bugfix / hotfix / migration scenario tests; no product-binding tests | Catalog-only confidence |
| RL-10 | Design still Draft; no LoopRail RFC | Cannot treat as shipped protocol |

---

## Non-goals (this IG)

- Token/cost budgets (RFC-222 H3) — track separately.
- Distributed multi-daemon claim locks — single-process claim remains.
- Making rails perform git/PR ops as builtins — rails spawn CE goals only;
  StrangeLoop executes work inside those goals.
- Full dreaming/episodic distillation product — P1 may leave dreaming as
  events-only with honest docs; deep distillation is a follow-on IG.
- Changing StrangeLoop invariant: SL executes one goal; rails shape the DAG;
  AutopilotService schedules.

---

## Design principles

1. **One honesty bar**: if a path is stubbed, docs/config/tests must say so —
   or the path must work.
2. **CE remains SoT for goal/step entities**; JobLoopIndex for membership;
   rail trace keyed by `job_id` (IG-RQJ-02 / IG-677).
3. **Events over polls for monitor reactivity**; scheduling may stay poll-based.
4. **RFC-630**: consensus and rail guards use structured LLM output, not
   keyword/substring heuristics.
5. **Persistence rule (AGENTS §10)**: rails/autopilot/CE stores follow
   `persistence.default_backend` — no mixed SQLite+Postgres in one process.
6. **Tests fix the product**, not mocks that hide production TypeErrors.

---

## Phase 0 — Correctness & honesty (blocking)

**Goal:** No silently broken RPCs; monitor wires match the bus; docs stop
overselling.

### Work items

| ID | Work | Closes |
|----|------|--------|
| P0-1 | Make `absorb_guidance` async **or** stop awaiting it in router; add unmocked unit + daemon test that real CE absorbs guidance | CE-2 |
| P0-2 | Inject `guidance_accumulated` into `ContextProjector` / loop prompt builders so next dispatch sees operator text | CE-3 |
| P0-3 | Align Monitor subscriptions with actual bus topics (`INTERNAL_GOAL_*` / CE emit). Prefer: CE lifecycle methods emit internal events AutopilotService already handles | AP-2 |
| P0-4 | Fix WorkerPool: `mark_idle(..., success=False)` must return slot to idle (or quarantine with TTL + reclaim); add unit test for capacity after N failures | AP-4 |
| P0-5 | Surface persist failures: `_persist_goals` / CE `save` escalate after N failures (metric + daemon health); optional fail-closed config | CE-4, AP-10 |
| P0-6 | Doc hygiene: wiki CE page + RFC-624/625 status notes for stubs (callbacks, allow_retry, episodic, dreaming); fix `agent.autonomous.enabled` → `agent.autopilot.enabled` in RFC-222 | CE-6, AP-1, AP-7 |
| P0-7 | Consensus: structured output schema (`accept` / `send_back` / `suspend`) — remove substring match | AP-6 |

### Acceptance (P0)

- [x] `job_guidance` against a live daemon CE succeeds and appears in the next
      worker prompt bundle
- [x] Failing a dispatched goal N times does not permanently shrink
      `max_loops` capacity
- [x] Monitor `goal_failed` / completion handlers fire at least once in a unit
      test with real bus + CE (no string-topic mismatch)
- [x] Consensus uses structured parse; substring path deleted
- [x] Wiki/RFC stub claims removed or marked deferred

---

## Phase 1 — Supervised Autopilot pilot

**Goal:** Cancel, pause, crash, and failure recovery are operator-trustworthy
with `agent.autopilot.enabled: true`.

### Work items

| ID | Work | Closes |
|----|------|--------|
| P1-1 | **Pause**: cascade suspend + cancel in-flight child workers; resume reactivates eligible pending goals | AP-5 |
| P1-2 | **Backoff apply**: `_apply_backoff_decision` mutates CE (retry→pending with budget; leave failed when exhausted — engine health recovers, never `failed→suspended`); honor `max_retries` / `retry_count`. Superseded further by [IG-697](IG-697-engine-deadlock-recovery.md) | AP-3 |
| P1-3 | **Crash budget**: on `recover()`, increment `attempts_after_crash` (or equivalent); respect config cap → suspend/fail | CE-5 |
| P1-4 | **Daemon CE durability model** (choose one, document in RFC-625 errata): (A) give daemon CE real persistence backend matching `default_backend`, or (B) keep snapshot sidecar but also persist minimal ledger/guidance fields and assert ledger SoT remains loop CE. Prefer (A) for “sole SoT” honesty on the DAG | CE-1 |
| P1-5 | RFC-228: implement or explicitly reject `verification_rules`; add ownership checks or document single-tenant assumption | AP-9 |
| P1-6 | Integration: unmocked WS submit → fake-or-real runner → complete/cancel/pause/guidance (daemon fixture without AsyncMock on CE) | AP-8, CE-8 |
| P1-7 | Dreaming: either wire minimal distillation hook **or** disable config defaults / document “events only” until follow-on IG | AP-7 |

### Acceptance (P1)

- [x] `job_pause` stops child workers within one scheduling interval
- [x] Failed goal with remaining retries returns to `pending` and redispatches
- [x] Daemon restart restores DAG + guidance; pending goals redispatch when
      enabled *(crash attempt budget increments; over-budget → suspend)*
- [x] At least one daemon integration test runs real CE (no AsyncMock on
      absorb/create/cancel) — `test_real_ce_guidance_pause.py`
- [x] Dual-CE model documented and consistent with chosen P1-4 option
      *(Option B: daemon CE + snapshot sidecar; loop CE owns ledger)*

### Acceptance (P2)

- [x] `soothe autopilot run "…" --rail feature-dev` / `--rail spike` binds
      interpreter (CLI + WS `rail_id`); spike `job_start` spawns scouts
- [x] Spike rail pauses for human; resume completes without auto-implement
- [x] Maker-checker send-back uses `retry_branch`
- [x] Job-scoped JSONL rail trace under `$SOOTHE_DATA_DIR/loops/{job_id}/`
- [x] No-rail jobs unchanged (Monitor/CE opportunistic path)
- [x] `GoalNode` carries `rail_id` / tags / branch / role
- [x] `verification_rules` stored on goal (RFC-228); single-tenant ownership

---

## Phase 2 — LoopRail product binding

**Goal:** Operator can run `--rail feature-dev` (and builtins) end-to-end;
policy shapes the DAG; StrangeLoop still executes single goals.

### Work items

| ID | Work | Closes |
|----|------|--------|
| P2-1 | Promote LoopRail design → RFC (or attach as RFC-222 amendment); keep draft until RFC status ≥ Proposed | RL-10 |
| P2-2 | `GoalNode` fields: `rail_id`, tags, `branch_id`, `branch_status`, `role` (migrate off `RailJobState` shadow store); persist in DAG snapshot | RL-4 |
| P2-3 | Wire `LoopRailInterpreter` into AutopilotService/Monitor: bind on submit; forward lifecycle events (`job_start`, `goal_completed`, `goal_failed`, `dag_idle`, `user_intervention`) | RL-1 |
| P2-4 | Submit surface: `rail_id` on WS / SDK / CLI (`--rail`) / TUI; config `agent.autopilot.default_rail` + workspace `.rail-default` fallback (no invented `default.yml`) | RL-2, RL-3 |
| P2-5 | `RailSelector` (explicit id → workspace default → config default → no rail) | RL-3 |
| P2-6 | Durable trace: JSONL under job artifact dir keyed by `job_id` (IG-RQJ-02); Postgres rows when `default_backend: postgresql` | RL-7 |
| P2-7 | Human gate: `pause_for_user` → CE suspend + system event; CLI/TUI resume emits `user_intervention` | RL-5 |
| P2-8 | Decompose: LLM/CE plan for scout/impl/review goals (structured); retire hard-coded “Explore facet N” as production default (keep as test fixture) | RL-6 |
| P2-9 | CE `branch_manager` (or equivalent) for `retry_branch` prune+replant; `merge_branches` either implement or remove from catalog verbs | RL-8 |
| P2-10 | Scenario tests: bugfix, hotfix, migration; product-binding test: Service binds rail and fires `job_start` → builtin | RL-9 |
| P2-11 | Config templates: `agent.autopilot.rails` / `default_rail` synced to `soothe.template.yml` + daemon setup templates | RL-2 |

### Acceptance (P2)

- [ ] `soothe autopilot run "…" --rail feature-dev` binds interpreter and
      writes job-scoped rail trace
- [ ] Spike rail pauses for human; resume completes without auto-implement
- [ ] Maker-checker send-back uses `retry_branch` (not only consensus
      send_back on same goal)
- [ ] Restart mid-rail job: `rail_id` + annotations + trace survive; interpreter
      rebinds
- [ ] No-rail jobs unchanged (Monitor/CE opportunistic path)

---

## Phase 3 — Production soak & evidence

**Goal:** Evidence matches the trust claim.

### Work items

| ID | Work | Closes |
|----|------|--------|
| P3-1 | Real Postgres CE integration tests (dag + ledger save/load/recover) under CI service container | CE-7 |
| P3-2 | Crash E2E: enable autopilot → submit multi-goal job → kill daemon → restart → pending redispatched; assert JobLoopIndex `interrupted` + new assignment `loop_id` | CE-8, AP-8 |
| P3-3 | Optional live-runner soak (nightly): one feature-dev rail job against a fixture repo | RL-9, AP-8 |
| P3-4 | Update RFC-222 / 228 / 624 / 625 status sections; archive readiness notes; mark LoopRail RFC | CE-6, RL-10 |
| P3-5 | Operator runbook: enablement, consensus model roles, pause/cancel, rail catalog, crash expectations | — |
| P3-6 | **Blocking predecessor:** land [IG-680](IG-680-autopilot-dag-health-evidence-deps.md) P0 (health remove guards, workspace inherit, consensus evidence) before trusting multi-goal soak results — 2026-08-04 eval showed workspace SUCCESS with job `cancelled` | AP-8, soak honesty |

### Soak finding (2026-08-04) → IG-680

A long-running taskkit eval (auto decompose, 4-wide pool, CLI surface)
produced a correct workspace deliverable but a misleading job terminal status.
Do **not** treat P3-3 green as production-ready until IG-680 P0 accepts:

| Eval ID | Finding | IG-680 |
|---------|---------|--------|
| AH-1 | DAG health cancelled umbrella root (`dag_health_verification`) | P0-1/P0-2 |
| AH-2 | Consensus `send_back` / `no narrative` despite on-disk success; subgoals lost workspace | P0-3…P0-6 |
| AH-3 | Decomposed pipeline had `deps=[none]` | P1 |
| AH-4 | Post-completion over-decompose under design goal | P1 |

### Acceptance (P3)

- [ ] Postgres CE tests green in CI
- [ ] Crash E2E green
- [ ] RFCs and wiki match shipped behavior
- [ ] Runbook linked from wiki autopilot / CE pages
- [ ] IG-680 P0 acceptance met (or explicitly waived with operator risk note)

---

## Suggested implementation order

```text
P0-1,P0-2  guidance fix (fast, high severity)
P0-3       monitor bus alignment
P0-4       worker slot reclaim
P0-7       consensus structured output
P0-5,P0-6  persist honesty + docs
    ↓
P1-1,P1-2  pause + backoff apply
P1-3,P1-4  crash budget + daemon CE durability
P1-5,P1-6,P1-7  RFC-228 + unmocked tests + dreaming honesty
    ↓
P2-1       RFC for rails (can parallelize with P1)
P2-2…P2-11 product binding
    ↓
P3-*       soak evidence
```

---

## Key files (touch list)

| Area | Paths |
|------|--------|
| CE core | `packages/soothe/src/soothe/context/engine.py`, `models.py`, `store_*.py`, `projection.py` |
| Autopilot | `autopilot/service.py`, `monitor.py`, `worker_pool.py`, `consensus.py`, `context_projector.py` |
| Rails | `autopilot/rail/*`, `rails/catalog.py`, `rails/builtin_rails/*` |
| Daemon | `soothe-daemon/server/core.py`, `protocol/router.py` |
| CLI / client | `soothe-cli/.../autopilot_cmd.py`, SDK `AutopilotSubmitParams` |
| Config | `config/soothe.template.yml`, daemon setup templates, `config/models.py` |
| Tests | `tests/unit/context/`, `tests/unit/core/autopilot/`, `tests/unit/rails/`, `soothe-daemon/tests/integration/autopilot/`, new `tests/integration/context/` |
| Specs | `docs/specs/RFC-222/228/624/625`, LoopRail draft → RFC, `docs/wiki/core/context-engine.md` |

---

## Verification

After each phase (and before commit):

1. Cleanse related dead stubs/mocks introduced by the phase (AGENTS rule 6).
2. `./scripts/verify_finally.sh`
3. Phase-specific acceptance checkboxes above.

Do **not** “fix” tests by AsyncMocking away production TypeErrors (CE-2 lesson).

---

## Exit criteria (IG complete)

All of the following hold:

1. Solo CE and Autopilot supervised pilot paths have no known broken RPCs or
   dead event wires.
2. Operators can opt into rails via `--rail` / config; no-rail path preserved.
3. Crash, pause, cancel, guidance, and retry behaviors match runbook.
4. Postgres and crash E2E evidence exist.
5. Specs/wiki no longer claim unimplemented APIs.

When exit criteria are met, set this IG **Status: Implemented** and file any
remaining dreaming/distillation or cost-budget work as follow-on IGs.

**Follow-on (filed):** [IG-680](IG-680-autopilot-dag-health-evidence-deps.md) —
DAG health guardrails, consensus evidence grounding, decompose dependency
wiring, and post-completion decompose budget.
