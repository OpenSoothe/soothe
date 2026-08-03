# Rail Trace Continuity Across Loop Boundaries — Analysis

**Status**: Clarification memo (design review of `docs/drafts/2026-07-11-loop-rail-design.md`)
**Date**: 2026-08-03 (updated 2026-08-04 for IG-677)
**Related**: LoopRail design draft §7, [IG-677](IG-677-autopilot-job-loop-index.md),
RFC-222 / RFC-228

> **IG-677 update**: Autopilot no longer recycles `autopilot__wNNN` as the
> filesystem `loop_id`. Each assignment is `autopilot__{job_id}__{uuid}` under
> `data/loops/{loop_id}/`, with durable membership in `JobLoopIndex`. That
> makes loops **job-attributable**, but a job still spans **many** assignment
> loops — so rail traces must remain keyed by **`job_id`**, not by assignment
> `loop_id`. The conclusions below still hold; code citations for `wNNN` are
> historical.

---

## 1. Question

Does rail trace data persist or inherit across goal decomposition and sub-loops?

Specifically: when `decompose_parallel` spawns child goals that run on separate
assignment loops (each with its own `loop_id`), does the rail trace — the
append-only `RuleFireRecord` list — survive those loop boundaries? And when
`retry_branch` salvages completed work via `informs` edges, does the pruned
branch's trace history carry forward?

---

## 2. Short answer

**Yes — key the trace on `job_id` (root goal ID), not assignment `loop_id`.**

Even after IG-677, `loop_id` names one StrangeLoop assignment
(`autopilot__{job_id}__{uuid}`). A single job DAG spans many such assignments.
If the rail trace were stored under each assignment dir, it would fragment
across workers and would not be a single job-scoped log.

The trace must be keyed to the **job root goal ID**. The rail interpreter is
job-scoped — it subscribes to `goal_*` events for one job's DAG, regardless of
which assignment loop executes each goal. Prefer
`~/.soothe/data/loops/{job_id}/rail_trace.jsonl` (job artifact dir) or Postgres
`rail_trace` rows keyed by `job_id` — never
`data/loops/autopilot__{job_id}__{uuid}/rail_trace.jsonl`.

---

## 3. Evidence from the codebase

### 3.1 Assignment `loop_id` ≠ job id (IG-677)

**`packages/soothe/src/soothe/autopilot/worker_pool.py`** allocates:

```python
loop_id = f"autopilot__{job_id}__{uuid.uuid4().hex}"
```

Pool **slots** (`autopilot__slot_NNN`) are reusable capacity; each claim binds a
**new** assignment `loop_id` + runner. `JobLoopIndex` records membership under
`autopilot:job_loops:{job_id}`. Live pointer while running:
`GoalNode.assigned_loop_id` (cleared when the assignment ends).

A loop is stamped on the goal at claim time and cleared when the assignment ends:
```python
claimed = self._ce.claim_goal(goal.id, loop_id=worker.loop_id)
# ...
goal.assigned_loop_id = None
```

### 3.2 One job's DAG spans multiple assignment loops

The scheduling loop dispatches each ready goal to an available **slot**
(sticky-affinity preference, not hard binding). Each dispatch allocates a new
assignment `loop_id`:

**`WorkerPool.pick_worker(goal, *, job_id)`** preference order:
1. Explicit `prefer` (slot_id or last loop_id) if idle
2. Sticky: idle slot that recently ran a parent
3. Any idle slot (LRU) — **new** `loop_id` on rebind
4. Spawn new slot under `max_loops`

A `decompose_parallel` job with 3 scout goals may use 3 assignment loops
(`autopilot__{job}__{uuid1..3}`), possibly on 1–3 pool slots. Each goal gets its
own `loop_id`; membership is listed in `JobLoopIndex`.

### 3.3 The job identity is the root goal ID

The codebase already treats the root goal ID as the "job_id" for DAG traversal:

**`packages/soothe/src/soothe/autopilot/service.py:1076-1083`**
```python
async def dag_snapshot(self, root_goal_id: str) -> dict[str, Any]:
    """Export DAG structure for visualization (RFC-228).
    ...
    Args:
        root_goal_id: Root goal ID (job_id) to traverse from.
```

**`packages/soothe/src/soothe/context/models.py:223-225`** — DAG relationships:
```python
parent_id: str | None = None
depends_on: list[str] = Field(default_factory=list)
informs: list[str] = Field(default_factory=list)
```

The root goal is the stable job-scoped anchor. Child goals reference it via `parent_id` chains and `depends_on`/`informs` edges.

### 3.4 No `job_id` or `rail_id` fields exist yet on GoalNode

