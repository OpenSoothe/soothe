# IG-344: Thread Workspace Awareness and Isolation Fixes

## Status: In Progress

## Problem

Two workspace-related bugs:

1. **Explore resolver shows wrong path**: The explore engine log shows
   `resolver='/Users/.../.soothe/Workspace'` because subagents are built at
   agent init time using `config.workspace_dir` (the daemon default), not the
   thread workspace. The IG-328 runtime override works correctly, but the
   resolver/build-time workspace should ideally reflect the thread workspace.

2. **Runtime uses wrong cwd**: CLI starts with cwd
   `/Users/.../soothe` but runtime uses `/Users/.../soothe/packages/soothe-cli`.
   Root cause: The TUI launch function (`app.py:5708-5713`) reads
   `config.workspace_dir` instead of `os.getcwd()`. The headless CLI path
   (`daemon.py:54`) only uses `SOOTHE_CLI_WORKSPACE` env var, falling back to
   `Path.cwd()` in `bootstrap_thread_session` which captures the process cwd
   (which may differ from the user's shell cwd if the process was launched
   from a different directory).

## Root Causes

### TUI workspace resolution (`soothe-cli/tui/app.py:5708-5713`)
```python
configured_workspace = getattr(config, "workspace_dir", None)
cwd = None
if isinstance(configured_workspace, str) and configured_workspace.strip():
    workspace_value = configured_workspace.strip()
    if workspace_value != ".":
        cwd = workspace_value  # Uses config default, not actual user cwd!
```
This ignores the user's actual shell cwd and uses `config.workspace_dir`
(which defaults to `~/.soothe/Workspace` after the model validator coercion).

### Headless CLI workspace (`soothe-cli/cli/execution/daemon.py:54`)
```python
cli_ws = os.environ.get("SOOTHE_CLI_WORKSPACE", "").strip()
# Falls back to None, which means bootstrap_thread_session uses Path.cwd()
```
`Path.cwd()` captures the daemon client process cwd, not the user's shell cwd.

### Resolver uses config.workspace_dir for subagent/tool init (`_resolver_tools.py:528-530`)
```python
resolved_cwd = (
    str(expand_path(config.workspace_dir)) if config.workspace_dir else str(Path.cwd())
)
```
This uses the daemon config default (`~/.soothe/Workspace`) at build time.
Thread workspace override only happens at runtime via state injection (IG-328).

## Fix

### Fix 1: TUI launch should prefer `os.getcwd()` over `config.workspace_dir`
The TUI launch function should use the actual process cwd as default, only
overriding with `config.workspace_dir` if it's a non-default explicit user
setting. Since we can't reliably detect "user explicitly set this", always
use `os.getcwd()` as the workspace — the user's cwd is the correct workspace.

### Fix 2: Headless CLI should use `os.getcwd()` as explicit default
Instead of relying on `Path.cwd()` inside `bootstrap_thread_session`, pass
`os.getcwd()` explicitly from the headless CLI entry point.

### Fix 3: Improve log clarity for explore resolver workspace
The resolver workspace being `~/.soothe/Workspace` is expected (it's the
build-time default). The debug log at engine.py:141-146 is confusing because
it always fires when thread workspace differs from resolver. This is normal
and expected. Reduce log level or clarify the message.

## Files Changed

- `packages/soothe-cli/src/soothe_cli/tui/app.py` (TUI launch workspace)
- `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py` (headless workspace)
- `packages/soothe/src/soothe/subagents/explore/engine.py` (log clarity + ToolNode workspace)

## Additional Fix: Explore ToolNode workspace injection

### Root Cause
The explore engine's `execute_action_node` calls `tool_node.invoke({"messages": ...})`
passing only `messages`. LangGraph's `ToolNode._extract_state()` returns this dict as
the `ToolRuntime.state`. Since `workspace` is not in the dict, the callable backend
(`_create_thread_workspace_backend`) receives `None` for `runtime.state.get("workspace")`
and falls back to `initial_workspace` — the stale resolver default (`~/.soothe/Workspace`).

With `virtual_mode=True`, the `FilesystemBackend.cwd` becomes `~/.soothe/Workspace`, so
all glob/grep/ls operations are scoped to that empty directory instead of the actual
project workspace.

### Fix
Pass `workspace` from `ExploreState` into the `tool_node.invoke()` dict so `ToolRuntime.state`
includes it. The callable backend then correctly resolves the thread workspace.

```python
# Before
tool_results = tool_node.invoke({"messages": tool_messages_input})

# After
tool_invoke_input = {"messages": tool_messages_input}
thread_workspace = state.get("workspace")
if thread_workspace:
    tool_invoke_input["workspace"] = thread_workspace
tool_results = tool_node.invoke(tool_invoke_input)
```
