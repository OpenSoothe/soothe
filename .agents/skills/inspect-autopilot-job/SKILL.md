---
name: inspect-autopilot-job
description: >-
  Inspect Soothe autopilot jobs: goal DAG structure, LoopRail conformance,
  parallelism scorecard, consensus/send_back, engine deadlock recovery, and
  goal execution history (job_loops attempts, wall times, phase timeline from
  rail_trace). Use when the user names a job id, asks about rail/pool/DAG
  stuck goals, low parallelism, feedback cycles, or wants execution history
  of an autopilot job or its goals.
---

# Inspect Autopilot Job

Job-scoped forensics for Autopilot + LoopRail. For single-loop StrangeLoop /
tools / plans / skills, use [diagnose-loop](../diagnose-loop/SKILL.md)
Workflow B on hot `autopilot__{job}__*` loops.

Prefer `.venv/bin/soothe` when available.

## When to Use

- Job id / 8-char prefix / child goal id under a rail job
- Low parallelism, pending implement goals, rail not advancing
- Integrate / commit / review / QA / feedback stuck
- “What happened on this job?” / DAG structure / execution history
- Consensus send_backs, engine recoveries, pruned makers

## Data Sources

| Source | Path / command | Use |
|--------|----------------|-----|
| Live DAG | `soothe autopilot job\|goal\|status\|top` | Current status (authoritative when daemon up) |
| Job contract | `~/.soothe/data/jobs/{job}/GOAL.md` | Submit description snapshot (IG-702) |
| Rail state | `~/.soothe/data/jobs/{job}/rail_state.json` | `rail_id`, wave/feedback rounds, annotations (role/tags/branch) |
| Rail trace | `…/jobs/{job}/rail_trace.jsonl` (legacy: `loops/{job}/`) | Builtin fires + guards; phase timeline |
| Job↔loops | `persist.db` `autopilot:job_loops:{job}` (ns `autopilot_goals`) | Per-goal attempt history + wall times |
| Goals snapshot | `persist.db` `autopilot:goals:snapshot` | Offline DAG (may lag live CE) |
| Dispatch logs | `soothe.log*`: `dispatched goal`, `Consensus`, `Sent goal`, `Engine recovering` | Send_backs / recovery |
| Worker logs | `~/.soothe/data/loops/autopilot__{job}__*/runner.log` | Per-attempt StrangeLoop detail |

SQLite keys use **namespace** `autopilot_goals`:

```bash
sqlite3 ~/.soothe/data/databases/persist.db \
  "SELECT data FROM soothe_kv WHERE namespace='autopilot_goals' AND key='autopilot:job_loops:$JOB';"
```

## Workflow

```text
1. Resolve job id (C0)
2. Live DAG + rail_state annotations (structure)
3. Goal execution history (job_loops + phases)  ← required
4. Parallelism scorecard
5. Rail conformance (builtin seq vs rail YAML)
6. Failure / recovery modes
7. Optional: diagnose-loop Workflow B on hot loops
```

### 0. Resolve job identity

```bash
SOOTHE="${SOOTHE:-soothe}"   # prefer: /path/to/repo/.venv/bin/soothe
$SOOTHE autopilot status
$SOOTHE autopilot jobs
$SOOTHE autopilot job <JOB_ID>
$SOOTHE autopilot goal <GOAL_ID>
```

Filesystem: `~/.soothe/data/jobs/$JOB/`, loops `autopilot__${JOB}__*`.

Record: `rail_id`, workspace, root `depends_on`, children, pool `active/idle/max`, `job_loops.active_loops`.

### 1. Goal DAG structure

Build a depends_on graph from live CLI (preferred) or CE snapshot.

For each goal with `id == JOB` or `parent_id == JOB` (plus orphans under the job):

| Column | Source |
|--------|--------|
| id, description preview | `autopilot job` / `goal` |
| role / rail_tags / branch | `rail_state.annotations` or goal fields |
| status | pending/active/completed/failed/cancelled/suspended |
| depends_on → status | edge list |
| retry / send_back / engine_recovery | CE snapshot fields |

Also list **pruned** annotations (`branch_status=pruned`) even if absent from CLI tree — they explain `retry_maker` history.

**Report a mermaid or ASCII DAG** of the live pipeline (root gate → phases).

**Root wiring checks:**

