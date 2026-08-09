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

`greenfield-system` sets ``auto_pick: false`` (pass `--rail` explicitly).

## Catalog

| Rail | Pipeline |
|------|----------|
| `feature-dev` | Scouts → plan+implement → review → QA |
| `bugfix` | Scouts (repro/root-cause) → fix → review → QA |
| `maker-checker` | Implement → independent checker → replant on send_back → QA |
| `hotfix` | Patch → review → QA; human pause on high blast radius |
| `spike` | Explore → pause for human; no auto-implement |
| `pr-review` | Review → QA; no implementation branch |
| `migration` | Milestones → streaming WavePlan makers → host merge → per-maker QA → feedback; pause on cutover |
| `greenfield-system` | Milestones → streaming worktree makers → host merge into `job/<id>/_base` → per-maker review/QA → feedback until acceptance → land on main |

`merge_branches` is a host verb (happy-path merge maker → job branch in an
isolated merge worktree, refresh peers, spawn review). Conflicts or other
non-trivial git failures spawn a resolve StrangeLoop goal so a worker can fix
the tree with tools; `dag_idle` / resolve completion retries the host merge.
`land_job_branch` runs before `complete_job`.

### Submit with `greenfield-system`

From a repo that has a `GOAL.md` (pass `--rail` explicitly; auto-pick does not
select greenfield). With no TASK / `--file`, submit reads `./GOAL.md`:

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
