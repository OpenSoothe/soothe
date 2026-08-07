# IG-717: Rail Exec M3 — multi-step `do:` L0 recipes

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[IG-716](IG-716-rail-exec-verb-briefs.md)

---

## Goal

Land RFC-231 **M3** (partial): rails may override a catalog verb with a
multi-step ``do:`` list of **L0 primitives**. When present, Rail Exec runs the
recipe instead of the Python ``_do_*`` handler.

This IG ships a **useful L0 subset** and converts ``plan_milestones`` on
``greenfield-system`` / ``migration`` to ``do:`` recipes (proof + delete
Python-path dependency for those rails). Full extraction of wave/feedback
macros (``foreach``, worktrees, ``spawn_feedback_cycle``) may follow in a
later IG without changing this contract.

---

## L0 subset (this IG)

| Op | Spec |
|----|------|
| `spawn_goal` | `brief`, `tags`, `role`, optional `id`, `priority`, `depends`, `wire.root_waits_on` |
| `wire_deps` | `root_waits_on: [step_id\|goal_id\|self]` |
| `gate` | `unless: acceptance_met`, `max: feedback_rounds\|waves`, `no_inflight: feedback` |
| `bump` | `feedback_round` \| `wave_index` (string shorthand or `{counter: …}`) |
| `pause_job` | `{}` / null |
| `complete_job` | `{}` / null |

**Deferred:** `foreach`, `ensure_worktree`, `ingest_wave_plan`, `prune`,
`replant` (stay on Python `_do_*` until extracted).

### Interpolation

Literal replace only: `{job_id}`, `{feedback_round}`, `{wave_index}`, and
`${…}` forms of the same. Step aliases from `spawn_goal.id` resolve in
`depends` / `root_waits_on` after spawn. `trigger` → `trigger_goal_id`.

---

## Catalog

`verbs.<name>` may include ``do:`` (list of single-key maps). Allowed body
keys: `brief`, `tags`, `role`, `do` (IG-716 + this). If ``do:`` is set, it must
be a non-empty list; unknown L0 op → load-time error.

M2-only bodies (brief/tags/role, no `do`) still use Python `_do_*` with
overrides (IG-716).

---

## Invoke

```text
if state.verb_overrides[verb].do:
    RecipeRunner.run(do)
else:
    _do_{verb}(...)
```

---

## Acceptance

1. Catalog rejects unknown L0 ops / bad `do` shapes.
2. Custom rail / override with `do:` spawning two chained goals works without
   a new `then:` verb name.
3. Builtin `plan_milestones` via `do:` matches prior greenfield/migration briefs
   (existing copy tests still pass).
4. Rails without `do:` unchanged (Python path).
5. `./scripts/verify_finally.sh` green.

---

## Non-goals

- M4 intent→ActionPlan.
- Extracting `spawn_wave_makers` / `spawn_feedback_cycle` into YAML yet.
- Plugin-registered L0 ops.