- Child must **never** `depends_on` job root (deadlock while root active)
- Root may depend on terminal gate (integrate / QA / feedback verify) — by design
- Flag health rewires that change root deps mid-flight

### 2. Goal execution history (required)

Produce a **phase timeline** and **per-goal attempt ledger**.

#### 2a. Phase timeline from rail_trace builtins

```bash
TRACE=~/.soothe/data/jobs/$JOB/rail_trace.jsonl
test -f "$TRACE" || TRACE=~/.soothe/data/loops/$JOB/rail_trace.jsonl
```

Extract only lines with `builtin` set (ignore pure `dag_idle` no-ops). Report:

```text
seq | event | condition | builtin | result | goal | timestamp
```

Map to phases (streaming greenfield/migration): `plan_milestones` →
`spawn_wave_makers` (spawn-ready) → `merge_branches`* → `review` /
`qa_verify` (per maker) → `spawn_wave_makers` (unblocked slices) →
`spawn_feedback_cycle` → … → `complete_job` (lands `job/<id>/_base`).

Legacy custom rails may still show `spawn_integrate` / `commit_milestone`.

Flag: long gaps between consecutive builtins (hang / deadlock); makers
completed but no `merge_branches`; catalog slices never in `spawned_slices`
while pool idle (deps / spawn-ready miss); early `spawn_feedback_cycle`
before any merge/QA.

#### 2b. Per-goal attempt ledger from `job_loops`

Parse `autopilot:job_loops:{job}` (see [reference.md](reference.md) for script).

Per `goal_id` report:

| Field | Meaning |
|-------|---------|
| n_attempts | Count of loop entries |
| completed / failed | Status counts |
| wall_min | `min(started_at)` → `max(ended_at)` span |
| first→last | UTC time-of-day span |
| active now? | In `active_loops` |

Flag goals with **failed > 0**, wall_min ≫ siblings, or many attempts (thrash).

#### 2c. Consensus / recovery history

```bash
rg "dispatched goal .*($JOB|GOAL)|Sent goal .* send_back|Consensus evaluation|Engine recovering failed goal|Retrying failed goal" \
  ~/.soothe/logs/soothe.log* | tail -100
```

Per goal note: `send_back_count/max`, `retry_count/max_retries`,
`engine_recovery_count/max_engine_recoveries`, last consensus reasoning snippet.

#### 2d. Optional: runner.log slices for hot goals

```bash
for d in ~/.soothe/data/loops/autopilot__${JOB}__*; do
  echo "=== $d ==="
  rg '\[Goal\]|\[Plan\] phase=|Step .* (completed|failed).* in [0-9]+ms|Graph invocation' \
    "$d/runner.log" 2>/dev/null | head -40
done
```

Deep tool/plan waste → [diagnose-loop](../diagnose-loop/SKILL.md) Workflow B.

### 3. Parallelism scorecard

| Question | How |
|----------|-----|
| Ready? | `pending` + all `depends_on` terminal (prefer **completed**, not failed) |
| Active? | `active` + loop in `job_loops.active_loops` |
| Blocked? | Deps unmet; workspace reservation; pool full; dreaming |

```bash
$SOOTHE autopilot status
rg 'dispatched goal|claimed slot|deferred: workspace|No worker capacity|WorkerPool:' \
  ~/.soothe/logs/soothe.log* | tail -60
```

Required:

```text
pool_max=N  pool_active=A  ready_goals=R  active_goals=G  active_loops=L
parallelism_ratio = A / max(1, min(R, N, max_parallel_goals))
```

Flag low parallelism when `R≥2` and `A≤1` longer than ~2× poll interval — unless
serial rail gate (see below).

Same-workspace reservation serializes goals sharing one `workspace`. Greenfield
makers should use distinct `.soothe/worktrees/…`.

**By-design serial phases** (not a bug):

| Rail | Early | Parallel |
|------|-------|----------|
| `feature-dev` | one plan+maker after scouts | scout fan-out |
| `greenfield-system` | `plan_milestones` → one architecture | makers after `architecture_ready` |
| `migration` | same fan-out as greenfield (`plan_milestones` → WavePlan → makers); plus `needs_human` → pause | makers after `architecture_ready`; cutover may pause |

### 4. Rail conformance

1. Resolve YAML: `packages/soothe/.../builtin_rails/<rail_id>.yml`, else
   `~/.soothe/rails/`, else `<workspace>/.soothe/rails/`.
2. Diff builtin sequence vs `flow[].then`.

