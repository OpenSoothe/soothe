# IG-357 — Act-wave finalize model + planner preview field clarity

## Purpose

1. **Single conceptual model** — Centralize how `last_execute_assistant_text` and delegate-vs-root provenance are computed in `compute_act_wave_finalize()` / `ActWaveFinalizeSnapshot` (`act_wave_finalize.py`). Executor applies one snapshot to `LoopState` instead of scattering branch logic.

2. **Distinct preview fields** — Replace the duplicated name `delegate_evidence_preview` with:
   - **`task_return_preview`** — per `task` tool invocation in `generate_outcome_metadata` (subagent outcome type).
   - **`wave_join_preview`** — bounded slice of the full Execute wave join string on wave-level `StepResult.outcome` (scheme B).

Planner evidence resolution uses a small helper that checks `wave_join_preview`, then `task_return_preview`, then `output_summary`.

## Status

Completed; `./scripts/verify_finally.sh` passed locally.

## Verification

`./scripts/verify_finally.sh`
