# IG-300: Shell `cd` to client-declared workspace

## Goal

Ensure `run_command` (and related shell recovery) uses the workspace path from the client / Source (`configurable["workspace"]`) as the shell cwd, including when LangGraph executes tools on a thread pool where `get_config()` is unavailable.

## Approach

- Accept LangGraph-injected `ToolRuntime` on `RunCommandTool._run` / `_arun` (and `run_background`), annotated as `Annotated[ToolRuntime | None, InjectedToolArg()]` so OpenAI `bind_tools` JSON schema omits `runtime` (optional unions are not auto-detected as injected).
- Resolve effective workspace with priority: `ToolRuntime` (`configurable["workspace"]` **or** latest `LoopHumanMessage.workspace` in `runtime.state["messages"]`) → `get_config()` → `FrameworkFilesystem` → static `workspace_root`.
  - The state message fallback covers sync tools on LangGraph’s thread pool where `get_config()` is empty and the per-call config copy omits `workspace` even though the AgentLoop human turn carried it.
- Use that path for initial shell `cd`, post-recovery `cd`, and per-command `cd` when it changes.

## Status

Implemented in `packages/soothe/src/soothe/toolkits/execution.py`.
