# IG-570: Workspace tool binding unification

## Goal

Fix filesystem and execution tools resolving paths against the ephemeral daemon cwd instead of the stream/loop workspace (loop 2514: `glob` → `[]` while `ls` with absolute paths worked).

## Scope

1. **Unified resolution** — `resolve_effective_tool_workspace()` chains ContextVar → LangGraph config/state → config override → daemon fallback (same as `run_command`).
2. **Tool resolver** — `file_ops`, `execution`, and subagent `work_dir` use unified resolution.
3. **Runtime backends** — `WorkspaceAwareBackend.__call__` and `SootheFilesystemMiddleware._get_backend` always prefer dynamic workspace.
4. **Glob UX** — empty results include workspace root hint; timeout via `tool_timeout.per_tool.glob` (30s); discovery fallback in tool description and timeout errors.
5. **macOS shell** — reject GNU `timeout` wrapper in `run_command`/`run_background`; docs steer to native tool timeouts.
6. **Discovery strategy** — execution policies + tool hints: after glob failure use `grep`/`ls`, not repeated broad `**` globs.

## Out of scope

Plan ordering / DAG changes.

## Verification

- `./scripts/verify_finally.sh`
- Unit tests for workspace resolution, glob timeout, macOS shell guard, discovery hints
