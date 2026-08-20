# IG-739: Autoresearch Loop Rail — native execution and prompt fragments

**Created**: 2026-08-10  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[IG-717](IG-717-rail-exec-do-recipes.md),
[IG-716](IG-716-rail-exec-verb-briefs.md),
[IG-736](IG-736-autopilot-prompts-module.md)

---

## Goal

Land the **autoresearch** rail: an iterative autonomous research loop that
plans research questions → gathers web evidence → reflects on sufficiency →
synthesizes an adaptive report, looping find→optimize→verify until acceptance.

This IG ships:

1. **`builtin_rails/autoresearch.yml`** — the rail YAML with `do:` recipes
   for `decompose_parallel` and `spawn_feedback_cycle`, `brief:` overrides
   for `review` and `qa_verify`, conditions, and the full flow.
2. **`autopilot/prompts/fragments/rail/autoresearch_loop.xml`** — the core
   loop prompt fragment (iteration protocol, scope banner, discipline).
3. **14 subcommand prompt fragments** under `fragments/rail/` matching all
   approved subcommands: `debug`, `fix`, `security`, `ship`, `scenario`,
   `predict`, `learn`, `reason`, `probe`, `improve`, `plan`, `evals`,
   `regression`, `orchestrator_routing`.
4. **`autopilot/rail/autoresearch_exec.py`** — native execution module with
   research-specific brief builders and a `plan_and_implement` dispatch path.
5. **Wiring** — `builtins_exec.py`, `verb_defaults.py`, `catalog.py`,
   `builtins.py` updated for native registration and dispatch.

---

## Contract

### Rail YAML (`autoresearch.yml`)

| Section | Content |
|---------|---------|
| `id` | `autoresearch` |
| `version` | `1.0` |
| `fanout.require_plan` | `true` (guards use fan-out latches) |
| `verbs.decompose_parallel.do` | `spawn_goal` (scout plan) + `wire_deps` (root waits on self) |
| `verbs.spawn_feedback_cycle.do` | `gate` (unless acceptance_met / max feedback_rounds / no_inflight) → `bump` → `spawn_goal` ×3 (diagnose → optimize → verify) |
| `verbs.review.brief` | Research synthesis review (no re-gather) |
| `verbs.qa_verify.brief` | Source/claim verification (fresh evidence checks) |
| `conditions` | `ready_to_synthesize`, `needs_synthesis`, `needs_feedback`, `needs_review`, `needs_qa`, `needs_human`, `branch_is_stuck`, `job_complete` |
| `flow` | `job_start → decompose_parallel`; `goal_completed/dag_idle → plan_and_implement` (synthesis); `goal_completed → review → qa_verify`; `goal_completed/failed → spawn_feedback_cycle`; `dag_idle → complete_job` |

### Flow

```text
job_start
  → decompose_parallel          (spawn scout planner, wire root deps)
goal_completed {ready_to_synthesize|needs_synthesis}
  → plan_and_implement          (native: synthesis plan → writer)
goal_completed {needs_review}
  → review                      (synthesis draft review)
goal_completed {needs_qa}
  → qa_verify                   (source/claim verification)
goal_completed/failed {needs_feedback}
  → spawn_feedback_cycle        (gate → bump → diagnose → optimize → verify)
goal_failed {branch_is_stuck}
  → retry_branch
goal_completed/dag_idle {needs_human}
  → pause_for_user
dag_idle {job_complete}
  → complete_job
```

### L0 ops used (`do:` recipes)

| Op | Where |
|----|-------|
| `spawn_goal` | `decompose_parallel` (scout plan), `spawn_feedback_cycle` (diagnose, optimize, verify) |
| `wire_deps` | `decompose_parallel` (`root_waits_on: self`) |
| `gate` | `spawn_feedback_cycle` (`unless: acceptance_met`, `max: feedback_rounds`, `no_inflight: feedback`) |
| `bump` | `spawn_feedback_cycle` (`feedback_round`) |

Interpolation: `{job_id}`, `{feedback_round}`. Step aliases from `spawn_goal.id`
resolve in `depends` / `root_waits_on`.

### Native dispatch (`autoresearch_exec.py`)

The generic `_do_plan_and_implement` spawns code-planning + code-implementation
goals with TDD / worktree discipline — wrong for research synthesis. The native
module provides:

| Symbol | Purpose |
|--------|---------|
| `AUTORESEARCH_RAIL_ID` | `"autoresearch"` constant |
| `RESEARCH_TAGS_PLANNING` | `["research", "planning", "questions"]` |
| `RESEARCH_TAGS_SYNTHESIS` | `["research", "synthesis"]` |
| `RESEARCH_TAGS_SCOUT` | `["research", "scout"]` |
| `RESEARCH_TAGS_FEEDBACK` | `["feedback", "research"]` |
| `RESEARCH_SCOPE_BANNER` | Public-web-only discipline text (RFC-630) |
| `research_plan_brief(job_id)` | Synthesis plan goal brief |
| `research_synthesis_brief(job_id)` | Synthesis writer goal brief |
| `research_scout_inform_ids(state, ce)` | Collect completed scout/gather goal IDs |
| `AutoresearchExec.plan_and_implement` | Spawn synthesis plan → writer (no TDD/worktree) |
| `AutoresearchExec.review` | Hook → delegates to generic `_do_review` |
| `AutoresearchExec.qa_verify` | Hook → delegates to generic `_do_qa_verify` |
| `is_autoresearch_job(state)` | Rail-id predicate |
| `get_autoresearch_exec(executor)` | Lazy-bind `AutoresearchExec` to an executor |

### Invoke dispatch

```text
if state.verb_overrides[verb].do:
    RecipeRunner.run(do)
else if state.rail_id == "autoresearch" and verb == "plan_and_implement":
    AutoresearchExec(executor).plan_and_implement(...)
else:
    _do_{verb}(...)
```

The native dispatch sits **after** the `do:` recipe check (YAML recipes win)
and **before** the generic `_do_*` fallback. This means:

- `decompose_parallel` and `spawn_feedback_cycle` → YAML `do:` recipes (RecipeRunner)
- `plan_and_implement` → native `AutoresearchExec` (research synthesis)
- `review` and `qa_verify` → generic `_do_*` with YAML `brief:` overrides
- `pause_for_user`, `complete_job`, `retry_branch` → generic `_do_*`

### Prompt fragments

| Fragment | Content |
|----------|---------|
| `autoresearch_loop.xml` | Core iteration-loop protocol: plan → gather → reflect → synthesize, scope banner, routing back to `spawn_feedback_cycle` |
| `debug.xml` | Root-cause evidence gathering before fix |
| `fix.xml` | Minimal evidence-based repair |
| `security.xml` | Threat identification/remediation, untrusted-data discipline |
| `ship.xml` | Finalize on green verification |
| `scenario.xml` | Evaluate competing evidence scenarios |
| `predict.xml` | Forecast with falsification tests |
| `learn.xml` | Distill reusable grounded lessons |
| `reason.xml` | Evidence→conclusion reasoning chain |
| `probe.xml` | Targeted gap-focused gather without synthesis |
| `improve.xml` | Bounded refinement from review/feedback |
| `plan.xml` | Flat sub-question decomposition |
| `evals.xml` | Criterion-based acceptance evaluation |
| `regression.xml` | Confirm no prior-behavior breakage |
| `orchestrator_routing.xml` | Structural-fact routing to next subcommand |

All fragments follow RFC-630 (structured light-LLM fields over keyword
heuristics) and the existing fragment style (plain-text XML, concise protocol
+ output spec).

### Verb defaults (defensive)

`verb_defaults.py` adds `plan_and_implement`, `review`, and `qa_verify` to
`DEFAULT_VERB_BRIEFS`, `DEFAULT_VERB_TAGS`, and `DEFAULT_VERB_ROLES`. These
are defensive defaults — YAML `brief:` / `do:` overrides always win. They
apply only when a custom rail without a `do:` recipe or `brief:` override
calls `plan_and_implement`.

### Catalog registration

Rails are discovered by scanning `builtin_rails/` — no explicit ID registry
exists. The autoresearch.yml file is placed in that directory and is
auto-discovered by `LoopRailCatalog`. `BUILTIN_RAIL_IDS` in `catalog.py`
documents the known IDs for boundary-check and test assertion purposes.

---

## Mapping

### Autoresearch verbs → execution paths

| Verb | Execution path | Tag vocabulary |
|------|---------------|----------------|
| `decompose_parallel` | YAML `do:` recipe (RecipeRunner) | `research, planning, questions` |
| `plan_and_implement` | Native `AutoresearchExec` | `research, planning` + `research, synthesis` |
| `spawn_feedback_cycle` | YAML `do:` recipe (RecipeRunner) | `feedback, research, {diagnose\|gather\|verify}` |
| `review` | Generic `_do_review` + YAML `brief:` | `review` (from verb_defaults) |
| `qa_verify` | Generic `_do_qa_verify` + YAML `brief:` | `qa` (from verb_defaults) |
| `pause_for_user` | Generic `_do_pause_for_user` | — |
| `complete_job` | Generic `_do_complete_job` | — |
| `retry_branch` | Generic `_do_retry_branch` | — |

