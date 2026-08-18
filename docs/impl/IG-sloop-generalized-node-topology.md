# StrangeLoop: Generalized Node Pattern & Simplified Topology Proposal

> Design doc synthesizing patterns discovered in the IHQ-01 inventory of the
> StrangeLoop LangGraph codebase (`packages/soothe/src/soothe/sloop/`).
> Status: **Draft for review** — no code changes proposed yet.

---

## 1. Executive Summary

The current Sloop graph is a single compiled `StateGraph(LoopGraphState)` with
**14 nodes**, **7 unconditional edges**, and **11 conditional edges** (each with
its own `route_after_*` function). Nodes share a strong structural shape — every
node is `async def(ctx, state) -> dict` that reads `ctx`/`state`, does work,
emits events, and returns routing-channel updates — but that shape is implicit:
there is no base class, no shared lifecycle hooks, and no uniform error/fatal
contract.

This document proposes:

1. **A generalized node pattern abstraction** (`LoopNode` protocol + lifecycle
   hooks) that makes the implicit shape explicit, testable, and uniform.
2. **A simplified, more robust topology** that collapses the plan→execute
   pipeline's serial validation chokepoints into fewer conditional edges while
   preserving all current routing semantics.
3. **Discussion points** for review before any implementation.

---

## 2. Evidence: Current Node Shape (from IHQ-01)

### 2.1 Uniform signature

All 14 nodes conform to:

```python
async def node_*(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]
```

The builder (`orchestrator/builder.py:91-131`) wraps each in a closure that
binds `ctx`, producing the `async def(state) -> dict` LangGraph expects.

### 2.2 Common internal phases

Inspecting representative nodes (`intake`, `enter_loop`, `generate_plan`,
`evaluate`, `commit_plan`, `validate_plan`, `execute`, `record_progress`,
`check_limits`, `begin_iteration`, `finalize`) reveals a recurring internal
sequence:

| Phase | What happens | Evidence |
|-------|--------------|----------|
| **Guard / precondition** | Check scratch/ctx for required inputs; if missing, emit `fatal_error` + return `{"last_outcome": "fatal"}` | `commit_plan.py:42-48`, `validate_plan.py:22-28`, `generate_plan.py:44-49`, `record_progress.py:30-36` |
| **Status emission** | Emit a TUI status label (`emit_plan_phase_status`, `ctx.emit("iteration_started", ...)`) | `generate_plan.py:72`, `begin_iteration.py:20-26`, `evaluate.py:33-34` |
| **Core work** | LLM call, CoreAgent dispatch, deterministic transform, or persistence | `generate_plan.py:78-100`, `execute.py:251+`, `commit_plan.py:50-85` |
| **State mutation** | Write to `ctx.loop_state`, `ctx.scratch`, `ctx.plan_manager`, `ctx.ce` | `commit_plan.py:80-85`, `record_progress.py:39-80`, `begin_iteration.py:18` |
| **Event emission** | `ctx.emit(...)` for TUI/observability | nearly all nodes |
| **Route key return** | Return dict with routing channels (`last_outcome`, `plan_route`, `assess_route`, etc.) | `generate_plan.py:23` (`_PLAN_GENERATE_FATAL`), `begin_iteration.py:37`, `check_limits.py:44,60` |

### 2.3 The fatal contract (informal)

Multiple nodes repeat the same fatal pattern:

```python
await ctx.emit("fatal_error", {"error": "<msg>", "step_id": ""})
return {"last_outcome": "fatal"}
```

Found in: `commit_plan.py:44-48`, `validate_plan.py:24-28`, `generate_plan.py:45-49`,
`record_progress.py:32-36`. Each hardcodes the emit+return pair with no shared
helper. Routers (`routing.py`) then check `state.get("last_outcome") == "fatal"`
in `route_after_resolve_decision`, `route_after_validate_evidence`,
`route_after_execute`, `route_after_plan`, `route_after_wired_subagent` — five
separate fatal checks.

### 2.4 The clarification-yield contract (informal)

Five routers repeat `_pending_clarification(state)` as a first-branch guard:

```python
if _pending_clarification(state):
    return AWAIT_USER
```

Found in: `route_after_plan`, `route_after_evaluate`, `route_after_execute`,
`route_after_wired_subagent`, `route_after_clarification`. This is a cross-cutting
concern inlined into every router rather than centralized.

### 2.5 Scratch-vs-state split

