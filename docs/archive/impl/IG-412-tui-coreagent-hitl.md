# IG-412 — CoreAgent LangGraph interrupt auto-resume (supersedes interactive HITL)

## Status

**Superseded.** Interactive human-in-the-loop (TUI approval menus, `resume_interrupts`, `hitl_scope.py`) was removed. AgentLoop execute phase now **auto-resumes** LangGraph interrupts in-process.

## Current behavior

- `Executor._core_agent_astream_with_interrupt_resume`: detect `__interrupt__` on `updates` chunks, build payload via `graph_interrupt.build_auto_resume_payload`, resume with `Command(resume=...)`.
- Auto-resume approves tool interrupts and fills empty `ask_user` answers (no client pause).
- Stream coalescer / CLI chunk filter retain `__interrupt__` chunks for correctness while the server resumes immediately.

## Removed (cleanup)

- `hitl_scope.py`, `test_hitl_scope.py`, daemon `resume_interrupts` handler, `daemon.hitl_timeout_seconds`
- TUI `AskUserMenu`, approval-menu widgets, `resume_interrupts` in Go/TS clients

## Files (current)

`packages/soothe/src/soothe/core/loop/engine/executor.py`, `graph_interrupt.py`, `packages/soothe-daemon/.../stream_delivery.py`, `packages/soothe-cli/.../chunk_filter.py`, `session.py`
