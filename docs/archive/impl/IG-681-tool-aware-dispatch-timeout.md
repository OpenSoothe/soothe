# IG-681: Tool-Aware Dispatch Timeout

**Created**: 2026-08-04
**Status**: Complete
**Incident**: loop `019fca61-d252-7b63-93b9-6737ec4f9e20` (`9e20`)
**Related**: IG-549 (heartbeat sentinel), IG-668 (assess envelope stall)

## Problem

Loop `9e20` hung for 30+ minutes on step `BBV-04` after Tool#17 returned a Gradle
build failure. The LangGraph runtime stalled scheduling the next LLM hop — no
chunks, no LLM observability, no role routing. The heartbeat sentinel mechanism
(IG-549) kept the stream alive every 10s (184 sentinels emitted), but the dispatch
watchdog was **disabled**, so the step hung indefinitely.

Root cause: a single inactivity threshold could not distinguish between:
1. **True deadlocks** (no tool active, no chunks) — should fail fast
2. **Legitimate long-running tools** (Gradle compile, browser_use, web search) —
   should be allowed to run

## Fix

Introduce **two orthogonal timeouts** with root pending-tool awareness:

| Field | Default | Purpose |
|-------|---------|---------|
| `dispatch_idle_seconds` | `300` | **Deadlock detector**: fires when no chunks arrive AND no root tool is pending. |
| `dispatch_tool_timeout_seconds` | `0` (disabled) | **Optional tool-wave wall-clock**. Prefer `agent.middleware.tool_timeout` in `nano.yml` for per-tool budgets. |

### Ownership

| Knob | File |
|------|------|
| `agent.loop.dispatch_idle_seconds` / `dispatch_tool_timeout_seconds` | `soothe.yml` (host) |
| `agent.middleware.tool_timeout` / `llm_rate_limit` / `tool_output` / … | `nano.yml` (nano) |

Do not put nano middleware knobs under `agent.loop`.

### Tool-boundary detection

`GraphStreamChunkReader` classifies chunks via `_classify_stream_chunk()`:

- **`tool_dispatch`**: root-namespace AIMessage with tool calls
- **`tool_result`**: root-namespace ToolMessage
- **`chunk`**: other real chunks (including nested subgraph msgs — progress only)
- **`sentinel`**: heartbeat (not real progress)

Pending state is a **set of tool_call ids**. Idle / sentinel-cap fire only when empty.
Sentinel cap is **suspended while tools are pending**.

### Config

```yaml
# soothe.yml (host)
agent:
  loop:
    dispatch_idle_seconds: 300
    dispatch_tool_timeout_seconds: 0

# nano.yml (nano) — per-tool middleware budgets
agent:
  middleware:
    tool_timeout:
      enabled: true
      default_seconds: 60.0
      per_tool:
        browser_use: 1800.0
        task: 18000.0
```

## Files Changed

| File | Change |
|------|--------|
| `graph_interrupt.py` | Pending-tool id set, root-namespace boundaries, tool-aware sentinel |
| `config/models.py` | Idle/tool fields; reject nano middleware + legacy keys under loop |
| `executor.py` / `planner.py` | Read tool_output / llm_rate_limit from `agent.middleware` |
| Templates | Host dispatch fields only; nano middleware only; no legacy |