Rich planner outputs (`PlanResult`, `AgentDecision`, `StatusAssessment`,
`StepExecutionRecord[]`) live on `ctx.scratch: LoopPhaseScratch` (non-serialized),
while only routing keys live on the LangGraph `LoopGraphState` (serialized,
checkpoint-safe). This split is correct but undocumented at the node level — each
node independently "knows" to read from `ctx.scratch` rather than `state`.

---

## 3. Proposed: Generalized Node Pattern

### 3.1 `LoopNode` protocol

```python
class LoopNode(Protocol):
    """Generalized StrangeLoop graph node contract."""

    station: ClassVar[str]  # canonical station id from stations.py

    async def precheck(self, ctx: LoopRuntimeContext, state: dict) -> NodeGuard | None:
        """Return None to proceed, or a NodeGuard (e.g. FatalGuard,
        SkipGuard) to short-circuit with a standard route-key dict."""

    async def run(self, ctx: LoopRuntimeContext, state: dict) -> NodeResult:
        """Core work. Returns a NodeResult carrying route keys + events."""

    async def postrun(self, ctx: LoopRuntimeContext, result: NodeResult) -> dict:
        """Optional post-work mutation/persistence. Defaults to returning
        result.route_keys."""
```

### 3.2 Lifecycle hooks (mapped to current ad-hoc patterns)

| Hook | Replaces (current ad-hoc) | Purpose |
|------|----------------------------|---------|
| `precheck` | The `if plan_result is None: emit+return fatal` blocks | Uniform precondition guard; single fatal contract |
| `run` | The core work body of each node | The actual LLM/dispatch/transform |
| `postrun` | Scattered `ctx.ce.defer_save()`, `plan_manager.ingest_plan(...)` | Post-work persistence, separated from logic |

### 3.3 Standard guard/result types

```python
@dataclass
class NodeResult:
    route_keys: dict[str, Any]        # merged into graph state
    events: list[tuple[str, dict]] = field(default_factory=list)

@dataclass
class FatalGuard:
    error: str
    step_id: str = ""
    route_keys: dict = field(default_factory=lambda: {"last_outcome": "fatal"})

    async def apply(self, ctx) -> dict:
        await ctx.emit("fatal_error", {"error": self.error, "step_id": self.step_id})
        return self.route_keys
```

### 3.4 Benefits

1. **Fatal contract centralized**: one `FatalGuard.apply` replaces 5+ hand-rolled emit+return pairs.
2. **Clarification yield centralized**: a `ClarificationYieldGuard` in `precheck` replaces 5 inlined `_pending_clarification` router checks (see §4.3).
3. **Testability**: each node's `run` becomes a pure function of `(ctx, state) → result`, testable without graph compilation.
4. **Observability**: the `LoopNode` wrapper can auto-emit `node_started`/`node_completed` events with timing, replacing per-node `emit_plan_phase_status` calls.
5. **Documentation**: the protocol docstring becomes the single source of truth for "how a Sloop node works."

### 3.5 Migration path (non-breaking)

- Introduce `LoopNode` as an opt-in protocol; existing `node_*` functions continue to work.
- Add a `wrap_node(station, node_fn)` adapter in `builder.py` that detects whether the target is a `LoopNode` (uses hooks) or a legacy function (current behavior).
- Migrate nodes one at a time, starting with the simplest (`begin_iteration`, `check_limits`, `validate_plan`) to validate the pattern.
- Do NOT rewrite `execute` or `finalize` in the first pass — they are the most complex and benefit least from abstraction.

---

## 4. Proposed: Simplified Robust Topology

### 4.1 Current topology pain points

| Issue | Evidence |
|-------|----------|
| **Serial validation chokepoints** | `commit_plan → validate_plan → execute` is a 3-node chain where `validate_plan` only checks `last_outcome == "fatal"` then routes to `execute`. The `route_after_resolve_decision` and `route_after_validate_evidence` routers are nearly identical fatal-guards. |
| **Duplicate fatal-check routers** | 5 routers (`route_after_resolve_decision`, `route_after_validate_evidence`, `route_after_execute`, `route_after_plan`, `route_after_wired_subagent`) all start with `if last_outcome == "fatal": return END/...` |
| **Duplicate clarification guards** | 5 routers inline `_pending_clarification(state) → AWAIT_USER` |
| `begin_iteration → gather_evidence` unconditional edge + `check_limits → begin_iteration` conditional | The `check_limits → begin_iteration → gather_evidence` path is always taken on non-terminal; `begin_iteration` is a pure setup node that could fold into `check_limits` or `gather_evidence`. |
| **`resume_synth` special-case routing** | `route_after_execute` has a special `resume_synth` branch to skip `record_progress` — a workaround for a scratch-state inconsistency, not a first-class route. |