Full trace dump helper: [reference.md](reference.md).

| Check | Fail means |
|-------|------------|
| `job_start` first builtin | Wrong rail bind |
| Guard never matches | Stuck phase |
| Child → root depends_on | Implement forever pending |
| Review before commit | Gate order broken |
| Idle with waves remaining | Missing `spawn_wave_makers` |

### 5. Failure modes

| Symptom | Likely cause |
|---------|----------------|
| Pool `1/0/N`, one child | Serial rail gate **or** reservation/deps bug |
| Integrate failed, rail idle, root pending | No integrate retry in rail; need engine recovery (`max_engine_recoveries`) |
| `branch_is_stuck` unmatched on `integrate` tags | Rail only retries makers |
| Implement pending forever | Child `depends_on` root still active |
| Many send_backs | Thin consensus evidence |
| Orphan pending under old parents | Stale DAG clutter |
| Makers share workspace | Worktree add failed |
| ~10k+ `dag_idle` no-ops in trace | Deadlock / acceptance unmet spin |
| Feedback diagnose thin → send_back | Agent skipped defect list |

## Output Template

```markdown
## Autopilot job {job_id} (rail={rail_id})

### Summary
Outcome; by-design serial phase vs defect; current phase; severity.

### Goal DAG
ASCII/mermaid + table (id, role, status, deps, retries/sb/erc).
Pruned / orphan notes.

### Execution history
#### Phase timeline
| When | Builtin / event | Goal | Notes |
#### Per-goal attempt ledger
| goal | attempts | ok/fail | wall_min | span | notes |
#### Consensus / recovery
send_backs, engine recoveries, key reasoning snippets.

### Parallelism scorecard
pool_max / active / ready / ratio; worktrees; peak concurrency.

### Rail conformance
Builtin seq vs expected; guard mismatches; bad depends_on.

### Latency
p50/p95 goal wall; ready→dispatch gaps; slowest goals.

### Hot loops (optional)
Pointers to diagnose-loop Workflow B for `autopilot__{job}__*`.

### Recommendations
…
```

## Guardrails

- Do not call early single-goal execution a parallelism bug during serial rail gates.
- Distinguish **ready but not dispatched** (scheduler/reservation) vs **not ready** (deps).
- Prefer `jobs/{id}/rail_trace.jsonl` over legacy `loops/{id}/`.
- Fan-out WavePlan (operator forensics; greenfield + migration): SoT is
  `jobs/{id}/rail_state.json` (`wave_slices` / `decompose_plan`,
  `spawned_slices`, `job_branch`, optional `wave_plan_source_path`).
  Transfer candidates: recommended dumps (`jobs/{id}/wave-plan.json`,
  `<workspace>/.soothe/wave-plan.json`), allowlist paths, structured
  `wave_plan` / `wave_plan_path`, or completion findings JSON.
- **Stuck after architecture, no makers:** planner completed but
  `wave_plan_ready=False` — see Debug Guide “WavePlan / catalog stall”.
  Recovery: supply a **flat** WavePlan via dump/path/blob (`wave_slices`
  string list or flat `slices[]` with optional `depends_on`; nested WAVE
  trees are rejected), or set `wave_slices` on `rail_state.json`, then wait
  for `dag_idle` (or `soothed restart`). Restart after package upgrades so
  streaming spawn + host merge are live.
- **Idle pool, more slices in plan:** not a wave barrier — check
  `spawned_slices` vs catalog and slice `depends_on`; expect
  `merge_branches` after each maker before dependents unlock.
- **Continue job, dump already ready, long planner:** with a current daemon,
  `plan_milestones` should reuse the dump and spawn makers immediately. If the
  planner still rediscovers for tens of minutes, the process predates that
  short-circuit — restart. Nested `independence` objects also fuel rewrite
  thrash; keep independence a string.
- Live CLI beats stale `goals:snapshot` when they disagree.
- Never cite IG-/RFC- ids in user-facing report text.
- Skipping schedule for rail job root is expected.

## Related

- Loop forensics: [diagnose-loop](../diagnose-loop/SKILL.md)
- Scripts / long parsers: [reference.md](reference.md)
- CLI: `soothe autopilot status|jobs|job|goal|goals|top|stop`
- Rails: `packages/soothe/src/soothe/rails/builtin_rails/`
- Debug wiki: `docs/wiki/howto_debug.md`
