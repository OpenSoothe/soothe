# IG-573: Step Completion Cognition Report

**Status**: Implemented  
**Related**: RFC-500 (TUI), RFC-214 (ledger — explicitly no write)

## Goal

On execute-step completion, emit a fast-LLM first-person summary (&lt;30 words) as a cognition reason card on the TUI. Source context is only the single-step human/ai pair (compact execute input + final assistant output). No message ledger mutation.

## Implementation

- `step_completion_report.py` — `summarize_step_completion_report()`
- `Executor._summarize_step_completion_report()` — builds pair via `compact_execute_human_content` + ledger AI resolver
- `StepCompletionReport` yielded before `StepResult` in `_execute_parallel`
- `execute_steps` → `step_completion_report` internal event
- `_runner_strange_loop` → `LoopAgentReasonEvent` (`plan_reasoning` field)
- Config: `agent.loop.step_completion_report_max_words`
