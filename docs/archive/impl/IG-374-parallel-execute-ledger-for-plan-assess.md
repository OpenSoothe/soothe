# IG-374: Parallel execute wave records `loop_messages` for Plan-assess

## Problem

`PromptBuilder.build_plan_messages(..., plan_phase="assess")` extends the planner prompt with `state.loop_messages` (RFC-214 ledger). Sequential execute (`_execute_sequential_chunk`) appends Human/AI pairs after each wave. **Parallel** execute (`_execute_parallel`) yielded `StepResult`s but **never** appended ledger messages, so the next `plan-assess` call lacked evidence from parallel steps (and Langfuse showed execute subgraph activity that did not appear in assess input).

## Approach

After `asyncio.gather` completes in `_execute_parallel`, append one `LoopHumanMessage` + `LoopAIMessage` per step (same shape as sequential ledger), using:

- `_ledger_execute_ai_content` for successful steps with AIMessages (mirrors sequential / IG-373 chunk assembly).
- `delegate_final` text when root assistant body is empty (task-delegate pattern).
- Exception / failed-step fallbacks aligned with sequential error ledger rows.

## Verification

- Unit test: `_append_parallel_wave_ledger` populates `state.loop_messages` for mixed success/failure tuples.
- `./scripts/verify_finally.sh`
