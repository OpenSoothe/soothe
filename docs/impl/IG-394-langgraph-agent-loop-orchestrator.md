# IG-394: LangGraph Agent Loop Orchestrator (RFC-620)

**Status**: In Progress (graph shell + iteration extraction landed; optional bounded gather / Track-B checkpointing remain)  
**RFC**: [RFC-620](../specs/RFC-620-langgraph-agent-loop-orchestrator.md)  
**Created**: 2026-05-05  

---

## Purpose

Implement Layer 2 goal execution as a **compiled LangGraph Loop Graph**, delete the imperative `AgentLoop.run_with_progress` driver, enforce **`loop_id` vs `thread_id`** checkpoint isolation, and ship **evidence-bound plan steps** with bounded gather + validation. **No backward compatibility** with the removed driver or dual orchestration paths.

---

## Success Criteria

1. Single entry path from runner/daemon into Layer 2 is the **compiled Loop Graph**.
2. Loop Graph LangGraph configurable/checkpointer identity uses **`loop_id`** only; CoreAgent uses **`thread_id`** — verified by unit tests.
3. **`StepAction`** carries **`evidence_refs`**; **`validate_evidence_bindings`** rejects invalid plans within repair caps.
4. `./scripts/verify_finally.sh` passes.
5. Dependent specs listed under **Documentation reconciliation** are updated in-repo so they no longer describe the imperative loop.

---

## Architecture Summary

| Component | Responsibility |
|-----------|----------------|
| `LoopGraphBuilder` / package | `StateGraph` definition, compile with Loop checkpointer |
| Graph nodes | Thin wrappers delegating to existing planner, executor, state manager, anchors, goal completion |
| `LoopState` + ledger | Extended state including `evidence_ledger`, validation counters |
| Runner adapter | `graph.astream` → existing progress event tuples / stream contract |
| Removed | Imperative `while` loop body in `agent_loop.py` (or file replaced by graph facade) |

---

## Implementation Tasks

### 1. State and schemas

- [ ] Add `EvidenceEntry` model and `evidence_ledger: list[EvidenceEntry]` to loop execution state (alongside `LoopState` or merged graph state TypedDict).
- [ ] Add **`evidence_refs: list[str]`** to `StepAction`; enforce non-empty when ledger non-empty (validators + prompts).
- [ ] Add optional **`validation_feedback`**, **`evidence_repair_round`** (or similar) for bounded repair loops.

### 2. Loop Graph package

Suggested layout (adjust to repo conventions):

```
packages/soothe/src/soothe/core/agent_loop/graph/
  __init__.py
  builder.py          # compile graph, attach checkpointer
  state.py            # graph state TypedDict / reducer annotations
  nodes/
    init.py
    iteration_start.py
    assess.py
    evidence_gather.py
    plan.py
    validate_bindings.py
    execute.py
    record_iteration.py
    goal_completion.py
  routing.py          # conditional edge functions
  streaming.py        # map LangGraph stream → runner events
```

- [ ] Implement nodes delegating to existing `PlanPhase` / `LLMPlanner` splits, `Executor`, `AgentLoopStateManager`, `CheckpointAnchorManager`, `SynthesisGenerator`, `determine_completion_action`.
- [ ] Wire conditional edges per RFC-620 topology.

### 3. Identity isolation

- [ ] Compile Loop Graph with checkpointer; **`thread_id` in configurable = `loop_id`** for this graph only (document as loop checkpoint key in code comments).
- [ ] Never pass conversation `thread_id` into Loop Graph checkpoint config.
- [ ] Add tests that fail if keys are swapped.

### 4. Bounded evidence gather

- [ ] Config: `max_tool_calls`, tool allowlist (read-biased default set), optional skip predicates aligned with RFC-620 (only normative skips).
- [ ] Invoke CoreAgent (or narrowed tool runner) with strict caps; append ledger rows via RFC-211-style metadata summarization.
- [ ] Emit ledger IDs stable for the current goal iteration.

### 5. Validation node

- [ ] Resolve each `evidence_refs` id against ledger and/or completed step ids (cross-plan refs per existing dependency rules).
- [ ] On failure: increment repair round; route to `plan_generate` with feedback; optionally `bounded_evidence_gather` when refs are hallucinated.
- [ ] Hard cap on total repairs; on exceed → terminal error event (same class as today’s fatal/replan semantics — define in node).

### 6. Runner integration

- [x] `invoke_agent_loop_graph` uses `merge_langfuse_runnable_config` with run name `{trace_name}:agent-loop-graph`, session = conversation `thread_id`, configurable `thread_id` = `loop_id`; metadata includes `loop_id` (IG-367 bridge).
- [x] Replace imperative loop with compiled graph + queue (`run_with_progress`).
- [ ] Preserve stream suppression rules for execute phase (IG-304) — unchanged in `loop_iteration`.
- [ ] Map graph outputs to existing event sequence expected by CLI/daemon (adjust **only** if RFC-614 / event catalog updated in same PR).

### 7. Delete imperative driver

- [ ] Remove `while state.iteration < max_iterations` orchestration from `agent_loop.py`; replace with thin `AgentLoop` facade that **only** compiles/invokes the graph **or** delete class if runner talks to graph directly (pick one shape; avoid duplicate facades).
- [ ] Remove obsolete helpers only used by the old loop (grep-led cleanup).

### 8. Configuration

- [ ] Add keys under `SootheConfig` / `agentic` (exact paths in PR): evidence caps, allowlist, repair bounds.
- [ ] Update `packages/soothe/src/soothe/config/config.yml` **and** `config/config.dev.yml` in lockstep.

### 9. Tests

- [ ] Unit: each routing function and validator.
- [ ] Unit: isolation test `loop_id` ≠ `thread_id` for checkpoint keys.
- [ ] Integration: resume running checkpoint; max iterations; fatal execute; validation repair exhaust.
- [ ] Migrate or replace tests that assumed the async generator imperative loop (update fixtures).

### 10. Documentation reconciliation

Update or add pointers so nothing contradicts RFC-620:

- [ ] `CLAUDE.md` — Layer 2 description points to Loop Graph + RFC-620.
- [ ] `docs/specs/RFC-201-*.md` — banner or section: imperative driver superseded by RFC-620 (keep conceptual sections).
- [ ] Touch as needed: RFC-203, RFC-214, RFC-216, RFC-217 snippets that reference the hand-written loop.

---

## Explicit Non-Goals (IG scope)

- Changing CoreAgent / deepagents construction beyond Execute wiring.
- Layer 3 GoalEngine API changes.
- Long-lived feature flags for “old loop vs new loop”.

---

## Verification

```bash
./scripts/verify_finally.sh
```

---

## Rollback

Cut-over: rollback is **revert the merge** (Git), not runtime toggles.

---

## References

- RFC-620, RFC-604, RFC-211, RFC-218, RFC-219  
- Prior related IGs: IG-372 (plan split), IG-381 (evidence / explore), IG-374 (parallel ledger)
