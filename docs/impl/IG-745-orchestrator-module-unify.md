# IG-745: Unify `soothe.sloop.orchestrator` modules

## Goal

Collapse tiny helper modules in `soothe.sloop.orchestrator` into functionality-centric
modules. No behavior changes; no backward-compat shims.

## Target map

| Keep / new | Absorbs | Concern |
|---|---|---|
| `runtime_context.py` | `phase_scratch.py` | Run bundle + per-iteration scratch |
| `checkpoint.py` | `checkpoint_keys.py`, `checkpointer.py` | Thread isolation + CoreAgent checkpointer |
| `continuation.py` | `continuation_routing.py`, `mid_loop_intake.py` | Fresh/continuation entry + mid-loop intake |
| `stations.py` | `state.py` | Station IDs + `LoopGraphState` / route literals (channel fields that would import `intention`/`clarification` stay typed as `str` to avoid import cycles) |
| `routing.py` | — | Conditional edges |
| `node_base.py` | — | `LoopNode` lifecycle |
| `builder.py` / `runner.py` | — | Compile / invoke |

`validate_plan_evidence` moves into `stages/execute/commit_plan.py` (sole consumer).

## Deleted after move

`phase_scratch.py`, `checkpointer.py`, `checkpoint_keys.py`, `continuation_routing.py`,
`mid_loop_intake.py`, `state.py`, `evidence.py`.

## Verification

`./scripts/verify_finally.sh`
