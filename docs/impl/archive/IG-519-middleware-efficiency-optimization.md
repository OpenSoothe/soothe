# IG-519: Middleware Efficiency Optimization

**IG**: 519
**Title**: Middleware Efficiency Optimization — Caching, Bug Fix, Cleanup
**Status**: In Progress
**Created**: 2026-06-27
**Dependencies**: RFC-105 (Skill Progressive Loading), IG-478 (Tool Concurrency)

---

## Summary

Optimize middleware execution efficiency through three targeted changes:

1. **SystemPromptMiddleware caching** — Instance-level cache for SkillIndex/ProgressiveSkillRegistry
2. **SkillActivation snapshot fix** — Guard checkpointer before aget_state call
3. **ToolConcurrencyMiddleware removal** — Dead code cleanup (limit=64 is unlimited)

Estimated per-step time savings: **~55 ms** (SystemPrompt caching only).

> **Correction (post-implementation):** Removing `ToolConcurrencyMiddleware`
> from `build_soothe_middleware_stack` also removed its side effect of calling
> `record_tool_call_args_from_request()`, which populates the per-thread args
> registry the executor's stream path reads (`ingest_invocation_registry`) to
> attach tool-call kwargs to wire events. With nothing recording args on the
> main path, the TUI stopped showing tool-call args on step and non-explore
> subagent activities. Fix: the extracted `ToolCallArgsMiddleware` is wired into
> **both** the explore subagent stack (`build_explore_middleware_stack`) **and**
> the main CoreAgent stack (`build_soothe_middleware_stack`). See
> "ToolConcurrencyMiddleware Removal" below.

---

## Scope

| In Scope | Out of Scope |
|----------|--------------|
| SkillIndex instance caching in SystemPromptMiddleware | ProgressiveTools per-step binding (already fast) |
| Checkpointer guard for skill_activation snapshot | SkillIndex cache invalidation strategy changes |
| ToolConcurrencyMiddleware removal | Semantics changes to skill activation |

---

## Motivation

### Problem Analysis (from log analysis)

| Issue | Root Cause | Per-Step Impact |
|-------|------------|-----------------|
| SkillIndex rebuild per-hop | `SkillIndex()` instantiated in `_compose_skills_block()` on every LLM hop | 2.7 ms × 22 hops = **59 ms** |
| SkillActivation failure | `aget_state()` called without checkpointer → ValueError | Functional bug (no perf impact) |
| ToolConcurrency middleware | `limit=64` means semaphore never blocks | Dead code (0.002 ms negligible) |

### Key Insight

The `SkillIndex` already has internal mtime-based caching (`rebuild_if_stale()`). However, creating a fresh `SkillIndex()` instance on every hop forces cache reload overhead. By caching the instance on the middleware, we eliminate the re-instantiation cost while preserving the mtime-based freshness check.

---

## Files

| File | Action |
|------|--------|
| `docs/impl/IG-519-middleware-efficiency-optimization.md` | **Create** — this document |
| `middleware/system_prompt.py` | **Modify** — add instance-level caching |
| `middleware/tool_concurrency.py` | **Delete** — dead code |
| `middleware/tool_call_args_middleware.py` | **Create** — extracted args-recording middleware (semaphore dropped) |
| `middleware/_builder.py` | **Modify** — remove ToolConcurrencyMiddleware, **add ToolCallArgsMiddleware** to preserve args recording on main path |
| `middleware/tool_timeout.py` | **Modify** — remove ToolConcurrency import |
| `foundation/sloop/engine/executor.py` | **Modify** — checkpointer guard + replace init import with `init_tool_call_args_registry` |
| `tests/unit/middleware/test_tool_concurrency.py` | **Delete** — if exists |
| `tests/unit/middleware/test_tool_call_args_registry.py` | **Modify** — add regression test: main stack mounts `ToolCallArgsMiddleware` |

---

## Implementation Sequence

1. Create IG document (this file)
2. Add `self._skill_index` / `self._skill_registry` lazy-init to SystemPromptMiddleware
3. Add checkpointer guard in executor `_snapshot_skill_activation` section
4. Remove ToolConcurrencyMiddleware from `_builder.py` stack
5. Remove `init_tool_concurrency_for_thread` import/call from executor
6. Delete `tool_concurrency.py` file
7. Run `./scripts/verify_finally.sh`

---

## Detailed Design

### 1. SystemPromptMiddleware Caching

**Current code (`system_prompt.py:689-697`):**
```python
def _compose_skills_block(self, state):
    from soothe.skills.index import SkillIndex
    from soothe.skills.registry import ProgressiveSkillRegistry

    skill_index = SkillIndex()  # Fresh instance every hop
    entries = skill_index.rebuild_if_stale()  # Cache reload overhead
    registry = ProgressiveSkillRegistry()
    ...
```

