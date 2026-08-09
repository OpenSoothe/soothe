# Built-in LoopRails

Declarative job-scoped workflow patterns for Autopilot. Users author **when**
orchestration should act; **Rail Exec** applies catalog verb recipes as CE
primitives (`then:`).

## No `default` rail

Jobs **without** a `rail_id` keep AutopilotMonitor / ContextEngine opportunistic
behavior (placement, verifier suggestions, backoff, consensus). A rail is only
shipped when its policy adds hard gates or topology beyond that path.

When submit omits `--rail` / `rail_id`, selection follows RFC-231 §10
(implementation IG-728): structured LLM auto-pick over the merged catalog, then:

1. `<workspace>/.soothe/rails/.rail-default` (if set)
2. `agent.autopilot.default_rail` in config (if set)
3. **No rail** — Monitor/CE defaults (do not invent a `default.yml`)

All shipped builtins are eligible for LLM auto-pick. Operators can still force a
rail with `--rail` / `rail_id`, set `.rail-default`, or exclude ids via
`rail_auto_pick_deny` / per-rail `auto_pick: false` in custom YAML.

## Catalog

| Rail | Pipeline |
|------|----------|
| `feature-dev` | Scouts → plan+implement (feature or defect) → review → QA |
| `maker-checker` | Implement → independent checker → replant on send_back → QA |
| `hotfix` | Patch → review → QA; human pause on high blast radius |
| `spike` | Explore → pause for human; no auto-implement |
| `pr-review` | Review → QA; no implementation branch |
| `greenfield-system` | Milestones → streaming WavePlan makers → host merge → per-maker review/QA → feedback; pause on irreversible cutover → land on main |

### Maker / scout discipline (IG-737)

Goal briefs from Rail Exec append shared SoT fragments in
`soothe.rails.verb_defaults`:

- **Scouts** (`decompose_parallel`): systematic debugging — evidence only, no fixes
- **Planners** (`plan_milestones` / plan goals): parallel dispatch — independent domains only
- **Makers** (`plan_and_implement`, `spawn_wave_makers`, feedback optimize):
  `invoke_skill("using-git-worktrees")` before edits, TDD red→green, fix from root cause
- **QA / feedback verify**: fresh command evidence; never claim pass without running checks

Host-created `.soothe/worktrees/<slug>` counts as already-approved isolation
(skill Step 0: reuse; do not nest).

Removed (hard cut; use replacements above):

| Former id | Use instead |
|-----------|-------------|
| `bugfix` | `feature-dev` |
| `migration` | `greenfield-system` |

`merge_branches` is a host verb (happy-path merge maker → job branch in an
isolated merge worktree, refresh peers, spawn review). Conflicts or other
non-trivial git failures spawn a resolve StrangeLoop goal so a worker can fix
the tree with tools; `dag_idle` / resolve completion retries the host merge.
`land_job_branch` runs before `complete_job`.

### Submit with `greenfield-system`

From a repo that has a `GOAL.md`. With no TASK / `--file`, submit reads
`./GOAL.md`:

```bash
cd /path/to/repo
soothe autopilot submit --rail greenfield-system
soothe autopilot top
```

## Format

Each file: `id` must match filename stem; `then:` verbs are single catalog
strings (not lists). Override with `verbs:` — `brief`/`tags`/`role` and/or
multi-step `do:` L0 recipes.

**YAML tip:** use ``event:`` for triggers (not ``on:`` — YAML 1.1 treats bare
``on`` as a boolean). Legacy ``on`` is still accepted and rewritten to ``event``.

Internal protocol: `docs/specs/RFC-231-looprail-rail-exec.md`.
