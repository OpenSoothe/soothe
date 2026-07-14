# IG-368: Remove detailed evidence string (CONCRETE EVIDENCE / `get_detailed_evidence_string`)

## Status

Completed (verification: `./scripts/verify_finally.sh`).

## Goal

- Drop duplicated execution narrative from plan-context prompts; ledger (`loop_messages`) already carries execute Human/AI turns (RFC-214).
- Remove `StepResult.get_detailed_evidence_string` from `schemas.StepResult`.
- Build synthesis execution evidence from the AgentLoop ledger when present, else fall back to `to_evidence_string(truncate=False)` per successful step.

## Files

- `packages/soothe/src/soothe/core/prompts/builder.py` — remove CONCRETE EVIDENCE; keep WM + prior conversation in plan-context human (matches unit tests / RFC-207).
- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py` — delete `StepResult.get_detailed_evidence_string`.
- `packages/soothe/src/soothe/core/agent_loop/analysis/synthesis.py` — goal-completion synthesis passes **copies** of `state.loop_messages` into `CoreAgent.astream` plus a final `LoopHumanMessage` instruction (no flattened evidence blob). Empty ledger: one `HumanMessage` with compact `to_evidence_string` summaries. Char cap applies to the ledger slice plus a hard pass that drops oldest turns if needed.

## Note

`observability_check.py` had an I001 import-order issue on this branch; `ruff check --fix` applied so `./scripts/verify_finally.sh` passes.
