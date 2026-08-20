# IG-718: Fan-out unit is Slice (hard cut — no module terminology)

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[IG-717](IG-717-rail-exec-do-recipes.md),
[IG-715](IG-715-migration-wave-fanout.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md)

---

## Goal

Replace **module** as the fan-out abstraction with **Slice**. A slice is any
independent parallel ownership unit (feature, task, package/crate, migration
stage, …). Package/module is only one *kind* of slicing — not the name of the
unit in rails, WavePlan, or maker copy.

**Hard cut:** remove `wave_modules` / `modules` / `module` from the WavePlan
wire schema and from user-facing rail / goal text. No dual-read aliases.

---

## Wire schema (WavePlan findings / rail_state; IG-720)

| Old | New |
|-----|-----|
| `wave_modules: string[]` | `wave_slices: string[]` |
| `modules: [{module, description, …}]` | `slices: [{slice, description, …}]` |
| field `module` | field `slice` (slice id / slug) |

Example:

```json
{
  "wave_slices": ["desktop-shell", "auth-identity", "showcase-video"],
  "slices": [
    {
      "slice": "showcase-video",
      "description": "Video file → stream demo; write-set: apps/showcases/video/**",
      "priority": 70,
      "tags": ["feature"]
    }
  ],
  "independence": "disjoint primary write-sets per slice",
  "rationale": "maximize safe wave-1 parallelism",
  "max_waves": 3
}
```

Prefer rich `slices[]`. Bare `wave_slices` remains valid.

---

## Code / API rename

| Old | New |
|-----|-----|
| `WavePlanModule` | `WavePlanSlice` |
| `resolved_module_names` | `resolved_slice_ids` |
| `clamp_module_list` | `clamp_slice_list` |
| `resolve_fanout_modules` | `resolve_fanout_slices` |
| `FanoutResolution.modules` | `FanoutResolution.slices` |
| source `wave_modules` | `wave_slices` |
| `RailJobState.wave_modules` | `wave_slices` |
| `record_wave_plan(..., wave_modules=, modules=)` | `wave_slices=`, `slices=` |
| decompose_plan key `module` | `slice` |

---

## User-facing copy

- `greenfield-system` / `migration` YAML: summary, comments, conditions,
  `plan_milestones` briefs — Slice language only.
- Maker / integrate / retry / host gate messages: slice, not module.
- `spawn_wave_makers`: use rich `description` / `priority` / `tags` from
  decompose_plan when present; sort by priority desc before clamp.

---

## Non-goals

- Soft aliases for old JSON keys (hard cut).
- Intra-wave maker dependency edges.
- Renaming `fanout:` rail key (filesystem `wave-plan.json` removed in IG-720).

---

## Acceptance

1. Valid WavePlan JSON uses only `wave_slices` / `slices` / `slice`.
2. Payload with `wave_modules` / `modules` / `module` fails validation (no ingest).
3. Greenfield/migration planner briefs say Slice; no “module ownership units”
   as the fan-out unit.
4. Makers spawned from rich `slices[]` carry description text and priority.
5. Tests + `./scripts/verify_finally.sh` green.
6. No dual-read aliases; runtime logs/errors omit IG identifiers and module
   fan-out wording (catalog / gates / WavePlan warnings use Slice language).

---

## Migration note

In-flight jobs with legacy module-key plans or orphan `wave-plan.json` files
must re-run architecture so findings emit Slice-schema WavePlan JSON — host
will not accept legacy keys and does not load filesystem plan files (IG-720).
