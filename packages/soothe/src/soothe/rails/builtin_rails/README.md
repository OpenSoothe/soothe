# Built-in LoopRails

Declarative job-scoped workflow patterns for Autopilot. Users author **when**
orchestration should act; ContextEngine owns **what** (CE built-ins via `then:`).

## No `default` rail

Jobs **without** a `rail_id` keep AutopilotMonitor / ContextEngine opportunistic
behavior (placement, verifier suggestions, backoff, consensus). A rail is only
shipped when its policy **differs** from that path.

Fallback when auto-pick confidence is low:

1. `<workspace>/.soothe/rails/.rail-default` (if set)
2. `agent.autopilot.default_rail` in config (if set)
3. **No rail** — Monitor/CE defaults (do not invent a `default.yml`)

## Catalog (v1 sketches)

| Rail | How it differs from no-rail |
|------|-----------------------------|
| `feature-dev` | Scout barrier before implement; separate review + QA goals |
| `bugfix` | Repro / root-cause gate before fix; QA re-checks original failure |
| `maker-checker` | Independent checker goal; fail → replant (not same-goal consensus) |
| `hotfix` | Narrow path; mandatory review/QA; human pause on high blast radius |
| `spike` | Explore then `pause_for_user`; no auto-implement |
| `pr-review` | Review-only (+ optional QA); no implementation branch |
| `migration` | Wave goal-loop until a checkable stop condition |
| `greenfield-system` | Milestones → worktree makers → integrate → commit → review → QA → find/optimize/verify feedback until acceptance |

### Submit with `greenfield-system`

From a repo that has a `GOAL.md` (pass `--rail` explicitly; auto-pick does not
select greenfield):

```bash
soothe autopilot submit --file GOAL.md --rail greenfield-system -w /path/to/repo
soothe autopilot top
```

## Format

See `docs/drafts/2026-07-11-loop-rail-design.md`. Each file: `id` must match
filename stem; `then:` verbs are CE built-ins only.

**YAML tip:** use ``event:`` for triggers (not ``on:`` — YAML 1.1 treats bare
``on`` as a boolean). Legacy ``on`` is still accepted and rewritten to ``event``.
