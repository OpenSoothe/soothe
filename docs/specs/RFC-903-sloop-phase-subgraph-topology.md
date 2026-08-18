# RFC-903: Sloop Phase-Subgraph Topology and Node Lifecycle

**RFC**: 903
**Title**: Sloop Phase-Subgraph Topology and Node Lifecycle
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
RFC revises that topology into a **phase-subgraph** structure — 4 phase
subgraphs (`preprocess`, `plan`, `execute`, `complete`) plus residual sidecars
(`delegate`, `await_user`) — shrinking the outer graph to ~7 nodes and bounding
cross-phase fan-out by phase boundaries.

It also normatively defines a **generalized node lifecycle** (`LoopNode` base
class with five methods: `pre` / `project` / `prompt` / `process` / `post`) that
makes the implicit node shape RFC-220 describes explicit, uniform, and testable,
and centralizes the fatal / clarification-yield / resume-skip / phase-status
guards currently copy-pasted across 14 nodes and 11 routers.

Finally, it normatively replaces the manual clarification sidecar round-trip
(RFC-622 `pending_clarification` channel + origin map) with **native LangGraph
`interrupt()`** for return-to-sender origins, retaining a residual sidecar only
for non-return origins.

**Scope:** This RFC specifies the target topology, node contract, and
clarification model. It does **not** specify the step-wave execution machinery
(`Executor` internals) or the `StrangeLoop.run` outer pump; those remain under
RFC-220 / RFC-201. The implementation guide `IG-sloop-generalized-node-topology.md`
carries the phased migration plan.

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
3. **Manual clarification reinvention.** The `await_user` sidecar manually
   tracks `last_clarification_origin` and maps it back to a resume node — a
   re-implementation of LangGraph's native `interrupt()` / `Command(resume=...)`,
   which the checkpointer already supports (RFC-220 §Persistence Strategy).

---

## Guiding Principles

1. **Phased isolation** — Each phase subgraph owns its internal routing and
   returns a single exit channel; cross-phase fan-out is bounded by phase
   boundaries.
2. **Lifecycle uniformity** — Every node inherits one 5-method lifecycle; the
   base driver centralizes guards. Non-LLM nodes no-op the stages they do not
   need.
3. **Native primitives over manual channels** — Use LangGraph `interrupt()` for
   return-to-sender clarification; keep a manual channel only where the resume
   target is a different node.
4. **Wire stability** — Wire-stable deliverable phases and checkpoint ledger
   phases (RFC-220 §Normative Identity) remain immutable; `stations.normalize_station`
   decouples internal renames from the wire contract.

---

## Supersedes and Obsolete Surface

When RFC-903 is **Implemented**:

- RFC-220 remains **Implemented** for its identity/isolation rules, persistence
  strategy, and two-graphs-two-keys invariant. Its §Loop Graph Topology
  (flat 14-node graph) and §State and Schemas (implicit node contract) are
  **partially superseded** by this RFC.
- The flat `StateGraph(LoopGraphState)` topology is replaced by the phase-subgraph
  outer graph. The 11 `route_after_*` functions are replaced by 4 phase-exit
  routers + internal subgraph routers.
- The `pending_clarification` channel and `route_after_clarification` origin map
  are removed for the 3 return-to-sender origins (RFC-622); the residual sidecar
  retains them for 2 non-return origins.
- The route-key bag of flags (`plan_route`, `assess_route`, `evidence_gather_route`,
  `after_record_route`, `resume_synth`, `planner_implement_handoff`) is replaced
  by the typed `RouteDecision` sum type.
- Code paths that assume a flat graph or the manual clarification channel for
  return-to-sender origins are **deleted**, not deprecated.

RFC-220's header **must** carry `Partially Superseded by: RFC-903 (topology,
node contract, clarification model)` once RFC-903 reaches Implemented.

---

## Architecture Position

```
Layer 3 (RFC-200) → delegates single goal to Layer 2
Layer 2 (this RFC + RFC-220) → outer StateGraph of phase subgraphs, keyed by loop_id
    ├── preprocess subgraph → plan subgraph → execute subgraph → complete subgraph
    ├── delegate (sidecar)         ← planner_subagent_review origin
    ├── await_user (residual)     ← planner_subagent_review + rail_pause origins
    └── execute subgraph → invokes CoreAgent with thread_id (unchanged)