### Autoresearch conditions → flow triggers

| Condition | Event | Then |
|-----------|-------|------|
| `ready_to_synthesize` | `goal_completed` | `plan_and_implement` |
| `needs_synthesis` | `goal_completed` | `plan_and_implement` |
| `needs_review` | `goal_completed` | `review` |
| `needs_qa` | `goal_completed` | `qa_verify` |
| `needs_feedback` | `goal_completed` | `spawn_feedback_cycle` |
| `needs_feedback` | `goal_failed` | `spawn_feedback_cycle` |
| `branch_is_stuck` | `goal_failed` | `retry_branch` |
| `needs_human` | `goal_completed` | `pause_for_user` |
| `needs_human` | `dag_idle` | `pause_for_user` |
| `needs_feedback` | `dag_idle` | `spawn_feedback_cycle` |
| `job_complete` | `dag_idle` | `complete_job` |

### Research synthesis goal chain

```text
scout goals (research+scout/gather, completed)
  ↓ informs
synthesis plan goal (research+planning, role=planner, priority=70)
  ↓ depends_on
synthesis writer goal (research+synthesis, role=writer, priority=75)
```

Neither synthesis goal applies maker discipline (TDD, worktrees, systematic
debugging). Research synthesis is writing, not coding.

---

## Migration

### From generic `_do_plan_and_implement`

Before this IG, the autoresearch rail would have used the generic
`_do_plan_and_implement`, which spawns:

1. A code planning goal (architecture, TDD discipline)
2. A code implementation goal (maker, worktree, failing-test-first)

After this IG, autoresearch's `plan_and_implement` spawns:

1. A synthesis plan goal (research, planning, no TDD/worktree)
2. A synthesis writer goal (research, synthesis, no TDD/worktree)

The briefs are research-specific: they require flat JSON deliverables with
source citations and the public-web-only scope banner.

### No backward-compatibility shims

There is no prior autoresearch rail to maintain backward compatibility with.
This is a new rail. No shim layer is needed.

### Integration with existing rails

The autoresearch rail coexists with `greenfield-system`, `feature-dev`,
`migration`, and other builtin rails. Rail selection is driven by the LLM
rail-auto-pick (IG-728) or explicit operator binding. The autoresearch rail's
`applies_when` text guides selection toward research-report jobs.

### Prompt fragment registration

The 14 subcommand fragments and the `autoresearch_loop.xml` core fragment sit
alongside the pre-existing `guard_system.xml` under `fragments/rail/`. They
are available for the autopilot prompt assembler to include when the autoresearch
rail is active. Fragment registration in `fragments/__init__.py` is a
downstream concern (IG-736).

---

## Acceptance

1. `autoresearch.yml` loads from `LoopRailCatalog` with correct id, version,
   verbs, conditions, and flow.
2. `decompose_parallel` via `do:` recipe spawns a scout plan goal and wires
   root dependencies.
3. `spawn_feedback_cycle` via `do:` recipe gates on acceptance, bumps
   feedback_round, and spawns diagnose→optimize→verify goals.
4. `plan_and_implement` routes to `AutoresearchExec` (not generic
   `_do_plan_and_implement`) when `rail_id == "autoresearch"`.
5. Synthesis goals have research tags (not code tags), no TDD/worktree
   discipline, and include the public-web-only scope banner.
6. `review` and `qa_verify` delegate to generic handlers with YAML brief
   overrides.
7. Non-autoresearch rails (e.g. `greenfield-system`) do NOT route
   `plan_and_implement` to `AutoresearchExec`.
8. All 15 prompt fragment files exist and are non-empty.
9. `verb_defaults.py` has defensive defaults for `plan_and_implement`,
   `review`, `qa_verify`.
10. `./scripts/verify_finally.sh` green (ruff, vulture, tests, boundaries).

---

## Non-goals

- Extracting `decompose_parallel` or `spawn_feedback_cycle` from YAML `do:`
  recipes into Python handlers (they work as recipes).
- Registering prompt fragments in `fragments/__init__.py` (downstream IG-736).
- Adding a `foreach` L0 op for parallel scout spawning (scout plan is a single
  planner goal that decomposes into sub-questions internally).
- Academic literature review support (use external research tooling).
- Local codebase analysis support (use `feature-dev` or `spike` rails).
