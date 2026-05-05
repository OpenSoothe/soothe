# IG-396: RFC-220 Loop Graph topology, spec renumber, Langfuse bridge

**Status**: In Progress  
**RFC**: [RFC-220](../specs/RFC-220-langgraph-agent-loop-orchestrator.md)  
**Created**: 2026-05-05  

---

## Purpose

1. Align the compiled Loop Graph **node topology** with RFC-220 (formerly drafted as RFC-620): thin LangGraph nodes per phase instead of a single mega-node, preserving behavior via `LoopRuntimeContext` + `LoopPhaseScratch`.
2. Renumber the specification into the **AgentLoop 2xx series** as **RFC-220** (file rename + index/history + references).
3. **Bridge AgentLoop to Langfuse**: enrich RunnableConfig metadata/tags on `invoke_agent_loop_graph` so traces are filterable (`soothe_component`, `soothe_rfc`, tags) while keeping `loop_id` vs conversation `thread_id` isolation and IG-395 trace I/O patching.

---

## Verification

```bash
./scripts/verify_finally.sh
```

---

## References

- IG-394, IG-367, IG-395  
- `packages/soothe/src/soothe/core/agent_loop/graph/`
