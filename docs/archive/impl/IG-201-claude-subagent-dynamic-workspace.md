# IG-201: Claude subagent dynamic workspace (multi-client daemon)

## Problem

The Claude Code subagent set `ClaudeAgentOptions.cwd` only from factory-time `create_claude_subagent(..., cwd=...)` (via `resolve_subagents`: `config.workspace_dir` or `Path.cwd()` at agent build). Per-query workspace for threads and daemon clients (`SootheRunner` / `QueryEngine` → `config.configurable["workspace"]`) was ignored, so a single daemon serving different repos could run Claude in the wrong directory.

## Solution

Introduce `_resolve_claude_cwd(fallback)` in `subagents/claude/implementation.py`, aligned with `_get_effective_work_dir` / RFC-103:

1. `langgraph.config.get_config()["configurable"].get("workspace")` when non-empty
2. `FrameworkFilesystem.get_current_workspace()` when set
3. Factory-time `fallback` string

`Parent RunnableConfig` is already passed to nested subagent `ainvoke` via `core/agent/_patch.py` (`runtime.config`).

## Files

- `packages/soothe/src/soothe/subagents/claude/implementation.py`
- `packages/soothe/tests/unit/subagents/test_claude_cwd_resolution.py`

## Verification

`./scripts/verify_finally.sh`
