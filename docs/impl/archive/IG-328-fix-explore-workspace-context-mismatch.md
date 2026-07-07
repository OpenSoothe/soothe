# IG-328: Fix explore subagent workspace context mismatch

## Problem

The explore subagent searches the wrong workspace when invoked via `/explore` quick path routing.

**Observed behavior:**
- User runs: `soothe --no-tui -p "/explore count all file types of this project"` from project directory
- Thread workspace resolved correctly: `/Users/xiamingchen/Workspace/mirasurf/soothe` ✅
- Explore subagent searches: `~/.soothe/Workspace` ❌
- Results: TypeScript/JavaScript files (75 total) vs actual 874 Python files

**Daemon log shows:**
```
stream_workspace_resolved thread_id=mskzn278idn0 path=/Users/xiamingchen/Workspace/mirasurf/soothe source=explicit
Explore: glob found 1 paths (should be thousands!)
```

**Root cause:**
The resolver sets explore's `work_dir` context from `config.workspace_dir` (defaults to daemon workspace `~/.soothe/Workspace`), not from the thread's resolved workspace.

**Code trace:**

1. `runner/__init__.py:stream()` resolves thread workspace correctly:
```python
resolved = resolve_workspace_for_stream(
    explicit=workspace,
    config_workspace_dir=getattr(self._config, "workspace_dir", None),
)
effective_workspace = resolved.path  # → /Users/xiamingchen/Workspace/mirasurf/soothe ✅
state.workspace = effective_workspace
```

2. `_run_direct_subagent()` passes state to agent, but:
```python
# No mechanism to update subagent context at runtime!
# Subagents were resolved at daemon init with static context
```

3. Resolver `resolve_subagents()` called once at daemon startup:
```python
resolved_cwd = (
    str(expand_path(config.workspace_dir)) if config.workspace_dir else str(Path.cwd())
)
# → ~/.soothe/Workspace (daemon cwd)
elif name == "explore":
    extra_kwargs["context"] = {"work_dir": resolved_cwd}  # ❌ Static!
```

4. Explore uses this static `work_dir` for search:
```python
work_dir = context.get("work_dir", "")  # → ~/.soothe/Workspace ❌
workspace = work_dir
```

**Why it fails:**
- Subagents are resolved ONCE at daemon init (cached)
- Context (work_dir) is static, set from config.workspace_dir
- Thread workspace varies per request (from client cwd or explicit)
- No mechanism to inject thread workspace into subagent context at runtime

## Fix

Pass thread workspace to explore subagent at invocation time, not at resolver time.

**Approach:**
1. Inject `work_dir` from thread state into subagent invocation kwargs
2. Update `create_explore_subagent()` to accept runtime context override
3. Ensure explore uses thread workspace, not daemon config workspace

**Implementation:**

1. **runner/_runner_phases.py** (`_run_direct_subagent`):
   - Extract workspace from state
   - Pass as runtime context override to agent invoke

2. **core/agent/_patch.py** (task tool handler):
   - Inject thread workspace into subagent state before invocation
   - Override static resolver context with runtime workspace

3. **explore/implementation.py**:
   - Accept runtime context from state, not just resolver kwargs
   - Fallback to resolver context if state doesn't have workspace

## Verification

✅ All tests passing (1396 passed, 16 skipped)
- Run: `./scripts/verify_finally.sh` ✅
- Callable backend pattern works for both:
  - Thread workspace injection (runtime.state["workspace"])
  - Direct tool invocation (runtime=None, fallback to initial workspace)

**Expected behavior after fix:**
1. Explore receives thread workspace from runner via state.workspace
2. Callable backend resolves workspace at tool execution time
3. Tools search thread workspace (client cwd), not daemon workspace
4. File type counts reflect actual project (874 Python files), not TypeScript

**Test notes:**
- Direct tool invocation (without LangGraph) works via backend(None) fallback
- Thread workspace propagates automatically through ToolRuntime injection