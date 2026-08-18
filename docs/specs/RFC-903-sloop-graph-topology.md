# RFC-903: Sloop Graph Topology and Node Lifecycle

**RFC**: 903
**Title**: Sloop Graph Topology and Node Lifecycle
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-08-18
**Dependencies**: RFC-220, RFC-604, RFC-622, RFC-633, RFC-803
**Revises**: RFC-220 §Loop Graph Topology, §State and Schemas (node contract)
**Related**: RFC-201, RFC-207, RFC-214, RFC-218, RFC-219

---

## Abstract

RFC-220 normatively defines Layer 2 single-goal execution as a flat compiled
`StateGraph(LoopGraphState)` with 14 nodes and 11 conditional-edge routers. This
RFC revises that topology by:

1. Defining a **generalized node lifecycle** (`LoopNode` base class with five
   methods: `pre` / `project` / `prompt` / `process` / `post`) that makes the
   implicit node shape explicit, uniform, and testable, and centralizes the
   fatal / clarification-yield / resume-skip guards currently copy-pasted across
   nodes and routers.
2. Introducing a **typed `RouteDecision` sum type** replacing the free-form
   route-key dict.
3. **Folding** two serial validation/setup nodes into their siblings
   (`validate_plan` → `commit_plan`, `begin_iteration` → `check_limits`),
   reducing the graph from 14→12 nodes and 11→8 conditional routers.

**Revision note (2026-08-18, post-implementation):** The original draft proposed
a **phase-subgraph** restructure (4 compiled subgraphs + residual sidecars).
Implementation revealed that 6 of 8 routers fan across phase boundaries, so
LangGraph subgraphs — which can only route internally — don't compose cleanly
with the cross-phase routing. The phase-subgraph approach is **withdrawn**; the
flat graph with `LoopNode` lifecycle + node folds is the target topology. See
§13 for the full rationale.

---

## Motivation

1. **Routing complexity.** Adding or modifying a node in the flat graph ripples
   through multiple `route_after_*` functions; each router re-implements the
   same fatal and clarification guards. The 11-router / 14-node flat graph is
   hard to reason about, extend, or debug.
2. **Node inconsistency.** Nodes are ad-hoc: some emit phase status, some guard
   fatal, some use `GraphPromptWrapper`, some do not. The implicit
   `async def(ctx, state) -> dict` shape yields unpredictable behavior and
   untestable lifecycle stages.
3. **Serial validation chokepoints.** `validate_plan` is a single deterministic
   check sandwiched between two fatal-guard routers; `begin_iteration` is pure
   setup. Both add nodes and edges without adding routing value.

---

## Guiding Principles

1. **Lifecycle uniformity** — Every node inherits one 5-method lifecycle; the
   base driver centralizes guards. Non-LLM nodes no-op the stages they do not
   need.
2. **Fold, don't restructure** — Collapse serial setup/validation nodes into
   their siblings rather than restructuring the graph topology. The flat graph
   is retained; the node count and router count drop.
3. **Native primitives over manual channels** — Use LangGraph `interrupt()` for
   return-to-sender clarification (P6, future); keep a manual channel only
   where the resume target is a different node.
4. **Wire stability** — Wire-stable deliverable phases and checkpoint ledger
   phases remain immutable; `stations.normalize_station` decouples internal
   renames from the wire contract.

---

## Supersedes and Obsolete Surface

When RFC-903 is **Implemented**:

- RFC-220 remains **Implemented** for its identity/isolation rules, persistence
  strategy, and two-graphs-two-keys invariant. Its §Loop Graph Topology (flat
  14-node graph) and §State and Schemas (implicit node contract) are
  **partially superseded** by this RFC.
- The `validate_plan` and `begin_iteration` nodes are **folded** into
  `commit_plan` and `check_limits` respectively. They are no longer graph
  nodes; their station constants are retained for `normalize_station` backward
  compat.
- The `route_after_resolve_decision` and `route_after_validate_evidence`
  routers are replaced by a single `route_after_commit` router.
- The route-key bag of flags (`plan_route`, `assess_route`,
  `evidence_gather_route`, `after_record_route`, `resume_synth`,
  `planner_implement_handoff`) is replaced by the typed `RouteDecision` sum
  type as nodes migrate to `LoopNode`.

RFC-220's header **should** carry `Partially Superseded by: RFC-903 (node
lifecycle, node folds, typed route contract)` once RFC-903 reaches Implemented.

---

## Generalized Node Lifecycle

### `LoopNode` base class

Every StrangeLoop graph node **should** inherit `LoopNode` and implement the
five-method lifecycle. The base `__call__` driver runs the stages in fixed order
and centralizes the guard boilerplate.

```python
class LoopNode(ABC):
    station: str
    call_kind: GraphCallKind | None = None

    async def pre(self, ctx, state) -> GuardOutcome | None: ...
    def project(self, ctx, state) -> ProjectionResult: ...
    def prompt(self, ctx, state, proj) -> list[BaseMessage]: ...
    async def process(self, ctx, state, messages) -> NodeResult: ...
    def post(self, ctx, state, result) -> RouteDecision: ...

    async def __call__(self, ctx, state) -> dict:
        guard = await self.pre(ctx, state)
        if guard is not None:
            return guard.as_state_patch()
        proj = self.project(ctx, state)
        messages = self.prompt(ctx, state, proj)
        result = await self.process(ctx, state, messages)
        for event_type, payload in result.events:
            await ctx.emit(event_type, payload)
        decision = self.post(ctx, state, result)
        return decision.as_state_patch()
