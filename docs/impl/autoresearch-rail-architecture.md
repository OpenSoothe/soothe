# Autoresearch Rail — Architecture & Usage Guide

> Architecture, execution model, and operator usage for the autoresearch loop
> rail. Companion to [IG-739](IG-739-autoresearch-loop-rail.md) (implementation
> spec) and [RFC-231](../specs/RFC-231-looprail-rail-exec.md) (LoopRail exec).

---

## Overview

The **autoresearch** rail is an iterative autonomous research loop. It plans
research questions → gathers web evidence → reflects on sufficiency →
synthesizes an adaptive report, looping find→optimize→verify until acceptance.

Unlike code-producing rails (e.g. `feature-dev`, `greenfield-system`), the
autoresearch rail produces **writing, not code**. Its `plan_and_implement`
verb spawns research synthesis goals (plan + writer) rather than code
planning + implementation goals with TDD/worktree discipline.

### When to use

| Use autoresearch for | Do NOT use autoresearch for |
|----------------------|----------------------------|
| External fact comparisons | Local codebase analysis (use `feature-dev` / `spike`) |
| How-to guides from web sources | Academic literature review (use dedicated research tooling) |
| Landscape surveys | Production code changes |
| Fact-checks | Bug fixes (use `feature-dev`) |
| Adaptive research reports | Architecture planning (use `greenfield-system`) |

### Rail selection

The autoresearch rail is selected by the LLM rail-auto-pick (IG-728) based on
its `applies_when` text, or by explicit operator binding in the job submission.

---

## Architecture

### Three-level execution

```text
ContextEngine (goal DAG)
  ↓ goal scheduling
LoopRailInterpreter (rail rules)
  ↓ guard evaluation + verb dispatch
RailBuiltinExecutor.invoke (verb execution)
  ↓ dispatch by rail_id + verb
  ├─ RecipeRunner (YAML do: recipes)
  ├─ AutoresearchExec (native plan_and_implement)
  └─ _do_* generic handlers (review, qa_verify, complete_job, …)
```

### Verb dispatch table

The `invoke()` method dispatches verbs in three tiers:

| Priority | Dispatch | Verbs |
|----------|----------|------|
| 1st | YAML `do:` recipe (RecipeRunner) | `decompose_parallel`, `spawn_feedback_cycle` |
| 2nd | Native `AutoresearchExec` | `plan_and_implement` |
| 3rd | Generic `_do_*` handlers | `review`, `qa_verify`, `pause_for_user`, `complete_job`, `retry_branch` |

```text
invoke(verb):
  if state.verb_overrides[verb].do:     → RecipeRunner.run(do)
  elif rail_id == "autoresearch"
       and verb == "plan_and_implement": → AutoresearchExec.plan_and_implement()
  else:                                  → _do_{verb}()
```

This means:
- `decompose_parallel` and `spawn_feedback_cycle` execute as YAML `do:` recipes
  (no Python handler needed).
- `plan_and_implement` uses the native research synthesis path (not the generic
  code planning + implementation path).
- `review` and `qa_verify` use generic handlers but with research-specific
  `brief:` overrides from the YAML.

### L0 ops used in `do:` recipes

| Op | Purpose | Where |
|----|---------|-------|
| `spawn_goal` | Create a goal with interpolated brief + tags | `decompose_parallel` (scout plan), `spawn_feedback_cycle` (diagnose, optimize, verify) |
| `wire_deps` | Wire job root to depend on spawned goals | `decompose_parallel` (`root_waits_on: self`) |
| `gate` | Skip recipe if acceptance met / max rounds / inflight feedback | `spawn_feedback_cycle` |
| `bump` | Increment a counter (feedback_round) | `spawn_feedback_cycle` |

Interpolation: `{job_id}`, `{feedback_round}`. Step aliases from `spawn_goal.id`
resolve in `depends` / `root_waits_on`.

### Tag vocabulary

| Tag set | Tags | Applied to |
|---------|------|------------|
| `RESEARCH_TAGS_PLANNING` | `research, planning, questions` | Synthesis plan goal |
| `RESEARCH_TAGS_SYNTHESIS` | `research, synthesis` | Synthesis writer goal |
| `RESEARCH_TAGS_SCOUT` | `research, scout` | Completed scout/gather goals (inform sources) |
| `RESEARCH_TAGS_FEEDBACK` | `feedback, research` | Feedback cycle goals |

