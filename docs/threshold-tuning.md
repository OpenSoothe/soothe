---
title: "Threshold Tuning Methodology, Rationale, and Rollback"
description: >-
  Operator guide for tuning Soothe runtime thresholds safely: methodology,
  decision rationale for each threshold family, and rollback procedures.
  Cross-references the config templates and config models that define the
  canonical defaults and validation bounds.
---

# Threshold Tuning Methodology, Rationale, and Rollback

This document is the operator-facing methodology for tuning Soothe runtime
thresholds. It covers *how* to tune, *why* each threshold family has its
default, and *how to roll back* a change that misbehaves in production.

> **Scope.** Thresholds are the numeric knobs that bound agent behavior:
> iteration budgets, context-window overflow, SLA tiers, concurrency caps,
> rate-limit circuit breakers, and notify/escalation timers. This document
> does **not** cover capability config (which providers/tools are enabled)
> or environment config (SQLite vs Postgres). See
> [Common Configuration Patterns](wiki/configuration-guide/common-patterns.md)
> for that axis.

## 1. Where Thresholds Live (Source of Truth)

Treat these as the canonical references. Defaults and validation bounds live
in code; templates show the operator-facing overlay.

| Layer | File(s) | Role |
|-------|---------|------|
| **Defaults + validators** | `packages/soothe/src/soothe/config/models.py` | Pydantic `Field(default=..., ge=..., le=...)` — the hard bounds you cannot exceed |
| **Constants** | `packages/soothe/src/soothe/config/constants.py` | Char-cap registry, `DEFAULT_MAX_ITERATIONS` (99), `DEFAULT_MAX_TOOL_CALLS_PER_STEP` (100) |
| **Host overlay template** | `config/soothe.template.yml` | Operator-facing host thresholds (autopilot budgets, SLA, notify, loop) |
| **Nano/shared template** | `config/nano.template.yml` | Shared thresholds (context window, rate limit, output caps) |
| **Daemon template** | `config/daemon.template.yml` | Process thresholds (heartbeat, concurrency, GC, query duration) |
| **Packaged copies** | `packages/soothe-daemon/src/soothe_daemon/setup/templates/*.yml` | Synced by `soothed setup`; must mirror the templates above |
| **Develop overlay** | `config/develop/{nano,soothe}.yml` | Local-dev overrides |

> **Config-sync rule (AGENTS.md §2).** When you edit any
> `config/*.template.yml`, you MUST also update the matching
> `config/develop/*.yml` and the packaged copies under
> `packages/soothe-daemon/src/soothe_daemon/setup/templates/`. A change in
> one place that drifts in the others is the most common cause of
> "works on my machine, breaks in prod."

## 2. Tuning Methodology

### 2.1 Principles

1. **One axis at a time.** Soothe config has three independent axes
   (capability, behavior, environment). Threshold tuning touches *behavior*.
   Do not mix a threshold change with a provider swap or a persistence
   backend migration — if the agent misbehaves you will not be able to
   attribute the regression.

2. **Defaults are load-bearing.** Every default encodes a decision (see §3).
   Changing a default without reading its rationale is the leading cause of
   silent regressions. Read the `description=` on the `Field` and the
   rationale in §3 before touching the number.

3. **Respect the validators.** `ge`/`le` bounds in `models.py` are hard
   limits. A value outside them raises a config-load error on boot. If you
   genuinely need to exceed a bound, that is a code change (raise `le`) plus
   a rationale record — not a config-only edit.

4. **Measure before and after.** Use the benchmark scripts
   (`scripts/benchmark_alert_pipeline.py`,
   `scripts/benchmark_plan_generation.py`) and the SLO docs under
   `benchmarks/` to capture a baseline. A threshold change without a
   before/after measurement is a guess.

5. **No keyword heuristics (RFC-630).** Do not introduce new thresholds that
   gate on keyword/regex matching of user text. Content-judgment thresholds
   must use structured light-LLM fields or declarative config rules. If a
   keyword threshold seems required, stop and confirm with the user first.

### 2.2 Procedure

For each threshold change:

1. **Identify the family** (see §3) and read its rationale.
2. **Capture a baseline** with the relevant benchmark or a representative
   production trace.
3. **Edit the template** (`config/<scope>.template.yml`) — set only the
   field(s) in scope.
