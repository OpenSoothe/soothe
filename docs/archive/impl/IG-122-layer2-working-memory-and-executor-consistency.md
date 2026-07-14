# IG-122: Layer 2 Working Memory & Executor Step Accounting

**Status**: In progress  
**RFCs**: [RFC-203](../specs/RFC-203-loop-working-memory.md), [RFC-201](../specs/RFC-201-agentic-goal-execution.md)  
**Created**: 2026-04-02

## Purpose

Track implementation of:

1. **Executor (Act)**: One `StepResult` per `StepAction` in each sequential batch (scheme B); chunk waves by `execution.concurrency.max_parallel_steps` (0 = unlimited).
2. **Loop working memory (RFC-203)**: Modular API; in-memory store with workspace spill under `.soothe/loop`; wired into Reason prompts via `PlanContext` and `<SOOTHE_LOOP_WORKING_MEMORY>`.
3. **Reason prompt**: Stronger `plan_action=keep` guidance; step granularity; Layer 1/Layer 2 goal alignment (no verbatim goal-as-only-step).

## Tasks

- [x] RFC-203 specification
- [x] Executor chunking + multi `StepResult` for sequential success/failure
- [x] Parallel and dependency modes respect `max_parallel_steps`; dependency inner loop avoids tight retry on failure
- [x] `LoopWorkingMemory` + `LoopWorkingMemoryConfig` under `AgenticLoopConfig`; `LoopWorkingMemoryProtocol` in `soothe.protocols`
- [x] `LoopState`, `PlanContext`, `build_loop_reason_prompt` integration
- [x] Planner normalization for goal-as-step descriptions
- [x] Unit tests + `./scripts/verify_finally.sh`

## Verification

```bash
./scripts/verify_finally.sh
```
