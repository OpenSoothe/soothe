# IG-630: Full-loop token accounting (TUI ↔ Langfuse)

## Scope

Align `LoopState.total_tokens_used` and TUI display with Langfuse trace totals by:

1. Summing **all** CoreAgent execute hops (not only the last `AIMessage`).
2. Ensuring planner/intent **structured** LLM calls accumulate via shared token callback in config.
3. Scoping synthesis streaming for direct-LLM token accumulation.

## Out of scope

- Autopilot verifier / background `[main]` threads (separate traces).
- Subagent nested usage already excluded from step cards; loop total includes main execute + overhead.

## Done

- `extract_token_usage_from_messages` sums every AI turn in an execute wave.
- `merge_token_usage_callbacks` wired into `invoke_structured_chat` for planner/intent paths.
- Synthesis `astream` wrapped in `direct_llm_token_call_scope`.
- Removed dead `Executor._extract_token_usage` wrapper and unused `accumulate_loop_tokens_from_messages`.