The design draft (§5.2) proposes adding `rail_id`, `rail_version`, and a "rail trace ref on job root" to the goal model. These fields do not yet exist:

```python
# context/models.py — GoalNode has no job_id, rail_id, or trace_ref fields
# Only cron_job_id exists (RFC-229), which is a different concept
cron_job_id: str | None = None
```

### 3.5 Context projection (informs) already works cross-loop

The salvage mechanism — `informs` edges flowing context to replacement branches — already operates cross-goal, not cross-loop:

**`packages/soothe/src/soothe/autopilot/context_projector.py:79`**
```python
parent_ids = list(goal.depends_on) + list(goal.informs)
```

`GoalDispatchContextBundle` is projected from goal IDs (not loop IDs). This means salvage context flows correctly across worker boundaries today. The rail trace must follow the same pattern: keyed to the job's goal DAG, not to individual worker loops.

---

## 4. Design gap (pre-fix) and remaining rule

Early draft text keyed the SQLite trace at
`data/loops/{loop_id}/rail_trace.jsonl`. That is wrong even after IG-677:

| Issue | Explanation |
|-------|-------------|
| One job → many assignment `loop_id`s | Parallel scouts / retries each get `autopilot__{job}__{uuid}` dirs; a per-loop trace would fragment. |
| Assignment dirs are StrangeLoop runtime | Checkpoints / `runner.log` live there; rail soft-state is job-wide and must not ride a single assignment. |
| Slot reuse ≠ loop_id reuse (IG-677) | Slots recycle; assignment `loop_id`s do not — but that still does not make `loop_id` a job SoT. |
| `RailSnapshot` is job-scoped | Snapshot's first field is `job_id`; persistence must match. |

The draft now uses `data/loops/{job_id}/rail_trace.jsonl` (job artifact dir,
distinct from `autopilot__{job_id}__{uuid}` assignment homes). Keep that rule.

---

## 5. Recommended resolution

### 5.1 Key the trace to `job_id` (root goal ID), not `loop_id`

**Persistence path:**
```
~/.soothe/data/loops/{job_id}/rail_trace.jsonl
```

Where `job_id` = root goal ID of the autopilot job. This is:
- **Stable**: survives worker spawn/release cycles
- **Job-scoped**: one trace file per job, regardless of how many workers execute its goals
- **Consistent with `RailSnapshot.job_id`**: the in-memory data model already uses `job_id`

**On `GoalNode` (per §5.2 of the design, not yet implemented):**
```python
# Proposed additions to GoalNode (context/models.py)
rail_id: str | None = None           # Rail bound to this job (root only)
rail_version: str | None = None      # Semver of bound rail
# Trace is keyed by root goal ID; no per-goal trace_ref needed
```

### 5.2 Trace is single-writer (the rail interpreter), not per-worker

The LoopRail interpreter is **bound to the job root** (design §3: "interpreter bound to job root goal"). It is the sole writer of `rail_trace.jsonl`. Workers (StrangeLoop instances) do not write trace records — they emit `goal_*` events that the interpreter consumes.

```
Job root (job_id)
  └── LoopRailInterpreter (sole trace writer)
        ├── subscribes to goal_completed, goal_failed, etc.
        ├── evaluates conditions (LLM guards)
        ├── invokes CE built-ins (decompose_parallel, retry_branch, ...)
        └── appends RuleFireRecord to {job_id}/rail_trace.jsonl
              ↑
              Workers emit events → interpreter writes trace
              Workers never touch the trace file
```

This means:
- **No cross-loop trace fragmentation**: the interpreter writes one append-only file regardless of which worker executed the goal.
- **No trace inheritance needed for decomposition**: `decompose_parallel` creates child goals in the same DAG, under the same `job_id`. The interpreter continues tracing the same job. Child goals running on different workers emit events back to the same interpreter.
- **Trace survives `retry_branch`**: pruning a branch does not delete the trace. The pruned branch's `RuleFireRecord` entries remain in the append-only log. The replanted branch adds new entries. The `informs` mechanism carries *salvaged context* (goal summaries, findings) — not trace records — to the new branch.

### 5.3 What does NOT inherit across boundaries

| Artifact | Crosses loop boundary? | Mechanism |
|----------|------------------------|-----------|
| Rail trace (`RuleFireRecord` list) | N/A — job-scoped, never per-loop | Single file at `{job_id}/rail_trace.jsonl` |
| Salvaged context (findings, plan steps) | Yes — via `informs` edges | `GoalDispatchContextBundle` projection (`context_projector.py`) |
| StrangeLoop checkpoint (message ledger) | No — per `loop_id` (RFC-225 §4) | Workers are isolated; checkpoint stays in `{loop_id}/` |
| LangChain checkpointer (raw messages) | No — per `thread_id` (RFC-223) | Thread isolation by design |
| Branch state (`active`/`pruned`/`suspended`) | Yes — CE-owned, not loop-owned | `branch_manager.py` (proposed) operates on goal DAG, not loops |