4. **Sync** the develop overlay and packaged copies (AGENTS.md §2).
5. **Verify locally** — `./scripts/verify_finally.sh` must pass (zero lint,
   all tests, vulture clean). This catches validator-bound regressions.
6. **Canary** — roll to one loop / one autopilot worker before fleet-wide.
7. **Record** the change in the commit message: old value, new value, the
   metric that drove it, and the rollback condition (see §4).

### 2.3 Anti-patterns

- **Tuning to silence an alert.** If `sla.warning_after_seconds` fires, the
  fix is usually the upstream latency, not a larger threshold. Raising the
  threshold hides the symptom and lets the breach escalate to `critical`.
- **Raising `max_iterations` to "let it finish."** Iteration exhaustion is a
  *signal* of a planning or tooling defect. Raising the budget burns tokens
  and delays the terminal. Investigate the terminal reason first.
- **Lowering `context_overflow_threshold_pct` to "compact sooner."** This
  trades token cost for context loss. Compacting at 70% vs 80% discards
  ~10% more working memory per run — measure retrieval quality, not just
  token spend.

## 3. Threshold Families and Decision Rationale

Each family lists the config path, default, validator bounds, the runtime
enforcer, and the rationale that justifies the default.

### 3.1 Iteration & Step Budgets (Behavior axis)

| Field | Path | Default | Bounds | Enforcer |
|-------|------|---------|--------|----------|
| `max_iterations` | `agent.loop.max_iterations` | 99 | 1–500 | `check_limits.py`, `max_iterations_terminal.py`, `strange_loop.py` |
| `max_plan_steps_per_wave` | `agent.loop.max_plan_steps_per_wave` | 10 | 1–50 | `planner.py` |
| `max_subagent_tasks_per_wave` | `agent.loop.max_subagent_tasks_per_wave` | 4 | 0–20 | Execute wave |
| `max_tool_calls_per_step` | `agent.loop.max_tool_calls_per_step` | 100 | — | `check_limits.py` |

**Rationale.** `max_iterations` is shared between interactive loops and
Autopilot workers (Autopilot has no separate budget — see the field
description). The default of 99 (not 100) is deliberate: it leaves headroom
below the validator ceiling so a single emergency override can raise the
budget without a code change. The 1–500 bound exists because values above
500 produce unbounded token spend with diminishing completion probability —
empirically, loops that exceed ~100 iterations are stuck, not progressing.

`max_plan_steps_per_wave` defaults to 10 to cap planning token cost per
wave; the 50 ceiling prevents a single reasoning model call from emitting a
plan larger than the Execute phase can dispatch.

### 3.2 Context Window Management (RFC-224)

| Field | Path | Default | Bounds | Enforcer |
|-------|------|---------|--------|----------|
| `context_window_limit` | `agent.loop.context_window_limit` | 200,000 | 10,000–1,000,000 | `context_window_manager.py` |
| `context_overflow_threshold_pct` | `agent.loop.context_overflow_threshold_pct` | 0.80 | 0.50–0.95 | `context_window_manager.py` |
| `context_compaction_target_pct` | `agent.loop.context_compaction_target_pct` | 0.60 | 0.30–0.70 | `context_window_manager.py` |
| `step_context_check_enabled` | `agent.loop.step_context_check_enabled` | false | — | `context_window_manager.py` |

**Rationale.** Overflow triggers in-place compaction at 80% of the context
limit. The 80% default balances two failure modes: too low (compacts
prematurely, discards working memory, degrades retrieval quality) and too
high (risks a hard model context error on the next wave). The compaction
target of 60% leaves a 20-point buffer for the next Execute wave before
re-triggering — this is why the target is not 50% (too aggressive) or 70%
(too little headroom, re-triggers within one wave).

The 0.50–0.95 overflow bound is asymmetric to the 0.30–0.70 target bound on
purpose: overflow must always be strictly greater than target, otherwise
compaction would immediately re-trigger. The validators enforce this
invariant at the model level.

`step_context_check_enabled` defaults false because step threads
(`loop_id__step_{step_id}`) are short-lived; checking them adds overhead
with no benefit in the common case.