Planning and synthesis tag sets are disjoint — no goal should carry both.

### Scope banner (RFC-630)

All research goals include the public-web-only scope banner:

> Scope: public-web-only research. Use web search and crawl discovered URLs.
> Do not access private/internal systems or local codebase analysis. Cite a
> source URL for every factual claim.

This enforces RFC-630 (no keyword heuristics; structured discipline) by
embedding the scope constraint in the goal brief rather than filtering output
with regex.

---

## Flow

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

### Feedback cycle

When `spawn_feedback_cycle` fires (needs_feedback), the YAML `do:` recipe:

1. **gate** — skip if `acceptance_met`, `feedback_round >= max_feedback_rounds`,
   or inflight feedback goals exist.
2. **bump** — increment `feedback_round`.
3. **spawn_goal: diagnose** — review gathered evidence, identify gaps.
4. **spawn_goal: optimize** — execute targeted web searches for diagnosed gaps.
5. **spawn_goal: verify** — re-check evidence against acceptance contract.

The three feedback goals form a chain (diagnose → optimize → verify). When
verify completes and `needs_feedback` fires again, another round spawns. When
`ready_to_synthesize` or `needs_synthesis` fires, `plan_and_implement` re-runs
to synthesize from the newly gathered evidence.

---

## Conditions

| Condition | Triggers on | Then |
|-----------|-------------|------|
| `ready_to_synthesize` | `goal_completed` | `plan_and_implement` |
| `needs_synthesis` | `goal_completed` | `plan_and_implement` |
| `needs_review` | `goal_completed` | `review` |
| `needs_qa` | `goal_completed` | `qa_verify` |
| `needs_feedback` | `goal_completed` / `goal_failed` / `dag_idle` | `spawn_feedback_cycle` |
| `needs_human` | `goal_completed` / `dag_idle` | `pause_for_user` |
| `branch_is_stuck` | `goal_failed` | `retry_branch` |
| `job_complete` | `dag_idle` | `complete_job` |

Conditions are evaluated by the guard evaluator (LLM-based or scripted in
tests). The `ScriptedGuardEvaluator` in tests defaults unmatched conditions to
`False` — tests must explicitly allow builtins to fire.

---

## Usage

### Submitting an autoresearch job

The autoresearch rail is selected automatically by rail-auto-pick when the job
description matches research-report intent, or explicitly via rail binding:

```yaml
# Explicit rail binding in job submission
rail: autoresearch
```

### What the rail produces

| Goal | Role | Deliverable |
|------|------|-------------|
| Scout plan | planner | Flat JSON: `sub_questions` list (question, search_query, scope, done_check) |
| Feedback diagnose | researcher | Gap list with targeted follow-up queries |
| Feedback gather | researcher | New evidence from targeted web searches |
| Feedback verify | qa | Sufficiency report (remaining gaps) |
| Synthesis plan | planner | Flat JSON: `sections` list (title, key_findings, source_urls, gap) |
| Synthesis writer | writer | Adaptive report with inline source citations |
| Review | reviewer | Coverage/accuracy/source-quality findings |
| QA verify | qa | Pass/fail: URL resolution, claim tracing, scope banner |

All deliverables are flat JSON (no nested trees) with source citations, per
RFC-630 structured-output discipline.

### Acceptance and completion

The rail completes when:
1. Synthesis writer goal has completed.
2. Review has passed (or was skipped by policy).
3. QA verify has passed (URLs resolve, claims trace, scope banner present).
4. No pending research goals remain (`dag_idle` + `job_complete`).

### Human pause

The rail pauses for human input when:
- The topic is ambiguous and needs scope clarification (`needs_human`).
- Sources are exhausted without a verdict (`needs_human`).
- The request needs scope clarification before continuing (`needs_human`).

After user intervention, the rail resumes and completes.

### Feedback budget

`spawn_feedback_cycle` respects `max_feedback_rounds` (default: 8). When the
feedback round counter reaches the maximum, the gate skips further feedback
cycles. This prevents infinite research loops.

---

## Testing

### Unit tests

`packages/soothe/tests/unit/rails/test_autoresearch_rail.py` — 35 tests covering:

- Catalog discovery and YAML contract (loads, verbs, conditions, flow).
- Brief builders (scope banner, flat JSON, no re-gather).
- Helper functions (`is_autoresearch_job`, `get_autoresearch_exec`,
  `research_scout_inform_ids`).
