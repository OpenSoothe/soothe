# Sloop LangGraph Topology Redesign

**Status:** Draft
**Date:** 2026-08-18
**Topic:** Generalized node lifecycle + phase-subgraph topology for the Strange Loop graph

## 1. Motivation & Problem Statement

The current sloop graph is a flat `StateGraph` with **14 nodes** and **11 conditional-edge
routers** (`route_after_preprocess`, `route_after_wired_subagent`, `route_after_iteration_gate`,
`route_after_evidence_gather`, `route_after_evaluate`, `route_after_plan`,
`route_after_resolve_decision`, `route_after_validate_evidence`, `route_after_execute`,
`route_after_record_iteration`, `route_after_clarification`). The primary pain is **velocity and
routing complexity**: adding or modifying a node ripples through N routers, and each router
re-implements the same guard boilerplate.

### Concrete duplication observed in the codebase

| Duplication | Where | Lines |
|---|---|---|
| `_pending_clarification()` check | `route_after_execute`, `route_after_plan`, `route_after_evaluate`, `route_after_wired_subagent` | ~20 |
| `if X is None: emit fatal_error; return {"last_outcome":"fatal"}` guard | `generate_plan`, `commit_plan`, `validate_plan`, `record_progress`, `execute` | ~40 |
| `emit_plan_phase_status` bracketing | 6 nodes, ~12 call sites | ~12 |
| `resume_synth` special-case flag | set in `begin_iteration`, checked in `route_after_execute` | 2 sites |
| Manual `GraphPromptWrapper` wiring | 4 planner/synthesis nodes | 4 |
| Route-key bag of flags (`plan_route`, `assess_route`, `evidence_gather_route`, `after_record_route`, `resume_synth`, `planner_implement_handoff`) | 11 routers | — |

The `await_user` sidecar fans back into **4 nodes** (`execute`, `generate_plan`, `evaluate`, `delegate`)
via `route_after_clarification`, which reads `last_clarification_origin` to pick the resume target —
a manual re-implementation of LangGraph's native `interrupt()`/`Command(resume=...)`, which the
checkpointer already supports.

## 2. Scope

### In scope

- A generalized `LoopNode` lifecycle abstraction (pre / project / prompt / process / post).
- A typed `RouteDecision` return contract replacing the free-form route-key dict.
- A phase-subgraph topology: 4 phase subgraphs + residual sidecars.
- Native `interrupt()` for return-to-sender clarification origins, including the bounded executor
  interrupt-seam change that requires.

### Out of scope (with rationale)

| Item | Why out |
|---|---|
| Wire-stable deliverable phases (`goal_completion`, `execute_step`) and checkpoint ledger phases (`intent_classify`, `plan_assess`, ...) | `stations.normalize_station` + `LEGACY_TO_STATION` already decouple internal renames from the wire contract. Immutable per RFC-220 / soothe-sdk contract. |
| `GraphPromptWrapper` projection internals (slicing, capping, boundary markers) | Already centralized in commit `85c54753b`. The lifecycle adopts it as the default `prompt()`; we do not redesign projection. |
| Step-wave execution machinery (`_execute_step_collecting_events`, `_run_parallel_step`, act-wave aggregation in `executor.py`) | The real bulk of `executor.py` (2892 lines). Orthogonal to topology: the lifecycle treats `process()` as opaque. |
| `StrangeLoop.run` / `pump_graph` outer pump (`strange_loop.py`, 1217 lines) | Orthogonal; the graph-node layer sits below this pump. |
| Migration execution | This draft is the design only. |

### The one scope correction (called out)

The native-`interrupt()` decision touches the executor's existing manual interrupt plumbing
(`_fetch_pending_interrupts_from_state` + `ClarificationCapture` shunt in `strange_loop.py:599,669`).
This is a **bounded change to the interrupt seam** — one method and its call sites — not the
step-execution machinery. It is explicitly in scope; the rest of the executor/strange_loop core
remains out.