### 3.3 SLA Tiers (Autopilot)

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `warning_after_seconds` | `autopilot.sla.warning_after_seconds` | 3600 | `sla/monitor.py` |
| `critical_after_seconds` | `autopilot.sla.critical_after_seconds` | 7200 | `sla/monitor.py` |
| `breach_after_seconds` | `autopilot.sla.breach_after_seconds` | 14400 | `sla/monitor.py` |

**Rationale.** Tiers are strictly ordered (warning < critical < breach) and
the `SlaConfig` validator enforces this ordering at load time. The defaults
follow a 1× / 2× / 4× cadence (1h, 2h, 4h) so each tier doubles the
allowable latency — this gives operators a geometric, predictable
escalation curve rather than arbitrary numbers. Do **not** invert the
ordering or collapse two tiers to the same value; the validator rejects
this, but even within bounds, collapsing tiers defeats the graduated
alerting intent.

### 3.4 Autopilot Budgets

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `max_retries` | `autopilot.max_retries` | 2 | Autopilot dispatch |
| `max_total_goals` | `autopilot.max_total_goals` | 99 | GoalEngine |
| `max_goal_depth` | `autopilot.max_goal_depth` | 5 | GoalEngine |
| `max_parallel_goals` | `autopilot.max_parallel_goals` | 3 | GoalEngine |
| `max_send_backs` | `autopilot.max_send_backs` | 3 | Rails |
| `max_engine_recoveries` | `autopilot.max_engine_recoveries` | 2 | GoalEngine |
| `checkpoint_interval` | `autopilot.checkpoint_interval` | 10 | Persistence |

**Rationale.** `max_total_goals` mirrors `max_iterations` (99) for the same
reason — headroom below a round ceiling. `max_goal_depth` of 5 bounds
recursive goal decomposition: deeper than 5 levels, the goal tree becomes
unmanageable and the leaf goals lose context from the root. `max_retries`
and `max_engine_recoveries` are both 2 (not 3) because a third retry on a
failing goal is almost always a deterministic failure that retries will not
fix — better to surface it than burn the budget.

### 3.4a Loop Pool Capacity (RFC-222)

Distinct from the Autopilot budgets above: these cap the StrangeLoop *worker
pool*, not the goal scheduler. A loop can be reused across parent→child
lineage, so pool capacity and scheduled parallelism are independent axes.

| Field | Path | Default | Bounds | Enforcer |
|-------|------|---------|--------|----------|
| `max_loops` | `autopilot.max_loops` | 16 | 1–32 | `WorkerPool` |
| `loop_idle_timeout` | `autopilot.loop_idle_timeout` | 300 | ≥10 | `WorkerPool` |
| `auto_resume_max_loops` | `persistence.auto_resume_max_loops` | 16 | 1–64 | Daemon startup |

**Rationale.** `max_loops` (16) is sized for ~2 Autopilot jobs at
`max_parallel_goals=3` plus ~3 interactive CLI StrangeLoops, with headroom
for parent→child reuse without pool starvation. It is deliberately larger
than `max_parallel_goals` (3) because scheduled goals reuse loops rather
than each spawning a fresh worker. The 32 ceiling prevents unbounded thread
growth under a misconfigured fleet. `loop_idle_timeout` (300s) keeps a warm
loop around for reuse within a 5-minute window — short enough to release
memory between bursts, long enough to amortize loop spin-up cost across
rapid successive dispatches. `auto_resume_max_loops` (16) caps concurrent
startup resume so a crashed daemon with many incomplete loops does not
thunder the provider on restart.

### 3.5 Rate-Limit Circuit Breaker

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `consecutive_rate_limit_threshold` | `agent.loop.thread_switch_policy.consecutive_rate_limit_threshold` | 3 | `check_limits.py` |
| `enabled` | `agent.loop.llm_rate_limit.enabled` | true | Rate-limit gate |

**Rationale.** The circuit breaker trips after 3 consecutive rate-limit hits
on a thread and switches threads rather than retrying in place. The value 3
is the threshold below which transient rate limits (a single burst) are
absorbed without a thread switch, and above which the failure is likely
sustained (quota exhausted) so switching is cheaper than retrying. See
IG-729 (rate-limit loop safety) and the archived IG-499/IG-501 for the
tuning history that settled on 3.

### 3.6 Notify & Escalation

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `suspend_after_seconds` | `autopilot.notify.suspend_after_seconds` | 2700 | `notify/router.py` |
| `suspend_escalation_multiplier` | `autopilot.notify.suspend_escalation_multiplier` | 2.0 | `notify/router.py` |
| `dedup_ttl_seconds` | `autopilot.notify.dedup_ttl_seconds` | 86400 | `notify/router.py` |