Layer 1 (RFC-100) → tools / subagents
```

The two-graphs-two-keys invariant (RFC-220 §Normative Identity) is **unchanged**:
the Loop Graph checkpoint key remains `loop_id`; the CoreAgent key remains
`thread_id`.

---

## Generalized Node Lifecycle

### `LoopNode` base class

Every StrangeLoop graph node **must** inherit `LoopNode` and implement the
five-method lifecycle. The base `__call__` driver runs the stages in fixed order
and centralizes the guard boilerplate currently duplicated across nodes.

```python
class LoopNode(ABC):
    station: str
    call_kind: GraphCallKind | None = None  # None for non-LLM nodes

    def pre(self, ctx, state) -> GuardOutcome | None: ...
    def project(self, ctx, state) -> ProjectionResult: ...
    def prompt(self, ctx, state, proj) -> list[BaseMessage]: ...
    async def process(self, ctx, state, messages) -> NodeResult: ...
    def post(self, ctx, state, result) -> RouteDecision: ...

    async def __call__(self, ctx, state) -> dict:
        g = self.pre(ctx, state)
        if g is not None:
            return g.as_state_patch()
        proj = self.project(ctx, state)
        messages = self.prompt(ctx, state, proj)
        result = await self.process(ctx, state, messages)
        return self.post(ctx, state, result).as_state_patch()
```

### Lifecycle stages

| Stage | Responsibility | Default | Nodes that override |
|---|---|---|---|
| `pre` | Guards (fatal, resume-skip, pending-clarification), phase status emit | shared guard logic | nodes with specific prereqs |
| `project` | CE ledger projection (DAG projection) | `GraphPromptWrapper.project_ledger` | non-planner nodes no-op |
| `prompt` | Message assembly `[System, projected_ledger, Human]` | `GraphPromptWrapper.build_messages` | non-LLM nodes return `[]` |
| `process` | Core work (LLM, CoreAgent dispatch, transform) | abstract — every node | all nodes |
| `post` | Scratch/state writes, event emit, route decision | typed `RouteDecision` | nodes with specific emits |

### Why five methods, not three

A 3-method `precheck`/`run`/`postrun` lumps projection, prompt assembly, and
core work into `run`. Separating them: (a) non-LLM nodes no-op `project`/`prompt`
cleanly; (b) `GraphPromptWrapper` becomes the default `prompt()` rather than
hand-wired per node; (c) projection is independently testable as a pure
function; (d) `process()` stays opaque to the topology, keeping the
`Executor`/`StrangeLoop` process core fenced.

### Typed return contract

Nodes return a **`RouteDecision` sum type**, not a free-form route-key dict:

```python
@dataclass
class RouteDecision:
    kind: Literal["proceed", "await_user", "deferred", "fatal", "terminal"]
    next_phase: str | None = None
    clarification_origin: str | None = None
    state_patch: dict = field(default_factory=dict)
```

The route-key bag of flags (`plan_route`, `assess_route`, `evidence_gather_route`,
`after_record_route`, `resume_synth`, `planner_implement_handoff`) is **removed**.
Routers pattern-match on `RouteDecision.kind`.

### `GuardOutcome`

```python
@dataclass
class GuardOutcome:
    kind: Literal["fatal", "deferred", "skip"]
    state_patch: dict = field(default_factory=dict)