### 4.2 Proposed simplified topology (target)

Collapse the plan→execute validation chain and centralize cross-cutting guards:

```
START → intake → enter_loop → [route_after_preprocess]
  ├→ END (chitchat)
  ├→ delegate → [route_after_delegate] → {finalize, await_user, generate_plan, END}
  ├→ commit_plan (folds validate_plan) → [route_after_commit] → {execute, END}
  └→ gather_evidence → [route_after_evidence_gather]
        → evaluate → [route_after_evaluate] → {finalize, commit_plan, generate_plan, await_user}
        → generate_plan → [route_after_plan] → {finalize, commit_plan, generate_plan, await_user}
        → commit_plan (trivial inject)

execute → [route_after_execute] → {record_progress, await_user, check_limits, END}
record_progress → [route_after_record_iteration] → {check_limits, finalize, END}
check_limits → [route_after_iteration_gate] → {gather_evidence (loop), END}
```

**Changes vs. current:**

| Change | Rationale |
|--------|-----------|
| **Fold `validate_plan` into `commit_plan`** | `validate_plan` is a single deterministic check (`validate_plan_evidence`) + fatal-guard. Move it to the tail of `commit_plan.run` / `commit_plan.postrun`. Eliminates 1 node + 2 routers (`route_after_resolve_decision`, `route_after_validate_evidence`). |
| **Fold `begin_iteration` into `check_limits`** | `begin_iteration` is pure setup (scratch reset, anchor capture, iteration_started emit). Merge into `check_limits` as the non-terminal branch. Eliminates 1 node + 1 unconditional edge. |
| **Centralize fatal-guard** | Replace 5 per-router `if last_outcome == "fatal"` checks with a single `fatal_guard(state)` decorator/wrapper on all routers. |
| **Centralize clarification-yield** | Replace 5 per-router `_pending_clarification` checks with a `clarification_guard(state)` applied as a router precondition. |
| **Eliminate `resume_synth` special-case** | Address the root cause: ensure `node_execute` always produces a valid `ctx.scratch.decision` + `plan_result` on the resume path (via the `precheck` guard), so `record_progress` can run normally. Removes the `resume_synth` channel + its router branch. |

### 4.3 Centralized router guards (code sketch)

```python
def with_standard_guards(router: RouterFn) -> RouterFn:
    """Decorator: apply fatal + clarification guards before the router's logic."""

    @functools.wraps(router)
    def wrapped(state: dict) -> str:
        if state.get("last_outcome") == "fatal":
            return END  # or a node-specific fatal target
        if _pending_clarification(state):
            return AWAIT_USER
        return router(state)

    return wrapped
```

Applied to: `route_after_evidence_gather`, `route_after_evaluate`, `route_after_plan`,
`route_after_commit`, `route_after_execute`, `route_after_record_iteration`,
`route_after_delegate`.

**Exception**: `route_after_preprocess` and `route_after_iteration_gate` do not
need the clarification guard (they run before/after the iteration loop, not
mid-pipeline).

### 4.4 Node count reduction

| | Current | Proposed | Delta |
|--|---------|----------|-------|
| Nodes | 14 | 11 | −3 |
| Conditional edges | 11 | 8 | −3 |
| Unconditional edges | 7 | 6 | −1 |
| Routers with inlined fatal-check | 5 | 0 (centralized) | −5 |
| Routers with inlined clarification-check | 5 | 0 (centralized) | −5 |

### 4.5 Topology diagram (proposed)