**Rationale.** `suspend_after_seconds` (2700s = 45min) is set below the SLA
warning tier (3600s) so that a stuck goal suspends *before* it breaches SLA
— the notify subsystem is the early-warning layer, SLA is the enforcement
layer. The escalation multiplier of 2.0 means a second suspension window is
twice as long (90min) before re-escalating, giving the upstream cause time
to resolve. `dedup_ttl_seconds` of 24h prevents alert storms on a flapping
goal.

### 3.7 Verify & Rails

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `verify_interval` | `autopilot.verify_interval` | 120 | Verify scheduler |
| `verify_idle_interval` | `autopilot.verify_idle_interval` | 300 | Verify scheduler |
| `verify_llm_min_nonterminal` | `autopilot.verify_llm_min_nonterminal` | 1 | `verify/consensus.py` |
| `rail_auto_pick_min_confidence` | `autopilot.rail_auto_pick_min_confidence` | 0.6 | Rails |
| `rail_auto_pick_timeout_s` | `autopilot.rail_auto_pick_timeout_s` | 120 | Rails |

**Rationale.** `rail_auto_pick_min_confidence` of 0.6 is the threshold
above which a rail is auto-selected without human confirmation. Below 0.6
the classification is ambiguous and forcing an auto-pick risks dispatching
the wrong rail; the human is kept in the loop. See IG-728 for the
confidence-threshold rationale.

### 3.8 Completion & Scenario Heuristics

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `dag_dependency_threshold` | `agent.loop.completion_rules.dag_dependency_threshold` | 3 | `planning_completion.py` |
| `low_success_rate_threshold` | `agent.loop.completion_rules.low_success_rate_threshold` | 0.6 | `planning_completion.py` |
| `ledger_direct_max_tool_calls` | `agent.loop.completion_rules.ledger_direct_max_tool_calls` | 50 | `planning_completion.py` |
| `high_step_count_threshold` | `agent.loop.scenario_rules.high_step_count_threshold` | 4 | `scenario_classifier.py` |
| `low_evidence_volume_threshold` | `agent.loop.scenario_rules.low_evidence_volume_threshold` | 2000 | `scenario_classifier.py` |

**Rationale.** These are *structural* thresholds (step counts, evidence
volume, DAG fan-out) — deterministic rules, not content judgment, so they
are compliant with RFC-630's "no keyword heuristics" rule. They gate which
completion path and which scenario fast-path the loop takes.
`high_step_count_threshold` of 4 separates simple (≤4 steps) from complex
scenarios; above it the classifier engages the heavier reasoning path.

### 3.9 Daemon Process Thresholds

| Field | Path | Default | Enforcer |
|-------|------|---------|----------|
| `heartbeat_interval_ms` | `daemon.heartbeat_interval_ms` | 30000 | WS server |
| `heartbeat_timeout_ms` | `daemon.heartbeat_timeout_ms` | 10000 | WS server |
| `max_concurrent_threads` | `daemon.max_concurrent_threads` | 100 | Thread dispatch |
| `max_concurrent_dispatches` | `daemon.max_concurrent_dispatches` | 50 | Dispatch pool |
| `max_query_duration_minutes` | `daemon.max_query_duration_minutes` | 1440 | `query/engine.py` |
| `stale_running_seconds` | `daemon.loop_status_reconciliation.stale_running_seconds` | 180 | Reconciliation |
| `log_growth_threshold_mb` | `daemon.log_growth_threshold_mb` | 100 | `memory_profiler.py` |

**Rationale.** `heartbeat_timeout_ms` (10s) is intentionally less than
`heartbeat_interval_ms` (30s) is *not* the case — the timeout is the
allowable gap *between* beats, so it is smaller than the interval to detect
a dead connection within one beat cycle. `max_query_duration_minutes` of
1440 (24h) bounds a single query's wall-clock; beyond this the query is
reaped as runaway. `stale_running_seconds` of 180 means a loop stuck in
`running` without a heartbeat for 3 minutes is reconciled — short enough to
catch a dead worker, long enough to avoid false positives during GC.

### 3.10 Char-Cap Registry (Output Boundaries)