- Native `invoke` dispatch (`plan_and_implement` routes to `AutoresearchExec`).
- Rail-id-aware dispatch (non-autoresearch rails use generic handlers).
- `do:` recipe verbs (`decompose_parallel`, `spawn_feedback_cycle`).
- Error handling (unbound jobs, missing state).
- Review/QA hook delegation.
- Module exports and tag vocabulary disjointness.

```bash
uv run pytest packages/soothe/tests/unit/rails/test_autoresearch_rail.py -q
```

### Integration tests

`packages/soothe/tests/integration/rails/test_autoresearch_rail.py` — multi-turn
end-to-end scenarios with real `ContextEngine` + `LoopRailInterpreter` and
scripted guards:

| Scenario | Verifies |
|----------|----------|
| Happy path | decompose → plan_and_implement → review → qa_verify → complete_job |
| Feedback cycle | needs_feedback → spawn_feedback_cycle → re-synthesize → complete |
| Acceptance-gated skip | acceptance met → feedback skipped |
| Human pause | needs_human → pause_for_user → resume → complete |
| Research tags | synthesis goals carry research tags, not code tags |
| Scout plan wiring | decompose spawns scout plan, root depends on it |
| Branch stuck | goal_failed → retry_branch → complete |
| Evaluation export | Writes `autoresearch_evaluation_results.json` |

```bash
uv run pytest packages/soothe/tests/integration/rails/test_autoresearch_rail.py -q --run-integration
```

### Test harness

Integration tests use `RailHarness` (`packages/soothe/tests/support/rail_harness.py`):

```python
from support.rail_harness import RailHarness

harness = RailHarness()
job_id = await harness.submit(
    "Compare vector databases",
    rail_id="autoresearch",
    guard_scripts={
        ("goal_completed", "ready_to_synthesize"): [False, True],
        ("dag_idle", "job_complete"): [True],
    },
)

async def on_ready(goal, turn):
    await harness.pseudo_complete(goal.id)

await harness.run_turns(on_ready)
assert await harness.job_completed()
```

`ScriptedGuardEvaluator` keys on `(event, condition_name)` tuples. Missing keys
default to `matched=False`. Values are FIFO queues — each evaluation pops one
entry. This lets tests script exact multi-turn decision sequences.

---

## File Map

| File | Purpose |
|------|---------|
| `packages/soothe/src/soothe/rails/builtin_rails/autoresearch.yml` | Rail YAML (verbs, conditions, flow, `do:` recipes) |
| `packages/soothe/src/soothe/autopilot/rail/autoresearch_exec.py` | Native exec module (synthesis plan + writer) |
| `packages/soothe/src/soothe/autopilot/rail/builtins_exec.py` | `invoke()` dispatch (routes to AutoresearchExec) |
| `packages/soothe/src/soothe/autopilot/rail/recipe_exec.py` | `RecipeRunner` (executes YAML `do:` recipes) |
| `packages/soothe/src/soothe/autopilot/rail/verb_defaults.py` | Defensive defaults for `plan_and_implement`, `review`, `qa_verify` |
| `packages/soothe/src/soothe/autopilot/rail/catalog.py` | `BUILTIN_RAIL_IDS` + `CE_RAIL_BUILTINS` |
| `packages/soothe/src/soothe/autopilot/prompts/fragments/rail/autoresearch_loop.xml` | Core loop prompt fragment |
| `packages/soothe/src/soothe/autopilot/prompts/fragments/rail/*.xml` | 14 subcommand prompt fragments |
| `packages/soothe/tests/unit/rails/test_autoresearch_rail.py` | Unit tests (35) |
| `packages/soothe/tests/integration/rails/test_autoresearch_rail.py` | Integration tests (8 scenarios) |

---

## Related

- [IG-739](IG-739-autoresearch-loop-rail.md) — Implementation spec
- [RFC-231](../specs/RFC-231-looprail-rail-exec.md) — LoopRail rail exec
- [IG-717](IG-717-rail-exec-do-recipes.md) — Rail exec `do:` recipes
- [IG-716](IG-716-rail-exec-verb-briefs.md) — Rail exec verb briefs
- [IG-736](IG-736-autopilot-prompts-module.md) — Autopilot prompts module
- [IG-728](IG-728-llm-rail-auto-pick.md) — LLM rail-auto-pick