```text
                         ┌──────────────────────────────────────────┐
                         │              START                        │
                         └──────────────┬───────────────────────────┘
                                        ▼
                                    ┌────────┐
                                    │ intake │
                                    └────┬───┘
                                         ▼
                                  ┌──────────────┐
                                  │  enter_loop  │
                                  └──────┬───────┘
                                         │ route_after_preprocess
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
                 ┌─────────┐      ┌──────────────┐      ┌──────────┐
                 │  END    │      │  delegate    │      │ gather_  │
                 │(chitchat)│     │              │      │ evidence │
                 └─────────┘      └──────┬───────┘      └────┬─────┘
                                        │ route_after_delegate    │ route_after_evidence_gather
                                        ▼                          ▼
                              ┌──────────────────┐         ┌──────────────┐
                              │ {finalize,       │         │   evaluate   │
                              │  await_user,     │         └──────┬───────┘
                              │  generate_plan,  │                │ route_after_evaluate
                              │  END}            │                ▼
                              └──────────────────┘         ┌──────────────┐
                                                           │ generate_plan│
                                                           └──────┬───────┘
                                                                  │ route_after_plan
                                                                  ▼
                                                           ┌──────────────┐
                                                           │  commit_plan │ ← (folds validate_plan)
                                                           └──────┬───────┘
                                                                  │ route_after_commit
                                                                  ▼
                                                           ┌──────────────┐
                                                           │    execute   │
                                                           └──────┬───────┘
                                                                  │ route_after_execute
                                                                  ▼
                                                           ┌──────────────────┐
                                                           │ record_progress  │
                                                           └──────┬───────────┘
                                                                  │ route_after_record_iteration
                                                                  ▼
                                                           ┌──────────────┐
                                                           │ check_limits │ ← (folds begin_iteration)
                                                           └──────┬───────┘
                                                                  │ route_after_iteration_gate
                                                                  ▼
                                                           gather_evidence (loop) or END
```

---

## 5. Discussion Points for Review

### 5.1 Abstraction cost vs. benefit

**Question**: Is the `LoopNode` protocol worth the indirection for 14 nodes that
already work?

- **Pro**: Centralizes fatal/clarification contracts, makes node lifecycle
  testable in isolation, provides a single documentation surface.
- **Con**: Adds a layer of abstraction; `execute` and `finalize` are complex
  enough that the hooks (`precheck`/`run`/`postrun`) may not cleanly partition
  their logic.
- **Recommendation**: Adopt the protocol but do NOT force-migrate `execute` and
  `finalize` in v1. Let them remain as legacy `node_*` functions wrapped by the
  adapter until a natural refactor opportunity arises.

### 5.2 Folding `validate_plan` — is the separation load-bearing?

**Question**: Does anything depend on `validate_plan` being a separate graph
node (checkpoints, interrupts, observability)?

- `validate_plan` is deterministic (no LLM, no CoreAgent) and runs in <1ms.
- Its only router (`route_after_validate_evidence`) is a fatal-guard → `execute`.
- Folding it into `commit_plan.postrun` means the evidence check happens before
  the graph commits the checkpoint for `commit_plan`. Is that acceptable?
- **Risk**: If `validate_plan` fails, the current topology has a checkpoint at
  `validate_plan` that `commit_plan` does not. Folding means the failed
  validation checkpoint is at `commit_plan` — semantically the same (the plan
  is not yet committed), but the checkpoint cursor position changes.
- **Recommendation**: Acceptable if checkpoint cursors are keyed by station and
  the resume logic does not depend on `validate_plan` as a distinct cursor.

### 5.3 Folding `begin_iteration` — anchor capture timing

**Question**: `begin_iteration` captures the iteration start anchor
(`capture_iteration_start_anchor`). If folded into `check_limits`, the anchor is
captured at the gate, not at the "begin" step. Does this matter?

- The anchor is used for checkpoint resume (re-entering the loop at the start of
  an iteration).
- If `check_limits` captures the anchor on the non-terminal branch (before
  routing to `gather_evidence`), the anchor position is functionally identical
  to the current `begin_iteration` position.
- **Risk**: `check_limits` also handles the terminal branch (max_iterations,
  rate_limited). The anchor must only be captured on the non-terminal path.
- **Recommendation**: Safe if the anchor capture is guarded by
  `if last_outcome not in ("max_iterations", "rate_limited")`.

### 5.4 `resume_synth` elimination — root cause fix or papering over?

**Question**: The `resume_synth` channel exists because `node_execute` on the
clarification-resume path synthesizes a step result without setting
`ctx.scratch.decision` / `plan_result`, causing `record_progress` to fatal.

- **Option A (root cause)**: Fix `node_execute` to always populate
  `ctx.scratch.decision` + `plan_result` on the resume path (via `precheck`),
  then remove `resume_synth` entirely.
- **Option B (keep workaround)**: Leave `resume_synth` as a first-class route
  but document it.
- **Recommendation**: Option A, but it requires understanding the full
  clarification-resume flow (`graph_interrupt.py`, `continuation_context.py`).
  Defer to a follow-up spike before committing.

### 5.5 Should `await_user` and `delegate` remain "sidecar" nodes?

**Question**: These two nodes are topologically inline (they participate in
conditional edges) but semantically sidecars (clarification relay, subagent
dispatch). Should they be extracted to a subgraph or kept inline?

