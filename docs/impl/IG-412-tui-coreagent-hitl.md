# IG-412 — TUI HITL for CoreAgent (AgentLoop execute)

## Goal

Let interactive daemon turns pause on LangGraph HITL interrupts emitted during **CoreAgent** execution inside AgentLoop so the TUI can approve / answer and `resume_interrupts` unblocks the graph.

## Changes

- `Executor`: wrap `core_agent.astream` in interrupt detect → resolver or auto-approve → `Command(resume=...)` loop.
- `hitl_scope.py`: ContextVar for the active async resolver; shared auto-approve payload builder; cancellation-safe chunk await.
- `SootheRunner.astream(client_loop_id=...)`: bind resolver ContextVar and `_client_loop_id_for_stream` for `_stream_phase`.
- `query_engine`: when `interactive` + `client_id` + `effective_loop_id`, stream via in-process `d._runner.astream` (subprocess cannot see daemon interrupt futures).
- `_runner_phases`: resolve interrupts via `_interrupt_resolvers[client_loop_id]`; fix `_auto_approve` missing `return`.

## Files

`hitl_scope.py`, `executor.py`, `runner/__init__.py`, `_runner_phases.py`, `query_engine.py`, `local_runner.py`, `pool_runner.py`, `ray_actor.py`, `test_hitl_scope.py`.

## Follow-up

- `daemon.hitl_timeout_seconds` (default 30, `0` = unlimited): daemon resolver uses `asyncio.wait_for`; on timeout resumes with `timeout_default_hitl_resume_payload` (approve tools; first `choices[0].value` per ask_user question).

## Status

Done.