```

The per-node `emit fatal_error + return {"last_outcome": "fatal"}` boilerplate
(5+ nodes) and the 4-router `_pending_clarification` check are folded into the
`pre()` default.

---

## Phase-Subgraph Topology

### Outer graph

The outer graph **must** consist of ~7 nodes: 4 phase subgraphs (`preprocess`,
`plan`, `execute`, `complete`) plus 2 sidecars (`delegate`, `await_user`) plus
entry.

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

### Phase subgraphs

| Subgraph | Internal nodes | Exit channel |
|---|---|---|
| `preprocess` | `IntakeNode → EnterLoopNode` | `{plan, delegate, end}` |
| `plan` | `GatherEvidenceNode → EvaluateNode → GeneratePlanNode` | `{execute, complete, await_user}` |
| `execute` | `CheckLimitsNode → CommitPlanNode → ExecuteNode → RecordProgressNode` (iteration loop) | `{plan, complete, await_user, end}` |
| `complete` | `FinalizeNode` | `END` |

### Internal folds

Two nodes from RFC-220's flat topology are **folded** into the execute
subgraph's internal nodes (not separate outer nodes):

| Fold | Into | Rationale |
|---|---|---|
| `validate_evidence_bindings` | `CommitPlanNode.post()` | Deterministic check + fatal-guard; belongs in `post()` |
| `iteration_start` | `CheckLimitsNode.process()` | Pure setup (scratch reset, anchor capture); non-terminal branch |

### Routing simplification

The 11 `route_after_*` functions collapse to **4 phase-exit routers** (one per
phase) plus internal subgraph routers. Cross-phase fan-out is bounded by phase
boundaries. No router contains an inlined `if last_outcome == "fatal"` or
`_pending_clarification` check — all guards live in `LoopNode.pre()`.

LangGraph subgraphs compose with the parent checkpointer natively, so
`interrupt()` persistence and resume still work across `ainvoke` calls.

---

## Clarification Model

### Two categories

Clarification origins (RFC-622, RFC-633) split by whether the resume target is
the **same node** that asked:

**Native `interrupt()` (return-to-sender, 3 origins):**
`ExecuteNode`, `GeneratePlanNode`, `EvaluateNode` call `interrupt(request)`
mid-`process`. LangGraph re-enters that exact node on `Command(resume=answers)`.

This removes:
- 6 of the 9 `await_user` edges (3 in + 3 out for these origins)
- The `route_after_clarification` origin-map logic for these origins
- The `last_clarification_origin` tracking for these origins
- The `pending_clarification` channel writes/reads for these origins

**Residual `await_user` sidecar (non-return, 2 origins):**
- `planner_subagent_review` → resumes to `delegate` (a different node)
- `rail_pause` → host-only, not a StrangeLoop interrupt

These keep the manual channel: the originating node returns
`RouteDecision(kind="await_user", clarification_origin=...)`; the outer graph
routes to the `await_user` sidecar; on answer, the sidecar routes to the fixed
resume node. `ClarificationPolicy.deferred` → `RouteDecision(kind="deferred")` → `END`.

### Executor interrupt seam

The native-interrupt change replaces the executor's existing manual interrupt
capture: `_core_agent_astream_with_interrupt_resume` and
`_fetch_pending_interrupts_from_state` (`strange_loop.py`) are modified so
`ask_user` interrupts from the 3 return-to-sender origins surface via native
`interrupt()` rather than `ClarificationCapture` → `pending_clarification`.

**Boundary:** the change touches `_fetch_pending_interrupts_from_state`,
`_core_agent_astream_with_interrupt_resume`, and their call sites in
`StrangeLoop.run`. The step-wave execution machinery (`_execute_step_collecting_events`,
`_run_parallel_step`, act-wave aggregation) is **unchanged** — `interrupt()` is
called from the node wrapper, not the executor internals.

### `resume_synth` elimination

The `resume_synth` channel (RFC-220 workaround for scratch-state inconsistency
on the clarification-resume path) is **removed**. Under native `interrupt()`,
`ExecuteNode` re-enters with the answer, `process()` populates scratch normally,
and `record_progress` runs without special-casing. No spike is needed — the
native-interrupt path makes the channel structurally unnecessary.

---

## State and Schemas

### `LoopGraphState` changes

| Channel | Change |
|---|---|
| `pending_clarification` | Removed for 3 return-to-sender origins; retained for 2 non-return origins |
| `pending_clarification_answer` | Removed for 3 return-to-sender origins; retained for 2 non-return origins |
| `last_clarification_origin` | Removed for 3 return-to-sender origins |
| `resume_synth` | Removed entirely |
| `after_record_route` | Removed (replaced by `RouteDecision.kind == "terminal"`) |
| `planner_implement_handoff` | Removed (replaced by `RouteDecision` within `delegate`) |
| `plan_route`, `assess_route`, `evidence_gather_route` | Removed (replaced by `RouteDecision`) |

### `LoopRuntimeContext` and `LoopPhaseScratch`

Unchanged. They are the mutable handles the lifecycle reads/writes. The lifecycle
introduces no new shared state; it formalizes access to existing state.

### `stations.normalize_station`

Unchanged and normative. It is the compatibility guardrail: internal station
renames and graph restructuring do not leak to the wire contract. Wire-stable
deliverable phases (`goal_completion`, `execute_step`) and checkpoint ledger
phases (`intent_classify`, `plan_assess`, `plan_generate`, `plan_gap_analysis`)
remain immutable.

---

## Persistence Strategy

The Loop Graph checkpoint key **must** version from `{loop_id}__strange_loop`
to `{loop_id}__strange_loop_v2` at subgraph introduction time. In-flight goals
on the v1 key resume on v1 (or a migration shim maps v1 cursors to v2
phase-entry points).

LangGraph subgraphs compose with the parent checkpointer natively, so
`interrupt()` persistence and resume work across `ainvoke` calls within the v2
graph. The two-graphs-two-keys invariant (RFC-220) is unchanged.

---

## Streaming and Observability

The runner continues to consume `compiled.astream` from the outer graph and
maps stream chunks to existing progress contracts (RFC-614). The `LoopNode`
base driver **may** auto-emit `node_started` / `node_completed` events with
timing, replacing per-node `emit_plan_phase_status` calls. Breaking changes to
client payloads are allowed **only** if RFC-614 / event catalog updates ship
in the same change batch.

Intent classification (RFC-220 §Streaming) Langfuse metadata attachment is
unchanged.

---

## Configuration

No new configuration keys are required by this RFC. The existing evidence caps,
gather skip policies, and clarification policy configuration (RFC-622) remain.
The checkpoint key suffix (`__strange_loop` vs `__strange_loop_v2`) is derived
from the graph version, not a user-facing config key.

---

## Testing Obligations

- **Lifecycle base**: unit-test `pre` / `project` / `prompt` / `process` / `post`
  in isolation per node. The base driver is tested once; subclasses test stage
  overrides.
- **Phase subgraphs**: each subgraph is a compiled `StateGraph` — testable
  independently with a fixture `LoopRuntimeContext`, without the full outer graph.
- **Routing**: phase-exit routers pattern-match on `RouteDecision` — testable as
  pure functions over typed inputs.
- **Clarification**: native `interrupt()` resume tested via `Command(resume=...)`
  on a checkpointer-backed subgraph; residual sidecar tested via existing
  clarification-policy fixtures.
- **Checkpoint**: resume tested on both `__strange_loop` and `__strange_loop_v2`
  keys for goals interrupted pre- and post-restructure.
- **Isolation**: the RFC-220 isolation tests (Loop Graph `thread_id` ≠ CoreAgent
  `thread_id`) remain unchanged.
- **Compat**: `normalize_station` + `LEGACY_TO_STATION` tests remain the
  guardrail for wire/ledger phase stability.

---

## Non-Goals (this RFC)

- Replacing the `Executor` step-wave execution machinery
  (`_execute_step_collecting_events`, `_run_parallel_step`, act-wave aggregation).
- Replacing the `StrangeLoop.run` / `pump_graph` outer pump.
- Redesigning `GraphPromptWrapper` projection internals (slicing, capping,
  boundary markers).
- Renaming wire-stable deliverable phases or checkpoint ledger phases.
- Changing the `LoopRuntimeContext` / `LoopPhaseScratch` data model.

---

## Implementation Sequence

1. Follow the **Implementation Guide**
   [`IG-sloop-generalized-node-topology.md`](../impl/IG-sloop-generalized-node-topology.md)
   (phased P1–P8).
2. P1–P2: introduce `LoopNode` base + `RouteDecision`; migrate simple nodes
   (non-breaking).
3. P3: fold `validate_plan` + `begin_iteration` (internal to execute subgraph).
4. P4–P5: build phase subgraphs; version checkpoint key to `__strange_loop_v2`.
5. P6: replace executor interrupt seam with native `interrupt()`.
6. P7: collapse residual `await_user` sidecar to 2 non-return origins.
7. Update RFC-220 header: `Partially Superseded by: RFC-903`.
8. Run `./scripts/verify_finally.sh`; update RFC-903 status to **Implemented**
   when complete.

---

## Summary

RFC-903 revises RFC-220's flat Loop Graph topology into a phase-subgraph
structure with a generalized 5-method node lifecycle and a typed `RouteDecision`
contract. It replaces the manual clarification round-trip with native LangGraph
`interrupt()` for return-to-sender origins, eliminating the `resume_synth`
workaround and 6 of 9 `await_user` edges. Wire-stable phases and the
two-graphs-two-keys invariant are preserved; the `Executor` step-wave machinery
and `StrangeLoop.run` pump remain under RFC-220 / RFC-201.
