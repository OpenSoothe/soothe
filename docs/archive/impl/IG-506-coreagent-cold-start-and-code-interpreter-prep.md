# IG-506: CoreAgent Cold Start and Code Interpreter Execute Prep

**Status**: Implemented  
**Created**: 2026-06-26  
**Related**: IG-476 (fresh-loop plan-assess skip), IG-477 (ephemeral execute graph)

## Problem

Loop `d9bd` log analysis showed two fixed costs before useful execute work:

| Phase | Duration | Cause |
|-------|----------|-------|
| CoreAgent cold start | ~5.3s | `create_deep_agent()` on every new `SootheRunner` |
| Code interpreter prep | ~5s on first execute LLM | Lazy QuickJS init via `CodeInterpreterMiddleware` on first model call |

Additionally, daemon workers create a **fresh** `SootheRunner` per request (`thread_runner.py`, `pool_runner.py`), so the ~5s graph compile repeats even on warm workers.

Planning and StrangeLoop bootstrap do **not** require a compiled CoreAgent graph until the execute node runs.

## Solution

### 1. Lazy CoreAgent materialization (default on)

- Resolve planner/policy in `SootheRunner.__init__` without compiling the LangGraph agent.
- Wrap CoreAgent in `LazyCoreAgent`; compile on first Layer-1 access (execute / quiz / checkpointer attach).
- Defer `_ensure_checkpointer_initialized()` for agentic StrangeLoop runs until quiz path or CoreAgent materialization.

**Expected gain**: ~5s removed from input → planning window (overlaps with planning LLM when both run sequentially today).

Config: `agent.runtime.lazy_core_agent` (default `true`).

### 2. Lazy ephemeral execute graph (IG-477 extension)

- Store an execute-graph compile callback on `CoreAgent` instead of compiling the checkpointer-free twin at build time.
- Compile on first `execution_graph` access.

**Expected gain**: Up to ~5s when checkpointer is present at build time (avoids double compile at startup).

### 3. Skip CodeInterpreter middleware when PTC allowlist is empty

- `CodeInterpreterMiddleware` only mounts when `code_interpreter.enabled` **and** `ptc_allowlist` is non-empty.
- Empty allowlist still means no `tools.*` exposure; mounting only added QuickJS startup cost on first execute LLM turn.

**Expected gain**: ~5s on first execute model call for typical file-tool workloads.

### 4. Reuse SootheRunner per daemon worker (default on)

- Thread pool and worker pool keep one `SootheRunner` per worker thread/process.
- Call `prepare_for_request()` between requests to clear query-scoped mirrors (IG-110).
- Optional warmup creates the runner at worker startup (amortizes first-query cold start).

Config (daemon):

- `thread_pool.reuse_runner` (default `true`)
- `thread_pool.warmup_runner` (default `true`)
- `worker_pool.reuse_runner` / `worker_pool.warmup_runner` (same semantics)

**Expected gain**: ~5s on every request after the first on a worker (graph stays compiled).

## Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/core/agent/_lazy.py` | New `LazyCoreAgent` wrapper |
| `packages/soothe/src/soothe/core/agent/_builder.py` | Lazy execute graph compile callback |
| `packages/soothe/src/soothe/core/agent/_core.py` | Lazy `execution_graph` materialization |
| `packages/soothe/src/soothe/runner/__init__.py` | Lazy agent, protocol resolution, `prepare_for_request()` |
| `packages/soothe/src/soothe/runner/_runner_strange_loop.py` | Defer checkpointer until quiz / materialize |
| `packages/soothe/src/soothe/middleware/_builder.py` | Skip CI when allowlist empty |
| `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` | Runner reuse + warmup |
| `packages/soothe-daemon/src/soothe_daemon/runner/pool_runner.py` | Runner reuse + warmup |
| `packages/soothe/src/soothe/config/models.py` | `AgentRuntimeConfig` |
| `packages/soothe-daemon/src/soothe_daemon/config/models.py` | Pool reuse/warmup flags |
| `config/config.template.yml` | `agent.runtime` section |
| `config/develop/config.yml` | Matching structure |
| `config/daemon.template.yml` | Pool reuse/warmup flags |

## Testing

- Unit: `LazyCoreAgent` defers factory until graph/execution access.
- Unit: middleware stack excludes CI when `enabled=true` and `ptc_allowlist=[]`.
- Unit: `CoreAgent.execution_graph` compiles twin lazily when callback set.
- Unit: `SootheRunner.prepare_for_request()` clears query-scoped state without dropping agent.

## Verification

```bash
./scripts/verify_finally.sh
```

Manual: tail `~/.soothe/logs/soothe.log` for a fresh loop — `[Init] Deep agent graph created` should appear near first execute, not at worker request start (when lazy + reuse enabled).

## Rollback

- Set `agent.runtime.lazy_core_agent: false` for eager CoreAgent build.
- Set `thread_pool.reuse_runner: false` for per-request runner isolation.
- Re-enable CI with explicit `ptc_allowlist` entries when PTC is required.
