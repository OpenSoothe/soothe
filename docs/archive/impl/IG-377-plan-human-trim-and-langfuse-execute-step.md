# IG-377: Plan-context human trim + Langfuse execute-step run name

**Status**: Completed  
**Scope**:

1. Plan-context `LoopHumanMessage` for plan-assess / plan-generate: drop the `Plan status: …` line; keep `Goal:` and `Execute iteration:` only (ledger still carries execution narrative).
2. Executor CoreAgent `astream` Langfuse merge: set `run_name` to `{trace_name}:execute-step` when `trace_name` is set, else `execute-step`, aligned with `soothe-dev:plan-assess` / `soothe-dev:plan-generate`.