## 3. Design Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Motivation | Velocity / routing complexity |
| D2 | Breadth | Lifecycle + topology; process-core decomposition out |
| D3 | Compat | Wire + ledger phases immutable; internal nodes free to rename |
| D4 | Topology | Phase subgraphs + lifecycle nodes |
| D5 | Clarification | Native `interrupt()` for return-to-sender origins + residual sidecar for non-return origins |
| D6 | Interrupt seam | Replace executor's manual interrupt capture with native LangGraph `interrupt()`/`Command(resume)` for the 3 return-to-sender origins |

## 4. Node Lifecycle — the `LoopNode` Abstraction

The five stages named in the request become explicit template methods on a base class. The base
`__call__` driver runs them in fixed order and centralizes the guard boilerplate.

### 4.1 Base class

```python
class LoopNode(ABC):
    """Uniform lifecycle for every StrangeLoop graph node.

    Subclasses override the stages they need. The base __call__ runs:
        pre -> project -> prompt -> process -> post
    and centralizes fatal / pending-clarification / resume-skip / phase-status
    guards that are currently copy-pasted per node.
    """

    station: str

    # ── pre: guards & setup ──────────────────────────────────────────
    def pre(self, ctx: LoopRuntimeContext, state: dict) -> GuardOutcome | None:
        """Check prereqs, fatal-skip-on-resume, pending-clarification,
        emit phase status. Return GuardOutcome to short-circuit
        (fatal / deferred / skip). None = proceed.

        Default implementation applies the shared guards currently duplicated
        across nodes:
          - _pending_clarification(state) -> AwaitingClarification
          - missing-scratch guard -> FatalOutcome
          - emit_plan_phase_status(label)
        Nodes override to add specific guards (e.g. decision-not-None)."""

    # ── project: DAG projection ───────────────────────────────────────
    def project(self, ctx: LoopRuntimeContext, state: dict) -> ProjectionResult:
        """Project the CE ledger for this call kind. Defaults to
        GraphPromptWrapper.project_ledger(kind=self.call_kind).
        No-op (returns empty ProjectionResult) for non-planner nodes
        (validate_plan, execute, intake, commit_plan, check_limits)."""

    # ── prompt: message assembly ─────────────────────────────────────
    def prompt(
        self, ctx: LoopRuntimeContext, state: dict, proj: ProjectionResult
    ) -> list[BaseMessage]:
        """Assemble [SystemMessage, projected_ledger, HumanMessage].
        Defaults to GraphPromptWrapper.build_messages(kind=self.call_kind, ...).
        Non-LLM nodes return []."""

    # ── process: the actual work ──────────────────────────────────────
    async def process(
        self, ctx: LoopRuntimeContext, state: dict, messages: list[BaseMessage]
    ) -> NodeResult:
        """The one abstract method every node must implement. Calls
        ctx.strange_loop.<phase> or ctx.strange_loop.executor.
        Returns a typed NodeResult. May raise interrupt() for
        return-to-sender clarification origins."""

    # ── post: writes + emit + route ───────────────────────────────────
    def post(
        self, ctx: LoopRuntimeContext, state: dict, result: NodeResult
    ) -> RouteDecision:
        """Write scratch/state, ctx.emit(...) events, return a typed
        RouteDecision instead of a free-form route-key dict."""

    # ── driver ────────────────────────────────────────────────────────
    async def __call__(
        self, ctx: LoopRuntimeContext, state: dict
    ) -> dict:
        g = self.pre(ctx, state)
        if g is not None:
            return g.as_state_patch()
        proj = self.project(ctx, state)
        messages = self.prompt(ctx, state, proj)
        result = await self.process(ctx, state, messages)
        return self.post(ctx, state, result).as_state_patch()
```

### 4.2 Typed return contract

The current free-form route-key dict (`{"plan_route": ..., "assess_route": ...,
"evidence_gather_route": ..., "after_record_route": ..., "resume_synth": ...,
"planner_implement_handoff": ...}`) is replaced by a sum type. Nodes return a
`RouteDecision`; the phase subgraph's exit router pattern-matches on it.