Defined in `config/constants.py`. Selected entries:

| Constant | Default | Purpose |
|----------|---------|---------|
| `DEFAULT_MAX_FIELD_CHARS` | 2000 | Generic field truncation |
| `PRIOR_PROGRESS_MAX_CHARS` | 25000 | Prior-progress context bound |
| `VISION_CONTEXT_MAX_CHARS` | 4000 | Vision evidence cap |
| `CONTINUATION_ASSESS_REASONING_MAX_CHARS` | 240 | Continuation reasoning bound |
| `GOAL_PREVIEW_MAX_CHARS` | 120 | Goal preview truncation |

**Rationale.** These are output-shaping caps, not behavior gates. They
exist to keep prompts within the model's input budget and to produce
deterministic truncation (so two runs of the same trace yield the same
prompt). Changing them affects token cost and retrieval quality, not
control flow.

### 3.11 Nano-Owned Middleware Thresholds (cross-reference)

The following threshold families are **defined in the `soothe-nano` PyPI
package**, not in this monorepo's `config/models.py`. They appear in
`config/nano.template.yml` as operator-facing overlays, but their defaults
and validators live upstream. Tune them per the nano package's own docs;
this section records *which knobs exist* and *what they bound* so operators
have a single index. Do not edit the nano template here without
re-releasing `soothe-nano` — the packaged copy under
`packages/soothe-daemon/src/soothe_daemon/setup/templates/nano.yml` is a
mirror, not the source of truth.

| Family | Key fields (nano.yml path) | Bounds |
|--------|----------------------------|--------|
| **LLM rate limiter** | `agent.middleware.llm_rate_limit.{rpm_limit, concurrent_limit, global_concurrent_limit, call_timeout_seconds, call_timeout_max_seconds, max_timeout_retries, timeout_retry_multiplier, max_rate_limit_retries, rate_limit_backoff_base, rate_limit_backoff_max, rate_limit_retry_timeout_seconds}` | Sized for ~2 Autopilot jobs + ~3 CLI StrangeLoops (`rpm_limit=180`, `concurrent_limit=4`, `global_concurrent_limit=18`) |
| **Tool timeout** | `agent.middleware.tool_timeout.{default_seconds, per_tool.<tool>, skip_tools_with_internal_timeout}` | `default=60s`; per-tool overrides (e.g. `grep`/`read_file=30s`, `browser_use=1800s`, `task=18000s`) |
| **Tool call limit** | `agent.middleware.tool_call_limit.{global_thread_limit, global_run_limit, tool_specific_limits.<tool>.{thread_limit, run_limit}}` | `global_thread_limit=200`, `global_run_limit=200`; network tools capped at 5/thread, 3/run |
| **Tool retry** | `agent.middleware.tool_retry.{max_retries, backoff_factor, initial_delay}` | `max_retries=3`, `backoff_factor=2.0`, `initial_delay=1.0` |
| **Report output** | `agent.middleware.report_output.{display_threshold, preview_chars, synthesis_max_chars}` | `display_threshold=20000`, `preview_chars=500` |
| **Code interpreter** | `agent.code_interpreter.{memory_limit_mb, timeout_seconds, max_ptc_calls, max_result_size}` | `memory_limit_mb=128`, `timeout_seconds=30`, `max_ptc_calls=50`, `max_result_size=100000` |
| **Context window (nano side)** | `agent.middleware.context_window_limit` | `200000` — mirrored by the host `agent.loop.context_window_limit` in §3.2; keep them aligned |

**Tuning note.** The LLM rate limiter is the most common source of
operator-visible regressions: raising `concurrent_limit` without raising
`global_concurrent_limit` (or vice versa) produces silent queueing. The two
are a *pair* — `concurrent_limit` bounds per-thread in-flight calls,
`global_concurrent_limit` bounds process-wide. Raise both together, and
confirm the provider's RPM quota supports the new `rpm_limit` before
deploying.

## 4. Rollback Procedures

### 4.1 General Rollback (config-only change)

If the change was config-only (no code), rollback is a revert + restart:

1. **Revert the template edit.**
   ```bash
   git revert <commit-sha>
   # or, for an uncommitted change:
   git checkout -- config/<scope>.template.yml
   ```
2. **Re-sync** the develop overlay and packaged copies if the revert did not
   touch them (it should have, if you followed §2.2 step 4).