### 5.4 `RailSnapshot` reconstruction is always from the job root

The design §7 states the snapshot is "reconstructable from: active/pruned branches + append-only `RuleFireRecord` list." Both inputs are job-scoped:

- **Branch list**: derived from the goal DAG under the root goal (traversing `parent_id` / `depends_on` / `informs` edges). CE owns this; no `loop_id` involvement.
- **Fired rules**: read from `{job_id}/rail_trace.jsonl`. One file, one job, one interpreter.

Reconstruction does not require visiting multiple `loop_id` directories.

---

## 6. Edge cases and implications

### 6.1 Worker reuse across jobs

If assignment loop `autopilot__J1__{uuidA}` runs goal A for job J1, then a later
assignment `autopilot__J2__{uuidB}` runs goal B for job J2:

- **Wrong**: writing rail traces under each assignment dir fragments / couples
  soft-state to StrangeLoop runtime.
- **Correct**: J1 → `data/loops/{J1}/rail_trace.jsonl` (or Postgres `job_id=J1`);
  J2 similarly. `JobLoopIndex` lists which assignment dirs belong to each job.

### 6.2 Job root metadata (design §5.2)

The design says "rail trace ref on job root" — a pointer to the trace store. This is the root goal's ID itself (the path is derivable: `{job_id}/rail_trace.jsonl`). No separate `trace_ref` field is needed if the convention is `job_id` → path. If an explicit field is desired for clarity:

```python
# On root GoalNode only
rail_trace_path: str | None = None  # e.g. "data/loops/{self.id}/rail_trace.jsonl"
```

But this is redundant with the derivable convention. Prefer no field and derive the path.

### 6.3 Persistence backend consistency (AGENTS.md §10)

If `persistence.default_backend: postgresql`, the rail trace should NOT live in a filesystem `jsonl` file. It should be a Postgres table:

```sql
CREATE TABLE rail_trace (
    job_id   TEXT NOT NULL,
    seq      BIGINT NOT NULL,  -- append ordering
    record   JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, seq)
);
```

The current design's `jsonl` path assumes SQLite mode. For Postgres mode, follow AGENTS.md §10: "New persistence features MUST branch on `persistence.default_backend`."

### 6.4 Trace retention and bounded growth

Design §7 mentions "bounded retention" but does not specify bounds. Recommendation:
- **Per-job cap**: `max_rule_fires_per_job` (default 1000) — after which oldest entries are evicted.
- **Global cap**: `max_trace_files` (default 500) — LRU eviction of `{job_id}/` directories.
- **Postgres mode**: `rail_trace_retention_days` (default 30) — periodic purge.

These belong in `config.yml` under `agent.autopilot.rails.trace_*`, not in rail YAML.

---

## 7. Summary

| Question | Answer |
|----------|--------|
| Does rail trace persist across goal decomposition? | Yes — interpreter is job-scoped; one trace per `job_id` across all assignment loops. |
| Does rail trace inherit into sub-loops? | N/A — key on `job_id`, not assignment `loop_id`. `JobLoopIndex` lists loops; rail does not. |
| Does pruned branch trace carry forward on `retry_branch`? | Append-only log is never pruned. Salvaged *context* flows via `informs`, not via copying rule-fires. |
| Is a per-assignment `{loop_id}` path correct? | No — use `{job_id}` (root goal). IG-677 assignment dirs are StrangeLoop runtime only. |
| What remains for the LoopRail RFC? | Confirm job-keyed SQLite/Postgres paths, CE `rail_id`/`rail_version`, retention config, tests. |

---

## 8. Action items for the LoopRail RFC (when promoted from draft)

1. **§7**: Keep / confirm persistence at `data/loops/{job_id}/rail_trace.jsonl` (job artifact dir), explicit note that this is **not** an IG-677 assignment dir (`autopilot__{job_id}__{uuid}`).
2. **§5.2**: Confirm `rail_id`, `rail_version` on root GoalNode. Drop separate "rail trace ref" (derivable from `job_id`).
3. **Persistence backend**: Postgres `rail_trace` when `default_backend: postgresql` (AGENTS.md §10).
4. **Retention**: Concrete `agent.autopilot.rails.trace_*` config fields.
5. **Tests**: Trace continuity across multiple assignment loops for one job; no mixing across jobs (use `JobLoopIndex` membership).
6. **Cross-ref**: Link [IG-677](IG-677-autopilot-job-loop-index.md) for slot vs assignment `loop_id`.
