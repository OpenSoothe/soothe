# IG-218: AgentLoop ↔ CoreAgent stream normalization

This guide tracks work to pin the CoreAgent input contract, centralize LangGraph `astream` chunk parsing (tuple vs dict vs legacy list), and deduplicate final-report streaming with the Act-phase `_stream_and_collect` path.

## Contracts

- **Into CoreAgent**: Orchestration callers SHOULD pass `{"messages": list[BaseMessage]}`. A bare `str` is coerced to a single `HumanMessage` in `CoreAgent.astream` for a single code path into `CompiledStateGraph`.
- **RunnableConfig.configurable**: Documented on `CoreAgent` — `thread_id`, `workspace`, step hints (`soothe_step_*`), goal briefing, Claude extras.
- **Out of CoreAgent**: Consumers rely on LangGraph multi-mode streams; Act aggregation uses `iter_messages_for_act_aggregation()` in `stream_chunk_normalize.py` for stable extraction.

## Code

- `soothe/cognition/agent_loop/stream_chunk_normalize.py` — pure helpers for tuple/dict chunks and text extraction.
- `soothe/core/agent/_core.py` — `str` → `HumanMessage` state dict normalization.
- `soothe/cognition/agent_loop/executor.py` — `_stream_and_collect` uses shared helpers.
- `soothe/cognition/agent_loop/agent_loop.py` — final report path uses `update_final_report_from_message()`.

## Status

Completed: `stream_chunk_normalize.py`, CoreAgent string coercion, `Executor` / `AgentLoop` unified parsing, unit tests in `test_stream_chunk_normalize.py`.
