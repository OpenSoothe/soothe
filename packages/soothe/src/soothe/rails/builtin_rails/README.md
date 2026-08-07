# Built-in LoopRails

Declarative job-scoped workflow patterns for Autopilot. Users author **when**
orchestration should act; **Rail Exec** applies catalog verb recipes as CE
primitives (`then:`).

## No `default` rail

Jobs **without** a `rail_id` keep AutopilotMonitor / ContextEngine opportunistic
behavior (placement, verifier suggestions, backoff, consensus). A rail is only
shipped when its policy adds hard gates or topology beyond that path.

Fallback when auto-pick confidence is low:

1. `<workspace>/.soothe/rails/.rail-default` (if set)
2. `agent.autopilot.default_rail` in config (if set)
3. **No rail** — Monitor/CE defaults (do not invent a `default.yml`)

## Catalog

| Rail | Pipeline |
|------|----------|
| `feature-dev` | Scouts → plan+implement → review → QA |
| `bugfix` | Scouts (repro/root-cause) → fix → review → QA |
| `maker-checker` | Implement → independent checker → replant on send_back → QA |
| `hotfix` | Patch → review → QA; human pause on high blast radius |
| `spike` | Explore → pause for human; no auto-implement |
| `pr-review` | Review → QA; no implementation branch |
| `migration` | Milestones → WavePlan makers → integrate → commit → review → QA → feedback; pause on cutover |
| `greenfield-system` | Milestones → worktree makers → integrate → commit → review → QA → find/optimize/verify until acceptance |

`merge_branches` is a reserved catalog verb (not used by shipped builtins).

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