**Proposed change:**
```python
# In __init__
self._skill_index: SkillIndex | None = None
self._skill_registry: ProgressiveSkillRegistry | None = None

# In _compose_skills_block
def _compose_skills_block(self, state):
    # Lazy-init (preserved across hops within same middleware instance)
    if self._skill_index is None:
        from soothe.skills.index import SkillIndex
        self._skill_index = SkillIndex()
    if self._skill_registry is None:
        from soothe.skills.registry import ProgressiveSkillRegistry
        self._skill_registry = ProgressiveSkillRegistry()

    entries = self._skill_index.rebuild_if_stale()  # Uses cached entries, mtime check
    ...
```

**Cache invalidation:**
- `rebuild_if_stale()` already checks mtime on every call
- If SKILL.md files change, the method re-parses automatically
- No additional invalidation logic needed

**Thread safety:**
- SystemPromptMiddleware is per-CoreAgent instance
- CoreAgent instances are not shared across threads
- Safe for concurrent use in thread-pool daemon

### 2. SkillActivation Snapshot Fix

**Current code (`executor.py:1631-1642`):**
```python
# RFC-105: Snapshot skill_activation from graph state back into LoopState
if loop_state is not None:
    try:
        graph_state = await self.core_agent.aget_state(
            config={"configurable": {"thread_id": fork_thread_id}},
        )
        if graph_state and graph_state.values:
            self._snapshot_skill_activation(graph_state.values, loop_state)
    except Exception:
        logger.debug("[Skill] Failed to snapshot skill_activation from graph state")
```

**Problem:**
- `aget_state()` requires a checkpointer
- CLI mode runs without checkpointer → ValueError every step
- Skill activation state is NOT persisted between steps

**Proposed change:**
```python
# RFC-105: Snapshot skill_activation from graph state back into LoopState
if loop_state is not None:
    # Only snapshot when checkpointer is configured (state lives in graph)
    # Without checkpointer, skill_activation lives in LoopState middleware hooks
    if self.core_agent.checkpointer is not None:
        try:
            graph_state = await self.core_agent.aget_state(
                config={"configurable": {"thread_id": fork_thread_id}},
            )
            if graph_state and graph_state.values:
                self._snapshot_skill_activation(graph_state.values, loop_state)
                self._snapshot_mcp_state(graph_state.values, loop_state)
                self._snapshot_tool_activation(graph_state.values, loop_state)
        except Exception:
            logger.debug("[Skill] Failed to snapshot skill_activation from graph state")
```

**Behavior change:**
- With checkpointer: Same behavior (snapshot from graph state)
- Without checkpointer: skill_activation updated via middleware hooks only (correct for CLI mode)

### 3. ToolConcurrencyMiddleware Removal

**Analysis:**
- `max_parallel_tools = 64` from config
- Average parallelism: 3-10 tools per LLM hop
- Semaphore never blocks (limit far exceeds demand)
- Middleware provides no actual limiting

**Removal scope:**
1. `_builder.py`: Remove `ToolConcurrencyMiddleware` import and stack append, **but re-add the extracted `ToolCallArgsMiddleware`** to preserve args recording on the main CoreAgent path (step + non-explore subagent activities). Without this, the TUI shows no tool-call args.
2. `executor.py`: Remove `init_tool_concurrency_for_thread` import and call; call `init_tool_call_args_registry()` directly instead.
3. `tool_concurrency.py`: Delete file (or leave with DEPRECATED marker for documentation).
4. `tool_call_args_middleware.py`: New lightweight middleware holding only the args-recording side effect (semaphore dropped). Wired into both `build_soothe_middleware_stack` and `build_explore_middleware_stack`.
5. Tests: Delete concurrency test; add a regression test asserting the main stack mounts `ToolCallArgsMiddleware`.

**Future consideration:**
If tool concurrency limiting becomes necessary, re-add middleware with:
- Default limit: 10-20 (actual contention)
- Per-step semaphore instead of per-thread
- Integration with budget tracking

---

## Success Criteria

1. SystemPromptMiddleware caches SkillIndex across hops
2. SkillActivation snapshot only called when checkpointer exists
3. ToolConcurrencyMiddleware removed from stack
4. All tests pass (`./scripts/verify_finally.sh`)
5. No "Failed to snapshot skill_activation" logs in CLI mode

---

## References

- Log analysis: `~/.soothe/logs/soothe.log` (steps averaging 500s, 46 tools/step)
- RFC-105: Skill Progressive Loading
- IG-478: Tool Concurrency Middleware (original implementation)