3. **Restart the daemon** to reload config:
   ```bash
   soothed restart
   ```
4. **Confirm** the threshold reads back the prior value:
   ```bash
   soothe admin config show agent.loop.max_iterations
   ```

Config-only rollbacks are safe and immediate because thresholds are read at
boot; no migration and no state cleanup is required.

### 4.2 Rollback After a Validator-Bound Change

If you raised a validator bound (`ge`/`le` in `models.py`) to permit a new
value, the rollback has two parts:

1. **Revert the code** (`models.py` bound) and the config (the template
   value). The code revert must land first, otherwise the config value will
   fail validation on boot.
2. **Run `./scripts/verify_finally.sh`** — the validator tests will confirm
   the bound is restored.

### 4.3 Rollback of a Threshold That Produced Bad State

Some thresholds, once raised, leave behind state that the lower threshold
would not have permitted:

- **`max_goal_depth` raised then lowered** — existing goals deeper than the
  new bound remain in the store; they are not retroactively rejected. To
  clean up, cancel the over-depth goals via the admin RPC or let them
  complete naturally. Do **not** delete goal records directly.
- **`max_parallel_goals` raised then lowered** — in-flight parallel goals
  continue to completion; the lower bound applies only to *new* dispatch.
- **`context_overflow_threshold_pct` lowered then raised** — already-
  compacted context is not restored. The next run uses the new (higher)
  threshold fresh.

Rule: **threshold rollbacks are forward-effective, not retroactive.** They
constrain new work; they do not rewrite history. If the bad state must be
purged, use the admin RPCs, not direct DB writes.

### 4.4 Canary Rollback

If the change was canaried to one loop/worker:

1. **Drain the canary** — stop dispatching new work to the canary instance.
2. **Revert config** on the canary only.
3. **Restart** the canary.
4. **Compare** the canary's metrics against the fleet baseline before
   fleet-wide rollout. If the canary regressed, the fleet is unaffected —
   this is the point of canarying.

### 4.5 Rollback Decision Criteria

Roll back immediately if any of:

- SLA breach rate exceeds the pre-change baseline by >20%.
- A loop that previously terminated now exhausts `max_iterations` (the
  terminal reason is a signal, not a failure to retry).
- Context-compaction frequency changes by >2× (in either direction — too
  much compaction loses memory, too little risks hard context errors).
- Rate-limit circuit-breaker trips per hour exceeds the baseline by >50%.

Do not "wait and see" past one SLA cycle (4h by default). A threshold
regression compounds: a stuck goal holds a dispatch slot, which reduces
effective parallelism, which raises latency on *other* goals.

## 5. Change Record Template

Append to the commit message of every threshold change:

```
threshold-change:
  field: agent.loop.max_iterations
  old: 99
  new: 120
  family: iteration-budget
  metric: loop-exhaustion rate on deep-research goals (baseline 3% → 1.2%)
  rollback-condition: loop-exhaustion rate returns to ≥3% OR token spend/loop rises >15%
  validator-bound: no
  synced: config/develop/soothe.yml, packages/soothe-daemon/.../templates/soothe.yml
```

This record is the rollback contract: the `rollback-condition` is the
objective signal to revert, evaluated against the `metric` baseline.

## 6. Related Documentation

- [YAML Reference](wiki/configuration-guide/yaml-reference.md) — field-level reference
- [Common Configuration Patterns](wiki/configuration-guide/common-patterns.md) — recipe catalog
- [Environment Variables](wiki/configuration-guide/environment-variables.md) — env-var overrides
- [Monitoring](wiki/deployment/monitoring.md) — SLA observability
- [Scaling](wiki/deployment/scaling.md) — concurrency caps
- [StrangeLoop](wiki/core/strangeloop.md) — iteration budget narrative
- [Context Engine](wiki/core/context-engine.md) — context window thresholds

Prior tuning history is captured in the IG/RFC corpus; the most relevant
records for threshold rationale are RFC-224 (context window), RFC-213
(reasoning quality), RFC-630 (no-keyword-heuristics rule), IG-729
(rate-limit loop safety), IG-728 (rail auto-pick confidence), and the
archived IG-499/IG-501 (rate-limit retry tuning) and IG-301/IG-319 (LLM
call timeout tuning).
