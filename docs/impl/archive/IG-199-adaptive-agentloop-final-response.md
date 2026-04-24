# IG-199: Adaptive AgentLoop final response

**Status**: Implemented  
**Scope**: AgentLoop completion path when `PlanResult.status == "done"`.

## Problem

AgentLoop always invoked a second CoreAgent turn to synthesize a “comprehensive final report,” even when the Execute phase already produced a complete user-facing answer on the goal thread.

## Design

1. **Capture** the last assistant text from each Execute wave on the main thread (`LoopState.last_execute_assistant_text`), using the same chunk vs final AIMessage selection logic as the existing final-report stream.
2. **Flag** parallel Execute waves with more than one step (`last_execute_wave_parallel_multi_step`) — multiple concurrent turns are not safe to collapse to a single last assistant line without synthesis.
3. **Policy** `needs_final_thread_synthesis()` (adaptive): run the extra CoreAgent report when evidence heuristics say so (reusing `SynthesisPhase` thresholds), when the parallel-multi flag is set, when the last wave hit the subagent cap, or when no assistant text was captured; otherwise reuse `last_execute_assistant_text`.
4. **Config** `agentic.final_response`: `adaptive` (default) | `always_synthesize` | `always_last_execute`.

## Notes

- `final_response_policy.py` defines `FinalResponseMode` as a local `Literal` (must stay aligned with `AgenticFinalResponseMode` in `soothe.config.models`) to avoid an import cycle with `soothe.config` during package import.

## Key files

- `packages/soothe/src/soothe/cognition/agent_loop/final_response_policy.py`
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`
- `packages/soothe/src/soothe/cognition/agent_loop/executor.py`
- `packages/soothe/src/soothe/cognition/agent_loop/schemas.py`
- `packages/soothe/src/soothe/cognition/agent_loop/synthesis.py`
- `packages/soothe/src/soothe/config/models.py`, `config.yml`, `config/config.dev.yml`

## Verification

Run `./scripts/verify_finally.sh` before merge.
