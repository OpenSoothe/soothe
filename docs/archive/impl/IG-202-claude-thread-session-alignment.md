# IG-202: Align Soothe thread with Claude Agent SDK session

## Problem

Each `task` delegation to the Claude subagent started a new Claude Code session because `ClaudeAgentOptions.resume` was never set, so conversation and tool context did not carry across delegations within the same Soothe thread.

## Solution

1. **Thread metadata** (`ThreadMetadata.claude_sessions`): map resolved workspace cwd (absolute path) → Claude session UUID, persisted via `DurabilityProtocol.update_thread_metadata`.

2. **Read path**: `SootheRunner._stream_phase` and `Executor` inject `configurable["claude_sessions"]` (snapshot from `get_thread`) and `configurable["soothe_durability"]` so the subagent can load and save without ad hoc globals.

3. **Subagent** (`subagents/claude/implementation.py`): resolve cwd with `_resolve_claude_cwd`, look up session id from in-process cache then configurable snapshot, set `options.resume`, stream `query()`, read `session_id` from `ResultMessage`, then `record_claude_session` (memory + durability).

4. **`DurabilityProtocol.get_thread`**: read-only load of `ThreadInfo` without changing status (implemented on `BasePersistStoreDurability`).

5. **`session_bridge.py`**: shared memory cache and merge logic for metadata updates.

## Files

- `packages/soothe/src/soothe/protocols/durability.py` — `ThreadMetadata.claude_sessions`, `get_thread`
- `packages/soothe/src/soothe/backends/durability/base.py` — `get_thread` implementation
- `packages/soothe/src/soothe/core/runner/_runner_phases.py` — inject `claude_sessions`, `soothe_durability`
- `packages/soothe/src/soothe/cognition/agent_loop/executor.py` — `_claude_runner_config_extras`
- `packages/soothe/src/soothe/subagents/claude/session_bridge.py` — new
- `packages/soothe/src/soothe/subagents/claude/implementation.py` — resume + record
- `packages/soothe/src/soothe/subagents/claude/events.py` — optional `resume_session_id`, `claude_session_id`
- Tests: `test_claude_session_alignment.py`, `test_durability.py`, `test_thread_manager.py` mock

## Verification

`./scripts/verify_finally.sh`
