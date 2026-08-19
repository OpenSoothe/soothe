# RFC-903: Sloop Graph Topology and Node Lifecycle

**RFC**: 903
**Title**: Sloop Graph Topology and Node Lifecycle
**Status**: Proposed
**Kind**: Architecture Design
**Created**: 2026-08-18
**Authors**: Soothe Team
**Updated**: 2026-08-18
**Dependencies**: RFC-220, RFC-604, RFC-622, RFC-633, RFC-803
**Revises**: RFC-220 §Loop Graph Topology, §State and Schemas (node contract)
**Related**: RFC-201, RFC-207, RFC-214, RFC-218, RFC-219, RFC-904
**Further revised by**: RFC-904 (recursive decomposition further shrinks stations; keeps `LoopNode` / `RouteDecision`)

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
3. **Wire stability** — Wire-stable deliverable phases and checkpoint ledger
   phases remain immutable; `clarification.origins` owns the legacy origin →
   canonical resume-station mapping, decoupling internal renames from the
   wire contract.

---

## Supersedes and Obsolete Surface

When RFC-903 is **Accepted**:

- RFC-220 remains **Implemented** for its identity/isolation rules, persistence
  strategy, and two-graphs-two-keys invariant. Its §Loop Graph Topology (flat
  14-node graph) and §State and Schemas (implicit node contract) are
  **partially superseded** by this RFC.
- The `validate_plan` and `begin_iteration` nodes are **folded** into
  `commit_plan` and `check_limits` respectively. They are no longer graph
  nodes; their station constants are removed and persisted checkpoints resume
  at the folding station.
- The `route_after_resolve_decision` and `route_after_validate_evidence`
  routers are replaced by a single `route_after_commit` router.
- The route-key bag of flags (`plan_route`, `assess_route`,
  `evidence_gather_route`, `after_record_route`, `resume_synth`,
  `planner_implement_handoff`) is replaced by the typed `RouteDecision` sum
  type as nodes migrate to `LoopNode`.

RFC-220's header **should** carry `Partially Superseded by: RFC-903 (node
lifecycle, node folds, typed route contract)` once RFC-903 reaches Accepted.

> **Follow-on (RFC-904):** Recursive step decomposition further shrinks the
> compiled graph (DISPATCH / RECONCILE / ROOT_EVAL) while retaining this RFC's
> `LoopNode` lifecycle and typed `RouteDecision`. See RFC-904.

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

**12 nodes, 8 conditional routers.**

---

## State and Schemas

### `LoopGraphState` changes (post-folds)

| Channel | Change |
|---|---|
| `resume_synth` | Retained (clear moved into `CheckLimitsNode.post()`) |
| `after_record_route` | Retained (not yet replaced by `RouteDecision`) |
| `plan_route`, `assess_route`, `evidence_gather_route` | Retained (not yet replaced by `RouteDecision`) |

Full `RouteDecision` replacement of these channels is a future phase as more
nodes migrate to `LoopNode`.

### `LoopRuntimeContext` and `LoopPhaseScratch`

Unchanged.

### `clarification.origins.CLARIFICATION_ORIGIN_RESUME_NODE`

Normative. Maps persisted legacy clarification origins to their canonical
resume station. Legacy planning origins (`plan_generate`, `plan_assess`,
`plan_gap_analysis`, `assess`, `analyze_gaps`) resume into the unified
`evaluate` station (or `generate_plan` for `plan_generate`). The mapping
replaces the former `stations.LEGACY_TO_STATION` / `normalize_station`
indirection — the legacy dict was reachable only through this single consumer,
so it is consolidated here.

---

## Persistence Strategy

The Loop Graph checkpoint key remains `{loop_id}__strange_loop` (unchanged from
RFC-220). The node folds move checkpoint cursors (a goal interrupted at the old
`validate_plan` station now resumes at `commit_plan`), but
`CLARIFICATION_ORIGIN_RESUME_NODE` maps the legacy origin, so resume is
compatible. No checkpoint key versioning is needed.

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
- **Compat**: `CLARIFICATION_ORIGIN_RESUME_NODE` maps the 5 persisted legacy
  clarification origins to their canonical resume station.
- **Isolation**: the RFC-220 isolation tests (Loop Graph `thread_id` ≠ CoreAgent
  `thread_id`) remain unchanged.

---

## Non-Goals

- Replacing the `Executor` step-wave execution machinery.
- Replacing the `StrangeLoop.run` / `pump_graph` outer pump.
- Redesigning `GraphPromptWrapper` projection internals.
- Renaming wire-stable deliverable phases or checkpoint ledger phases.
- Migrating `execute`/`finalize` to `LoopNode` (deferred — these 500–660-line
  nodes are too complex for the 5-method split to cleanly partition).

---

## Implementation Sequence

1. **P1 (done):** Introduce `LoopNode` base + `RouteDecision` + `GuardOutcome` +
   `wrap_node` adapter (non-breaking).
2. **P2 (done):** Migrate `begin_iteration`, `check_limits`, `validate_plan`,
   `commit_plan` to `LoopNode` subclasses.
3. **P3 (done):** Fold `validate_plan` into `CommitPlanNode.process()` and
   `begin_iteration` into `CheckLimitsNode.process()`. Update builder, routers,
   and topology test.
4. Update RFC-220 header: `Partially Superseded by: RFC-903`.

---

## Summary

RFC-903 revises RFC-220's Loop Graph with a generalized 5-method `LoopNode`
lifecycle, a typed `RouteDecision` contract, and two node folds
(`validate_plan` → `commit_plan`, `begin_iteration` → `check_limits`), reducing
topology from 14→12 nodes and 11→8 routers. The flat graph is retained.
Wire-stable phases and the two-graphs-two-keys invariant are preserved.
