# IG-716: Rail Exec M1/M2 — verb briefs via YAML (no rail_id forks)

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[IG-715](IG-715-migration-wave-fanout.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md)

---

## Goal

Land RFC-231 migration phases **M1 (skeleton)** + **M2 (brief overrides)**:

1. Catalog rails may declare `verbs:` with per-catalog-verb `brief` (and optional
   `tags` / `role`) overrides.
2. `RailBuiltinExecutor` resolves briefs as **rail override ▸ host defaults** —
   never `if state.rail_id == "…"`.
3. Move greenfield vs migration `plan_milestones` copy into YAML; delete the
   migration branch in `_do_plan_milestones`.
4. Host default briefs live in a small `verb_defaults` module (M1 extract of
   opaque goal text only — full L0 `do:` recipes deferred to a follow-on IG).

---

## Non-goals

- Full L0 ActionPlan / multi-step `do:` recipe execution (RFC-231 **M3**).
- NL `intent:` → ActionPlan expand (**M4**).
- Structural predicate YAML (`conditions.*.structural`) — later IG.
- Changing fan-out / WavePlan / guard semantics.

---

## Design

### Catalog `verbs:` (M2 subset)

```yaml
verbs:
  plan_milestones:
    brief: |
      … opaque planner copy with {job_id} …
    tags: [architecture, planning, milestones]   # optional
    role: planner                                  # optional
```

Validation:

- Keys under `verbs:` MUST be names in `CE_RAIL_BUILTINS` (or future recipe set).
- Each body is a mapping; allowed keys for this IG: `brief`, `tags`, `role`.
- Unknown keys → load-time `RailCatalogError`.
- `brief` non-empty str; `tags` list[str]; `role` str.

`RailDefinition.verbs: dict[str, dict[str, Any]]`.

### Bind + state

`LoopRailInterpreter.bind_job` copies `rail.verbs` onto
`RailJobState.verb_overrides`. Persist in `rail_state.json` for restart
continuity (same as other job fields).

### Resolve

```text
brief(verb) = verb_overrides[verb].brief  if set
            else DEFAULT_VERB_BRIEFS[verb]
            else hardcoded fallback in _do_* (should not happen for known verbs)
```

Template interpolate `{job_id}` (and leave other braces alone / use
`str.replace` for `{job_id}` only to avoid format explosions).

### Rails updated

| Rail | Change |
|------|--------|
| `greenfield-system` | `verbs.plan_milestones.brief` = current greenfield planner text |
| `migration` | `verbs.plan_milestones.brief` = current migration planner text |

Optional: same pattern for `review` / `qa_verify` defaults in module only
(no YAML required until a rail differs).

---

## Acceptance

1. Catalog loads `verbs:` on migration + greenfield; rejects unknown verb keys /
   bad shapes.
2. `plan_milestones` with `rail_id="migration"` **without** overrides still works
   if defaults include migration… **No** — defaults are greenfield-shaped;
   migration **must** declare YAML brief. Test binds via interpreter or passes
   overrides.
3. No `rail_id == "migration"` (or other id) in `builtins_exec.py`.
4. Existing greenfield / migration / wave-plan tests green.
5. `./scripts/verify_finally.sh` green.

---

## Follow-on

**IG-717** (planned): M3 multi-step `do:` recipes + extract `_do_spawn_*` bodies.