```python
@dataclass
class RouteDecision:
    """Sum-type route return from LoopNode.post()."""
    kind: Literal[
        "proceed",      # continue within / to the next phase
        "await_user",   # route to residual await_user sidecar (non-return origin)
        "deferred",     # clarification deferred -> END
        "fatal",        # unrecoverable -> END
        "terminal",     # goal done -> complete / END
    ]
    next_phase: str | None = None      # for "proceed": target phase or internal node
    clarification_origin: str | None = None  # for "await_user": the non-return origin
    state_patch: dict = field(default_factory=dict)  # scratch/state writes + emit side effects
```

This collapses `resume_synth`, `after_record_route`, `planner_implement_handoff`, and the three
`*_route` flags into one typed value. The bag-of-flags problem is solved structurally: you cannot
set a flag that the router doesn't know about.

### 4.3 Node-to-subclass mapping

Each current node becomes a subclass overriding only the stages it needs:

| Node | pre | project | prompt | process | post |
|---|---|---|---|---|---|
| `IntakeNode` | resume-skip (`_should_skip_intent_classify`) | — | — | `classifier.classify_intake` | emit reasoning |
| `GatherEvidenceNode` | — | — | — | fresh-loop/keep detection | `RouteDecision(proceed, next_phase=...)` |
| `EvaluateNode` | status | planner | wrapper | `node_plan_assess` + gap | route |
| `GeneratePlanNode` | status + handoff-hydrate | planner | wrapper | `plan_phase.generate_*` | emit plan |
| `CommitPlanNode` | decision-guard | — | — | `_resolve_decision` + DAG normalize | emit plan_decision |
| `ValidatePlanNode` | decision-guard | — | — | `validate_plan_evidence` | fatal/route |
| `ExecuteNode` | answer-consume | — | — | `executor` (opaque) + native `interrupt()` | step results |
| `RecordProgressNode` | plan-guard | — | — | persist + anchor + emit | route |
| `CheckLimitsNode` | — | — | — | budget/rate-limit check | terminal/route |
| `BeginIterationNode` | — | — | — | scratch reset + anchor | route |
| `FinalizeNode` | status | synthesis | wrapper | `SynthesisGenerator` | emit completed |

**Non-LLM nodes** (`validate_plan`, `commit_plan`, `check_limits`, `begin_iteration`,
`record_progress`, `gather_evidence`) inherit the default no-op `project()`/`prompt()` and
override only `pre`/`process`/`post`. The lifecycle is uniform even when stages are empty —
predictability without forcing every node through an LLM-shaped pipe.

### 4.4 What the lifecycle collapses

| Current duplication | Collapsed into |
|---|---|
| `_pending_clarification()` in 4 routers | `pre()` default guard |
| Per-node fatal-guard boilerplate (5 nodes) | `pre()` default guard |
| `emit_plan_phase_status` bracketing (6 nodes) | `pre()`/`post()` defaults |
| `resume_synth` set+check across 2 nodes | `pre()` resume-skip + `RouteDecision` |
| Manual `GraphPromptWrapper` wiring (4 nodes) | `prompt()` default |
| Route-key bag of 6 flags | `RouteDecision` sum type |

## 5. Topology — Phase Subgraphs

The outer graph shrinks from 14 nodes / 11 routers to ~7 outer nodes / 1 router per phase exit.

### 5.1 Outer graph

```
        START
          │
          ▼
    ┌───────────┐     next_phase      ┌──────────┐
    │ preprocess │───────────────────▶│   plan   │
    └─────┬─────┘                     └────┬─────┘
          │ delegate (sidecar)             │ next_phase
          ▼                                ▼
    ┌──────────┐     next_phase      ┌───────────┐     next_phase   ┌──────────┐
    │ delegate  │◀── (planner_review)│  execute  │─────────────────▶│ complete │──▶END
    └────┬─────┘                     └────┬─────┘                  └──────────┘
         │ await_user (residual)          │ await_user (residual)
         ▼                                ▼
       END                              END
```

### 5.2 Phase subgraphs

Each phase owns its internal routing and returns a single `next_phase` exit channel:

- **`preprocess` subgraph**: `IntakeNode -> EnterLoopNode`; exit router returns
  `{plan, delegate, end}` (replaces `route_after_preprocess`'s 4 targets).
- **`plan` subgraph**: `GatherEvidenceNode -> EvaluateNode -> GeneratePlanNode`; internal routing
  for fresh-skip, structural-keep, assess-route; exit returns `{execute, complete, await_user}`.
- **`execute` subgraph**: `CheckLimitsNode -> BeginIterationNode -> CommitPlanNode ->
  ValidatePlanNode -> ExecuteNode -> RecordProgressNode`; owns the iteration loop
  (`RecordProgressNode -> CheckLimitsNode`); exit returns `{plan, complete, await_user, end}`.
- **`complete` subgraph**: `FinalizeNode`; exit = `END`.

### 5.3 Routing simplification

The 11 `route_after_*` functions collapse to **4 phase-exit routers** (one per phase) plus
internal subgraph routers. Cross-phase fan-out is bounded by phase boundaries. LangGraph subgraphs
compose with the parent checkpointer natively, so `interrupt()` persistence and resume still work
across `ainvoke` calls.

## 6. Clarification — Native Interrupt + Residual Sidecar

Two categories, split by whether the resume target is the *same node* that asked.

### 6.1 Native `interrupt()` (return-to-sender, 3 origins)

`ExecuteNode`, `GeneratePlanNode`, `EvaluateNode` call `interrupt(request)` mid-`process`.
LangGraph re-enters that exact node on `Command(resume=answers)`. This deletes:

- 6 of the 9 `await_user` edges (3 in-edges from these nodes to `await_user`, and 3
  out-edges from `await_user` back to these nodes); the residual sidecar keeps 3 edges
  (the `delegate` round-trip for `planner_subagent_review` and the `__end__` defer edge)
- The `route_after_clarification` origin-map logic for these origins
- The `last_clarification_origin` tracking for these origins
- The `pending_clarification` channel writes/reads for these origins

No `pending_clarification` state, no origin map, no resume-node resolution — LangGraph does it.

### 6.2 Residual `await_user` sidecar (non-return, 2 origins)

- `planner_subagent_review` -> resumes to `delegate` (a different node)
- `rail_pause` -> host-only, not a StrangeLoop interrupt

These keep the manual channel: the originating node sets the clarification request and returns
`RouteDecision(kind="await_user", clarification_origin="planner_subagent_review")`; the outer
graph routes to the `await_user` sidecar; on answer, the sidecar routes to the fixed resume node
(`delegate` for planner review). `ClarificationPolicy.deferred` -> `END` is still expressed here.

### 6.3 The executor interrupt seam (in scope, bounded)

The native-interrupt change requires replacing the executor's existing manual interrupt capture.
Today, `_core_agent_astream_with_interrupt_resume` (`strange_loop.py:669`) runs the CoreAgent
stream and, after it ends, calls `_fetch_pending_interrupts_from_state` (`:599`) to read pending
LangGraph interrupts from graph state and shunt `ask_user` interrupts to `ClarificationCapture`,
which sets `pending_clarification` for the manual sidecar.

Under the new design, for the 3 return-to-sender origins:

- `ExecuteNode.process()` calls `interrupt(request)` directly; the CoreAgent stream pauses at
  that node; `Command(resume=answers)` re-enters `ExecuteNode`.
- The `_fetch_pending_interrupts_from_state` + `ClarificationCapture` shunt is removed for
  `ask_user` interrupts from these 3 origins.
- `ClarificationCapture` is retained only for the 2 non-return origins (or moved entirely into the
  residual sidecar).

**Boundary of the change:** `_fetch_pending_interrupts_from_state`, `_core_agent_astream_with_interrupt_resume`,
and the call sites in `StrangeLoop.run` that wire `clarification_detector`/`clarification_capture`.
The step-wave execution machinery (`_execute_step_collecting_events`, `_run_parallel_step`,
act-wave aggregation) is **untouched** — `interrupt()` is called from the node wrapper, not the
executor internals.

## 7. Data Flow

```
user goal
   │
   ▼
LoopRuntimeContext (shared handles: strange_loop, state_manager, ce, emit, scratch)
   │
   ▼
build_strange_loop_graph() -> outer StateGraph(preprocess, plan, execute, complete, delegate, await_user)
   │
   ▼
each phase subgraph is a compiled StateGraph of LoopNode subclasses
   │
   ▼
LoopNode.__call__: pre -> project -> prompt -> process -> post -> RouteDecision
   │
   ▼
phase-exit router pattern-matches RouteDecision.kind -> next_phase or END
```

`LoopRuntimeContext` and `LoopPhaseScratch` are unchanged — they are the mutable handles the
lifecycle reads/writes. The lifecycle does not introduce new shared state; it formalizes access
to the existing state.

## 8. Error Handling

- **Fatal guards**: `pre()` default checks missing-scratch/decision prereqs and returns
  `GuardOutcome(kind="fatal")`. The `__call__` driver converts this to the state patch that ends
  the graph. Per-node fatal copies are deleted.
- **Clarification deferral**: `ClarificationPolicy` raising `ClarificationDeferredError` in the
  residual sidecar returns `RouteDecision(kind="deferred")` -> END, matching today's behavior.
- **Rate-limit / max-iterations**: `CheckLimitsNode.process()` returns
  `RouteDecision(kind="terminal")` for budget exhaustion, matching `emit_max_iterations_terminal`.
- **Interrupt errors**: native `interrupt()` failures bubble through LangGraph's standard
  error path; the `GraphRecursionError` handling in the executor is unchanged.

## 9. Testing

- **Lifecycle base**: unit-test `pre`/`project`/`prompt`/`process`/`post` in isolation per node.
  The base driver is tested once; subclasses test their stage overrides.
- **Phase subgraphs**: each subgraph is a compiled `StateGraph` — testable independently with a
  fixture `LoopRuntimeContext`, without the full outer graph.
- **Routing**: phase-exit routers pattern-match on `RouteDecision` — testable as pure functions
  over typed inputs, no graph runtime needed.
- **Clarification**: native `interrupt()` resume tested via `Command(resume=...)` on a
  checkpointer-backed subgraph; residual sidecar tested via the existing clarification-policy
  fixtures.
- **Compat**: `normalize_station` + `LEGACY_TO_STATION` tests remain the guardrail for wire/ledger
  phase stability. No new wire phases are introduced.

## 10. Migration Shape (feasibility, not the plan)

Per the compat constraint (D3), wire-stable phases stay; only internal station names and graph
structure change. The migration is **one phase at a time**:

1. Introduce `LoopNode` base + `RouteDecision`. Each existing `node_xxx` function can be wrapped
   in a `LoopNode` subclass behind the same `node_xxx` entry point during transition — no graph
   change yet.
2. Build the `preprocess` subgraph, swap it into the outer graph, run tests. `route_after_preprocess`
   becomes the phase-exit router.
3. Repeat for `plan`, `execute`, `complete`.
4. Replace the executor interrupt seam (`_fetch_pending_interrupts_from_state` +
   `ClarificationCapture` shunt) with native `interrupt()` for the 3 return-to-sender origins.
5. Collapse the residual `await_user` sidecar to the 2 non-return origins.

Each step is independently shippable. `stations.normalize_station` + `LEGACY_TO_STATION` are the
compatibility guardrail throughout.

## 11. Alternatives Considered

- **Option 2: Single-dispatch spine.** One `dispatch` node reads a `next_station` channel nodes
  set; 11 routers collapse to 1. Simplest topology to draw, but `dispatch` becomes a god-router
  holding all branch logic in one function. Traded fan-out sprawl for centralization. Rejected:
  centralizes at the cost of locality.
- **Option 3: Linear spine + skip-forward.** Single chain, nodes short-circuit via flags. Fewest
  edges, but branching becomes implicit (state flags) not explicit (graph edges) — loses the
  debuggability that the current flat graph provides. Rejected for a system of this size.
- **C-rev-1: Keep executor's manual interrupt model, drop native interrupt().** Would stay truly
  out of the process core, but the manual `await_user` channel + origin map survive for all 5
  origins — losing the main simplification (6 edges deleted) that motivated choosing native
  interrupt. Rejected in favor of C-rev-2.

## 12. Open Questions

None blocking. The draft is internally consistent and all four load-bearing decisions (D1-D6) are
resolved. Implementation-time questions (e.g. exact `RouteDecision` field set, whether
`ClarificationCapture` moves fully into the sidecar) are deferred to the implementation guide.