- **Pro (subgraph)**: Cleaner main topology; sidecars become pluggable.
- **Con (subgraph)**: LangGraph subgraphs add checkpoint complexity; the current
  inline design with `interrupt()` works and is tested.
- **Recommendation**: Keep inline for v1; revisit if a third sidecar is added.

### 5.6 Router guard decorator — ordering sensitivity

**Question**: The `with_standard_guards` decorator applies fatal-check then
clarification-check before the router's own logic. Is this ordering always
correct?

- Fatal should take priority (a fatal node should not route to `await_user`).
- Clarification should take priority over the node's own route (a pending
  clarification should interrupt the normal flow).
- **Edge case**: `route_after_preprocess` does NOT use the guard (it runs before
  the pipeline). `route_after_iteration_gate` checks `last_outcome` for terminal
  states but should NOT check clarification (post-iteration, not mid-pipeline).
- **Recommendation**: Make the guard opt-in per router, not blanket-applied.

### 5.7 Checkpoint key implications

**Question**: The graph checkpoint key is `{loop_id}__strange_loop`
(`checkpoint_keys.py`). Folding nodes changes the set of stations a checkpoint
can resume from. Does any resume/recovery logic depend on `validate_plan` or
`begin_iteration` as resume targets?

- `checkpointer.py` resolves the CoreAgent's `BaseCheckpointSaver`; LangGraph
  resumes from the last checkpointed node.
- If `validate_plan` is folded, a goal interrupted at the old `validate_plan`
  station would resume at `commit_plan` instead. For in-flight goals at migration
  time, this could cause a one-time resume mismatch.
- **Recommendation**: Version the checkpoint key (e.g.
  `{loop_id}__strange_loop_v2`) or add a migration shim for in-flight
  checkpoints. Needs investigation in `graph_interrupt.py` /
  `continuation_context.py`.

---

## 6. Implementation Phasing (if approved)

| Phase | Scope | Risk |
|-------|-------|------|
| **P1** | Introduce `LoopNode` protocol + `wrap_node` adapter (non-breaking) | Low |
| **P2** | Migrate simple nodes (`begin_iteration`, `check_limits`, `validate_plan`, `commit_plan`) to `LoopNode` | Low |
| **P3** | Centralize fatal + clarification guards as router decorators | Medium (touches all routers) |
| **P4** | Fold `validate_plan` into `commit_plan`; fold `begin_iteration` into `check_limits` | Medium (checkpoint cursor change) |
| **P5** | Eliminate `resume_synth` (root-cause fix in `node_execute`) | High (clarification-resume flow) |
| **P6** | Migrate `evaluate`, `generate_plan`, `gather_evidence` to `LoopNode` | Medium |
| **P7** | (Optional) Migrate `execute`, `finalize` — only if natural refactor opportunity | High |

Each phase should be a standalone PR with `./scripts/verify_finally.sh` green.

---

## 7. Verification Criteria (post-implementation)

- [ ] All existing StrangeLoop tests pass without modification (no test-cheating per AGENTS.md §8).
- [ ] `./scripts/verify_finally.sh` is green (lint, format, tests, vulture, module boundaries).
- [ ] Node count reduced from 14 → 11 (or documented why a fold was rejected).
- [ ] No router contains an inlined `if last_outcome == "fatal"` or
      `_pending_clarification` check (all centralized).
- [ ] `LoopGraphState` channels `resume_synth` removed (or documented why kept).
- [ ] Checkpoint resume tested for goals interrupted pre- and post-fold.
- [ ] `docs/diagrams/strange_loop_graph_nodes.md` and `_edges.md` regenerated via
      `scripts/visualize_strange_loop_graph.py`.

---

## 8. References (internal)

- `packages/soothe/src/soothe/sloop/orchestrator/builder.py` — graph builder
- `packages/soothe/src/soothe/sloop/orchestrator/routing.py` — 11 conditional routers
- `packages/soothe/src/soothe/sloop/orchestrator/state.py` — `LoopGraphState` channels
- `packages/soothe/src/soothe/sloop/orchestrator/runtime_context.py` — `LoopRuntimeContext`
- `packages/soothe/src/soothe/sloop/orchestrator/phase_scratch.py` — `LoopPhaseScratch`
- `packages/soothe/src/soothe/sloop/stages/` — all 14 node implementations
- `docs/diagrams/strange_loop_graph_nodes.md` — canonical node table
- `docs/diagrams/strange_loop_graph_edges.md` — full edge dump
- IHQ-01 inventory (prior step) — pattern locations
