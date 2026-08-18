# IG-748: Cognition & Intention Layout (Relocate + Flatten)

## Goal

Align `soothe.sloop.cognition` with plan-phase reasoning only, relocate
mis-scoped modules to semantic homes, polish `soothe.sloop.intention` in place,
and keep both packages flat (no nesting). Do not merge intention into
cognition. Do not split `planner.py`.

## Constraints

- No backward-compat shims for old import paths — update all in-repo importers.
- Keep `planner.py` unsplit.
- Do not nest `cognition/wire/` or `intention/pass1|pass2/`.
- Keep intention and cognition as sibling packages under `sloop/`.

## Cognition relocate map

| From `cognition/` | To | Why |
|-------------------|----|-----|
| `step_deliverable.py` | `engine/step_deliverable.py` | Execute-wave gate |
| `step_completion_report.py` | `engine/step_completion_report.py` | Execute/TUI summary |
| `step_anchor_registry.py` | `prompts/step_anchor_registry.py` | Prompt assembly |
| `ledger_compaction.py` | `utils/ledger_compaction.py` | Cross-cutting ledger text |
| `parser.py` | deleted | Production-dead markdown parser |

## Intention polish

- Deduplicate Pass1/Pass2 invoke-config builder.
- Single Pass2 → `IntentClassification` construction path.
- Export `build_pass1_task_fallback` from package root.
- Prefer `intention.models` for enums/models; package root for facades.

## Coupling fix

Promote `_current_goal_has_execute_ledger` (or equivalent) to a shared public
helper so cognition does not import a private prompts symbol.

## Cleanse (same pass)

- Consolidate shared keep-block gates (`structural_keep` → call `assess_keep_block_reason`).
- Demote unused public surfaces (`prior_projection_text_from_messages`, `preview_goal`).
- Inline thin Pass1/Pass2 invoke wrappers; drop duplicate `_pass2_to_intent`.
- Move orphaned tests beside new module homes (`engine` / `prompts` / `utils`).

## Verification

`./scripts/verify_finally.sh`