```

### Why five methods

A 3-method `precheck`/`run`/`postrun` lumps projection, prompt assembly, and
core work into `run`. Separating them: (a) non-LLM nodes no-op `project`/`prompt`
cleanly; (b) `GraphPromptWrapper` becomes the default `prompt()`; (c) projection
is independently testable; (d) `process()` stays opaque to the topology.

### Typed return contract

`RouteDecision` replaces the free-form route-key dict:

```python
@dataclass
class RouteDecision:
    kind: Literal["proceed", "await_user", "deferred", "fatal", "terminal"]
    next_phase: str | None = None
    clarification_origin: str | None = None
    state_patch: dict = field(default_factory=dict)
```

### `GuardOutcome`

```python
@dataclass
class GuardOutcome:
    kind: Literal["fatal", "deferred", "skip"]
    state_patch: dict = field(default_factory=dict)
```

The per-node `emit fatal_error + return {"last_outcome":"fatal"}` boilerplate
folds into `pre()`.

### `wrap_node` adapter

The graph builder uses `wrap_node(station, node, ctx)` to detect `LoopNode`
instances vs legacy `async def(ctx, state) -> dict` functions, so the graph
adopts the new base incrementally.

---

## Node Folds

Two nodes are folded into their siblings, reducing topology from 14→12 nodes
and 11→8 conditional routers:

### Fold 1: `validate_plan` → `CommitPlanNode.process()`

`validate_plan` was a single deterministic check (`validate_plan_evidence`) +
fatal-guard, sandwiched between `route_after_resolve_decision` and
`route_after_validate_evidence`. The check now runs in `CommitPlanNode.process()`
after decision scoping. The two routers collapse into one `route_after_commit`
(`COMMIT_PLAN → {EXECUTE, END}`).

### Fold 2: `begin_iteration` → `CheckLimitsNode.process()`

`begin_iteration` was pure setup (scratch reset, start anchor capture,
`iteration_started` emit, `resume_synth` clear) with an unconditional edge to
`GATHER_EVIDENCE`. The setup now runs in `CheckLimitsNode.process()` on the
non-terminal branch. `route_after_iteration_gate` routes directly to
`GATHER_EVIDENCE` (was `BEGIN_ITERATION → GATHER_EVIDENCE`).

### Topology after folds

```
START → intake → enter_loop
  → [route_after_preprocess] → {gather_evidence, delegate, END}
  → [route_after_evidence_gather] → {evaluate, generate_plan, commit_plan}
  → [route_after_evaluate] → {finalize, commit_plan, generate_plan, await_user}
  → [route_after_plan] → {finalize, commit_plan, generate_plan, await_user}
  → commit_plan → [route_after_commit] → {execute, END}
  → execute → [route_after_execute] → {record_progress, await_user, check_limits, END}
  → record_progress → [route_after_record_iteration] → {check_limits, finalize, END}
  → check_limits → [route_after_iteration_gate] → {gather_evidence, END}
  → finalize → END
  sidecars: delegate, await_user
```

**12 nodes, 8 conditional routers, 6 unconditional edges.**

---

## Clarification Model (future — P6)

Clarification origins split by whether the resume target is the *same node*:

- **Return-to-sender (3 origins):** `execute`, `generate_plan`, `evaluate` —
  native LangGraph `interrupt()` / `Command(resume=...)` re-enters in-place.
  Requires touching the executor interrupt seam (`_fetch_pending_interrupts_from_state`
  + `ClarificationCapture` shunt in `strange_loop.py`).
- **Non-return (2 origins):** `planner_subagent_review` → `delegate`,
  `rail_pause` → host — keep the manual `await_user` sidecar channel.

This is **not implemented in P1–P3** and remains a future phase.

---

## State and Schemas

### `LoopGraphState` changes (post-folds)

| Channel | Change |
|---|---|
| `resume_synth` | Retained (P3 moved the clear into `CheckLimitsNode.post()`) |
| `after_record_route` | Retained (not yet replaced by `RouteDecision`) |
| `plan_route`, `assess_route`, `evidence_gather_route` | Retained (not yet replaced by `RouteDecision`) |

Full `RouteDecision` replacement of these channels is a future phase as more
nodes migrate to `LoopNode`.

### `LoopRuntimeContext` and `LoopPhaseScratch`

Unchanged.

### `stations.normalize_station`

Unchanged and normative. `BEGIN_ITERATION` and `VALIDATE_PLAN` constants are
retained for legacy ID mapping even though the nodes no longer exist as graph
nodes.

---

## Persistence Strategy

The Loop Graph checkpoint key remains `{loop_id}__strange_loop` (unchanged from
RFC-220). The node folds move checkpoint cursors (a goal interrupted at the old
`validate_plan` station now resumes at `commit_plan`), but `normalize_station`
maps the legacy station ID, so resume is compatible.

No checkpoint key versioning is needed for the fold-only topology change. If
the future clarification-model change (P6) introduces native `interrupt()`, the
key may version then.

---

## Streaming and Observability

Unchanged from RFC-220. The `LoopNode` base driver **may** auto-emit
`node_started` / `node_completed` events with timing, replacing per-node
`emit_plan_phase_status` calls (future).

---

## Testing Obligations

- **Lifecycle base**: unit-test `pre`/`project`/`prompt`/`process`/`post` in
  isolation per node.
- **Folds**: the `test_loop_graph_topology.py` test asserts the folded node set
  (no `begin_iteration`/`validate_plan` as graph nodes).
- **Compat**: `normalize_station` + `LEGACY_TO_STATION` tests remain the
  guardrail for wire/ledger phase stability.
- **Isolation**: the RFC-220 isolation tests (Loop Graph `thread_id` ≠ CoreAgent
  `thread_id`) remain unchanged.

---

## Non-Goals (this RFC)

- Phase-subgraph restructure (withdrawn — see §13).
- Replacing the `Executor` step-wave execution machinery.
- Replacing the `StrangeLoop.run` / `pump_graph` outer pump.
- Redesigning `GraphPromptWrapper` projection internals.
- Renaming wire-stable deliverable phases or checkpoint ledger phases.
- Native `interrupt()` for clarification (future P6).

---

## Implementation Sequence

1. **P1 (done):** Introduce `LoopNode` base + `RouteDecision` + `GuardOutcome` +
   `wrap_node` adapter (non-breaking).
2. **P2 (done):** Migrate `begin_iteration`, `check_limits`, `validate_plan`,
   `commit_plan` to `LoopNode` subclasses.
3. **P3 (done):** Fold `validate_plan` into `CommitPlanNode.process()` and
   `begin_iteration` into `CheckLimitsNode.process()`. Update builder, routers,
   and topology test.
4. **P6 (future):** Replace executor interrupt seam with native `interrupt()` for
   3 return-to-sender origins.
5. **P7 (future):** Collapse residual `await_user` sidecar to 2 non-return origins.
6. Update RFC-220 header: `Partially Superseded by: RFC-903`.

---

## Summary

RFC-903 revises RFC-220's Loop Graph with a generalized 5-method `LoopNode`
lifecycle, a typed `RouteDecision` contract, and two node folds
(`validate_plan` → `commit_plan`, `begin_iteration` → `check_limits`), reducing
topology from 14→12 nodes and 11→8 routers. The flat graph is retained.
Wire-stable phases and the two-graphs-two-keys invariant are preserved.

---

## 13. Withdrawn: Phase-Subgraph Topology

The original draft of this RFC (and the source design draft
`docs/drafts/2026-08-18-sloop-graph-topology-design.md`) proposed restructuring
the flat graph into 4 phase subgraphs (`preprocess`, `plan`, `execute`,
`complete`) plus residual sidecars, shrinking the outer graph to ~7 nodes.

**Implementation revealed this approach does not compose cleanly with
LangGraph's subgraph model.** LangGraph subgraphs (compiled `StateGraph` passed
to `parent.add_node(name, subgraph)`) can only route *internally* — a subgraph
node's output is a single state patch, and the parent graph does the
conditional routing on that output. Tracing the 8 routers revealed that **6 of
8 fan across phase boundaries**:

| Router | Targets | Crosses phases? |
|---|---|---|
| `route_after_preprocess` | plan, delegate, END | ✓ preprocess→plan/sidecar |
| `route_after_evidence_gather` | evaluate, generate_plan, commit_plan | ✓ plan→execute |
| `route_after_evaluate` | finalize, commit_plan, generate_plan, await_user | ✓ plan→complete/execute/sidecar |
| `route_after_plan` | finalize, commit_plan, generate_plan, await_user | ✓ plan→complete/execute/sidecar |
| `route_after_commit` | execute, END | ✗ intra-execute |
| `route_after_execute` | record_progress, await_user, check_limits, END | ✗ intra-execute + sidecar |
| `route_after_record_iteration` | check_limits, finalize, END | ✓ execute→complete |

Only `route_after_commit` and `route_after_execute` are intra-phase. The rest
cross boundaries, so they cannot live inside a subgraph — they must live in the
parent graph. Putting the nodes in subgraphs while keeping the routing in the
parent yields thin wrappers that add checkpoint complexity without simplifying
the routing.

The flat graph with `LoopNode` lifecycle + node folds delivers the real
simplification (centralized guards, typed route contract, fewer nodes/routers)
without fighting LangGraph's subgraph model. The phase-subgraph approach is
withdrawn.
