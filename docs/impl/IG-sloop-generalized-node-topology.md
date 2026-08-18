# StrangeLoop: Generalized Node Pattern & Simplified Topology Proposal

> Design doc synthesizing patterns discovered in the IHQ-01 inventory of the
> StrangeLoop LangGraph codebase (`packages/soothe/src/soothe/sloop/`).
> Status: **P1–P3 implemented; P4–P8 withdrawn/deferred** (commits
> `ffaa88890`, `fb493aa34`, `da849dc24`).
>
> **Revision 2026-08-18 (post-implementation):**
> - **P4–P5 withdrawn:** Phase-subgraph topology doesn't compose with
>   LangGraph's subgraph model (6 of 8 routers cross phase boundaries).
> - **P6–P7 withdrawn:** Native `interrupt()` for return-to-sender origins is
>   not feasible — `ask_user` interrupts originate in CoreAgent (Layer 1),
>   not StrangeLoop (Layer 2). The current `ClarificationCapture` relay is
>   the correct cross-graph interrupt pattern.
> - **P8 deferred:** `execute` (663 lines) and `finalize` (517 lines) are too
>   complex for the 5-method split to cleanly partition. Defer until a natural
>   refactor opportunity.
>
> **P1–P3 delivered:**
> - `LoopNode` 5-method base class + `RouteDecision` + `GuardOutcome` + `wrap_node`
> - 4 simple nodes migrated (`begin_iteration`, `check_limits`, `commit_plan`, `validate_plan`)
> - `validate_plan` folded into `commit_plan`, `begin_iteration` folded into `check_limits`
> - Topology: 14→12 nodes, 11→8 conditional routers
>
> The flat graph with `LoopNode` lifecycle + node folds is the **final target
> topology**. No further phases are planned.

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

1. **A generalized node pattern abstraction** (`LoopNode` base class with a
   5-method lifecycle: `pre` / `project` / `prompt` / `process` / `post`) that
   makes the implicit shape explicit, testable, and uniform, and centralizes
   the fatal / clarification-yield / resume-skip / phase-status guards that are
   currently copy-pasted across nodes and routers.
2. **A typed `RouteDecision` sum type** replacing the free-form route-key dict,
   so the route-key "bag of flags" (`plan_route`, `assess_route`,
   `evidence_gather_route`, `after_record_route`, `resume_synth`,
   `planner_implement_handoff`) becomes one typed value routers pattern-match on.
3. **A phase-subgraph topology** — 4 phase subgraphs (`preprocess`, `plan`,
   `execute`, `complete`) + residual sidecars (`delegate`, `await_user`) — that
   shrinks the outer graph to ~7 nodes and bounds cross-phase fan-out by phase
   boundaries.
4. **Native LangGraph `interrupt()` for return-to-sender clarification origins**
   (`execute`, `generate_plan`, `evaluate`) plus a residual `await_user` sidecar
   for non-return origins (`planner_subagent_review`, `rail_pause`), replacing
   the manual `pending_clarification` channel + origin map for the common path.

The two tracks compose but do not depend on each other:
- **Track A — Node pattern abstraction** (§3): explicit 5-method lifecycle + `RouteDecision`.
- **Track B — Phase-subgraph topology** (§4–§6): restructure into phase subgraphs + native interrupt.

Track A is non-breaking and low-risk. Track B changes graph shape, touches the
executor interrupt seam (bounded), and has checkpoint implications.

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
sequence, which the 5-method lifecycle makes explicit:

| Lifecycle stage | What happens today (ad-hoc) | Evidence |
|-------|--------------|----------|
| **pre** (guard / setup) | Check scratch/ctx for required inputs; if missing, emit `fatal_error` + return `{"last_outcome": "fatal"}`; resume-skip checks; pending-clarification check; emit phase status | `commit_plan.py:42-48`, `validate_plan.py:22-28`, `generate_plan.py:44-49`, `record_progress.py:30-36`, `intake.py` `_should_skip_intent_classify`, `begin_iteration.py:37` (`resume_synth` clear) |
| **project** (DAG projection) | `resolve_planner_projection_mode` + `project_planner_ledger*` slicing | centralized in `GraphPromptWrapper.project_ledger` (commit `85c54753b`); only planner/synthesis nodes use it; `finalize`/`intake` bypass |
| **prompt** (message assembly) | `[SystemMessage, projected_ledger, HumanMessage]` | `GraphPromptWrapper.build_messages`; `finalize` builds its own ledger-human |
| **process** (core work) | LLM call, CoreAgent dispatch, deterministic transform, or persistence | `generate_plan.py:78-100`, `execute.py:251+`, `commit_plan.py:50-85` |
| **post** (mutation + emit + route) | Write to `ctx.loop_state`, `ctx.scratch`, `ctx.plan_manager`, `ctx.ce`; `ctx.emit(...)`; return route-key dict | `commit_plan.py:80-85`, `record_progress.py:39-80`, `begin_iteration.py:18` |

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

Four routers repeat `_pending_clarification(state)` as a first-branch guard:

```python
if _pending_clarification(state):
    return AWAIT_USER
```

Found in: `route_after_plan`, `route_after_evaluate`, `route_after_execute`,
`route_after_wired_subagent`. This is a cross-cutting concern inlined into every
router rather than centralized.

### 2.5 The route-key bag of flags

Nodes return a free-form dict of routing channels: `plan_route`, `assess_route`,
`evidence_gather_route`, `after_record_route`, `resume_synth`,
`planner_implement_handoff`, `last_outcome`. Nine `route_after_*` functions each
read a different subset of these flags. Special-case flags like `resume_synth`
(set in `begin_iteration`, checked in `route_after_execute`) and
`planner_implement_handoff` (set in `delegate`, checked in
`route_after_wired_subagent`) leak across node boundaries.

### 2.6 Scratch-vs-state split

Rich planner outputs (`PlanResult`, `AgentDecision`, `StatusAssessment`,
`StepExecutionRecord[]`) live on `ctx.scratch: LoopPhaseScratch` (non-serialized),
while only routing keys live on the LangGraph `LoopGraphState` (serialized,
checkpoint-safe). This split is correct but undocumented at the node level — each
node independently "knows" to read from `ctx.scratch` rather than `state`.

### 2.7 The clarification round-trip

`await_user` is the only cross-cutting edge. Four nodes (`execute`,
`generate_plan`, `evaluate`, `delegate`) set `pending_clarification` and route
to `await_user`; `route_after_clarification` reads `last_clarification_origin`
to map back to the resume node. `await_user` has 5 out-edges (→ end, delegate,
evaluate, execute, generate_plan) and 4 in-edges. This manual channel partially
re-invents LangGraph's native `interrupt()`/`Command(resume=...)`, which the
checkpointer already supports.

---

## 3. Proposed: Generalized Node Pattern (Track A)

### 3.1 `LoopNode` base class — 5-method lifecycle

**[orig §3.1 proposed a 3-method protocol (`precheck`/`run`/`postrun`). This
revision expands to 5 methods, separating projection and prompt-injection as
distinct stages so non-LLM nodes can no-op them and `GraphPromptWrapper` becomes
the default `prompt()` implementation rather than hand-wired per node.]**

```python
class LoopNode(ABC):
    """Uniform lifecycle for every StrangeLoop graph node.

    Subclasses override the stages they need. The base __call__ runs:
        pre -> project -> prompt -> process -> post
    and centralizes fatal / pending-clarification / resume-skip / phase-status
    guards that are currently copy-pasted per node.
    """

    station: str
    call_kind: GraphCallKind | None = None  # None for non-LLM nodes

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
        Returns a typed NodeResult. May call interrupt() for
        return-to-sender clarification origins (see §6)."""

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

### 3.2 Why 5 methods, not 3

The original 3-method `precheck`/`run`/`postrun` lumps projection, prompt
assembly, and core work into `run`. Separating them:

| Benefit | Rationale |
|---|---|
| Non-LLM nodes no-op cleanly | `validate_plan`, `commit_plan`, `check_limits`, `begin_iteration`, `record_progress`, `gather_evidence` inherit default no-op `project()`/`prompt()` and override only `pre`/`process`/`post`. Under 3-method, `run` would mix LLM-adjacent assembly with core work. |
| `GraphPromptWrapper` becomes the default | The recently-centralized wrapper (commit `85c54753b`) is the default `prompt()`; nodes stop hand-wiring it. Under 3-method, each node re-wires the wrapper in `run`. |
| Projection is independently testable | `project()` returns a `ProjectionResult` testable as a pure function of `(call_kind, state)`. Under 3-method, projection is buried in `run`. |
| `process()` stays opaque to the topology | The executor/strange_loop core (4000+ lines) is touched only via `process()`, which remains `ctx.strange_loop.<phase>`. The 5-method split keeps the heavy process core fenced while exposing the lightweight stages. |

### 3.3 Typed return contract — `RouteDecision`

**[orig §3.3 proposed `NodeResult(route_keys, events)` keeping the free-form
dict. This revision replaces it with a sum type so the route-key bag of flags
(§2.5) is structural, not convention.]**

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

This collapses `resume_synth`, `after_record_route`, `planner_implement_handoff`,
and the three `*_route` flags into one typed value. The bag-of-flags problem is
solved structurally: you cannot set a flag that the router doesn't know about.

### 3.4 Standard guard types

```python
@dataclass
class GuardOutcome:
    """Short-circuit result from LoopNode.pre()."""
    kind: Literal["fatal", "deferred", "skip"]
    state_patch: dict = field(default_factory=dict)

    def as_state_patch(self) -> dict:
        return {"last_outcome": self.kind, **self.state_patch}
```

`FatalGuard` (orig §3.3) is folded into `GuardOutcome(kind="fatal")`; the
emit-`fatal_error`-then-return pair becomes the `pre()` default.

### 3.5 Node-to-subclass mapping

| Node | pre | project | prompt | process | post |
|---|---|---|---|---|---|
| `IntakeNode` | resume-skip (`_should_skip_intent_classify`) | — | — | `classifier.classify_intake` | emit reasoning |
| `GatherEvidenceNode` | — | — | — | fresh-loop/keep detection | `RouteDecision(proceed)` |
| `EvaluateNode` | status | planner | wrapper | `node_plan_assess` + gap | route |
| `GeneratePlanNode` | status + handoff-hydrate | planner | wrapper | `plan_phase.generate_*` | emit plan |
| `CommitPlanNode` | decision-guard | — | — | `_resolve_decision` + DAG normalize + validate evidence | emit plan_decision |
| `ExecuteNode` | answer-consume | — | — | `executor` (opaque) + native `interrupt()` | step results |
| `RecordProgressNode` | plan-guard | — | — | persist + anchor + emit | route |
| `CheckLimitsNode` | — | — | — | budget/rate-limit check + scratch reset + start anchor | terminal/route |
| `FinalizeNode` | status | synthesis | wrapper | `SynthesisGenerator` | emit completed |

**Note:** `ValidatePlanNode` and `BeginIterationNode` are folded (see §4.2) and
do not appear as separate nodes in the target topology. They are listed here
only to show how their logic maps onto the lifecycle if retained during
transition.

### 3.6 Benefits

1. **Fatal contract centralized**: one `pre()` default replaces 5+ hand-rolled
   emit+return pairs.
2. **Clarification yield centralized**: a `pre()` default guard replaces 4
   inlined `_pending_clarification` router checks.
3. **Projection + prompt centralized**: `GraphPromptWrapper` is the default
   `project()`/`prompt()`; 4 nodes stop hand-wiring it.
4. **Route contract typed**: `RouteDecision` replaces the route-key bag of 6
   flags across 11 routers.
5. **Testability**: each stage is a pure function testable without graph
   compilation; the base driver is tested once.
6. **Documentation**: the base class docstring is the single source of truth.

### 3.7 Migration path (non-breaking)

- Introduce `LoopNode` base + `RouteDecision` + `GuardOutcome`. Each existing
  `node_xxx` function can be wrapped in a `LoopNode` subclass behind the same
  `node_xxx` entry point during transition — no graph change yet.
- Add a `wrap_node(station, node_fn)` adapter in `builder.py` that detects
  whether the target is a `LoopNode` (uses hooks) or a legacy function (current
  behavior).
- Migrate nodes one at a time, starting with the simplest (`begin_iteration`,
  `check_limits`, `validate_plan`, `commit_plan`) to validate the pattern.
- Do NOT rewrite `execute` or `finalize`'s `process()` in the first pass — they
  are the most complex and benefit least from the lightweight-stage
  abstraction. Their `pre`/`post` still centralize guards.

---

## 4. Proposed: Phase-Subgraph Topology (Track B)

**[orig §4 proposed a flat-graph simplification: fold validate_plan into
commit_plan, fold begin_iteration into check_limits, centralize guards as
router decorators, keeping the single flat StateGraph. This revision replaces
that with a phase-subgraph restructure. The original folds are retained as
*internal* simplifications within the execute phase subgraph (§4.2).]**

### 4.1 Target outer graph

The outer graph shrinks from 14 nodes / 11 routers to ~7 outer nodes / 1 router
per phase exit:

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

### 4.2 Phase subgraphs

Each phase owns its internal routing and returns a single `next_phase` exit
channel:

- **`preprocess` subgraph**: `IntakeNode -> EnterLoopNode`; exit router returns
  `{plan, delegate, end}` (replaces `route_after_preprocess`'s 4 targets).
- **`plan` subgraph**: `GatherEvidenceNode -> EvaluateNode -> GeneratePlanNode`;
  internal routing for fresh-skip, structural-keep, assess-route; exit returns
  `{execute, complete, await_user}`.
- **`execute` subgraph**: `CheckLimitsNode -> CommitPlanNode -> ExecuteNode ->
  RecordProgressNode`; owns the iteration loop
  (`RecordProgressNode -> CheckLimitsNode`); exit returns
  `{plan, complete, await_user, end}`.
- **`complete` subgraph**: `FinalizeNode`; exit = `END`.

**Internal folds retained from orig §4.2:**

| Change | Rationale | Where it lives now |
|---|---|---|
| **Fold `validate_plan` into `commit_plan.post()`** | `validate_plan` is a single deterministic check (`validate_plan_evidence`) + fatal-guard. Move to the tail of `CommitPlanNode.post()`. Eliminates 1 node + 2 routers. | Orig §4.2, §5.2 |
| **Fold `begin_iteration` into `check_limits.process()`** | `begin_iteration` is pure setup (scratch reset, anchor capture, `iteration_started` emit). Merge as the non-terminal branch of `CheckLimitsNode`. Eliminates 1 node + 1 unconditional edge. | Orig §4.2, §5.3 |

These folds are *internal* to the execute subgraph; the outer graph is
unaffected. The checkpoint cursor concern (orig §5.7) is addressed by
versioning the checkpoint key at subgraph introduction time (§7).

### 4.3 Routing simplification

The 11 `route_after_*` functions collapse to **4 phase-exit routers** (one per
phase) plus internal subgraph routers. Cross-phase fan-out is bounded by phase
boundaries. LangGraph subgraphs compose with the parent checkpointer natively,
so `interrupt()` persistence and resume still work across `ainvoke` calls.

**[orig §4.3 proposed a `with_standard_guards` router decorator. Under the
phase-subgraph design, the fatal + clarification guards move into `pre()` and
`post()` of the `LoopNode` base (§3.1), so the router decorator is no longer
needed — routers pattern-match on `RouteDecision.kind` and do not re-check
guards. The decorator approach is superseded.]**

### 4.4 Node count reduction

| | Current | Proposed | Delta |
|--|---------|----------|-------|
| Outer nodes | 14 (flat) | ~7 (4 phases + 2 sidecars + entry) | −7 |
| Conditional routers | 11 | 4 phase-exit + internal | −7 |
| Routers with inlined fatal-check | 5 | 0 (in `pre()`) | −5 |
| Routers with inlined clarification-check | 4 | 0 (in `pre()`) | −4 |
| Shared node contract | implicit (`async def` shape) | explicit (`LoopNode` 5-method) | new |
| Route return type | free-form dict (6 flags) | `RouteDecision` sum type | new |

---

## 5. Clarification — Native Interrupt + Residual Sidecar

**[orig §5.5 recommended keeping `await_user`/`delegate` inline for v1. This
revision goes further: native `interrupt()` for return-to-sender origins
removes most `await_user` edges; the residual sidecar handles only non-return
origins.]**

### 5.1 Two clarification categories

Split by whether the resume target is the *same node* that asked:

**Native `interrupt()` (return-to-sender, 3 origins):**
`ExecuteNode`, `GeneratePlanNode`, `EvaluateNode` call `interrupt(request)`
mid-`process`. LangGraph re-enters that exact node on `Command(resume=answers)`.

This deletes:
- 6 of the 9 `await_user` edges (3 in-edges from these nodes to `await_user`,
  and 3 out-edges from `await_user` back to these nodes); the residual sidecar
  keeps 3 edges (the `delegate` round-trip for `planner_subagent_review` and the
  `__end__` defer edge)
- The `route_after_clarification` origin-map logic for these origins
- The `last_clarification_origin` tracking for these origins
- The `pending_clarification` channel writes/reads for these origins

**Residual `await_user` sidecar (non-return, 2 origins):**
- `planner_subagent_review` → resumes to `delegate` (a different node)
- `rail_pause` → host-only, not a StrangeLoop interrupt

These keep the manual channel: the originating node returns
`RouteDecision(kind="await_user", clarification_origin="planner_subagent_review")`;
the outer graph routes to the `await_user` sidecar; on answer, the sidecar
routes to the fixed resume node (`delegate` for planner review).
`ClarificationPolicy.deferred` → `RouteDecision(kind="deferred")` → `END` is
still expressed here.

### 5.2 The executor interrupt seam (in scope, bounded)

The native-interrupt change requires replacing the executor's existing manual
interrupt capture. Today, `_core_agent_astream_with_interrupt_resume`
(`strange_loop.py:669`) runs the CoreAgent stream and, after it ends, calls
`_fetch_pending_interrupts_from_state` (`:599`) to read pending LangGraph
interrupts from graph state and shunt `ask_user` interrupts to
`ClarificationCapture`, which sets `pending_clarification` for the manual
sidecar.

Under the new design, for the 3 return-to-sender origins:

- `ExecuteNode.process()` calls `interrupt(request)` directly; the CoreAgent
  stream pauses at that node; `Command(resume=answers)` re-enters `ExecuteNode`.
- The `_fetch_pending_interrupts_from_state` + `ClarificationCapture` shunt is
  removed for `ask_user` interrupts from these 3 origins.
- `ClarificationCapture` is retained only for the 2 non-return origins (or
  moved entirely into the residual sidecar).

**Boundary of the change:** `_fetch_pending_interrupts_from_state`,
`_core_agent_astream_with_interrupt_resume`, and the call sites in
`StrangeLoop.run` that wire `clarification_detector`/`clarification_capture`.
The step-wave execution machinery (`_execute_step_collecting_events`,
`_run_parallel_step`, act-wave aggregation) is **untouched** — `interrupt()` is
called from the node wrapper, not the executor internals.

**[orig §5.4 proposed fixing `resume_synth` by making `node_execute` always
populate scratch on the resume path. Under native `interrupt()`, the
`resume_synth` channel is eliminated entirely: `interrupt()` re-enters
`ExecuteNode` with the answer, `process()` populates scratch normally, and
`record_progress` runs without special-casing. The orig Option A/B question
(§5.4) is resolved in favor of elimination via native interrupt.]**

---

## 6. Data Flow

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

`LoopRuntimeContext` and `LoopPhaseScratch` are unchanged — they are the mutable
handles the lifecycle reads/writes. The lifecycle does not introduce new shared
state; it formalizes access to the existing state.

---

## 7. Checkpoint & Compat

### 7.1 Wire / ledger phase stability

Wire-stable deliverable phases (`goal_completion`, `execute_step`) and checkpoint
ledger phases (`intent_classify`, `plan_assess`, `plan_generate`,
`plan_gap_analysis`) remain unchanged. `stations.normalize_station` +
`LEGACY_TO_STATION` are the compatibility guardrail — internal station renames
and graph restructuring do not leak to the wire contract.

### 7.2 Checkpoint key versioning

**[orig §5.7 raised checkpoint cursor migration as an open question. Under the
phase-subgraph restructure, the change is larger than a node fold, so the
checkpoint key must be versioned.]**

The graph checkpoint key moves from `{loop_id}__strange_loop` to
`{loop_id}__strange_loop_v2`. In-flight goals at migration time resume on the v1
key (or a migration shim maps v1 cursors to v2 phase-entry points). Needs
investigation in `graph_interrupt.py` / `continuation_context.py` during
implementation.

LangGraph subgraphs compose with the parent checkpointer natively, so
`interrupt()` persistence and resume still work across `ainvoke` calls within
the v2 graph.

---

## 8. Discussion Points for Review

**[orig §5 open questions are resolved or superseded as follows:]**

| Orig Q | Resolution |
|---|---|
| Q1 `validate_plan` separate node load-bearing? | Folded into `CommitPlanNode.post()`; checkpoint cursor moves to `commit_plan`, addressed by key versioning (§7.2). **Resolved.** |
| Q2 Anchor capture timing after `begin_iteration` fold | Folded into `CheckLimitsNode.process()` non-terminal branch; anchor capture guarded by `if last_outcome not in ("max_iterations", "rate_limited")`. **Resolved.** |
| Q3 `resume_synth` root-cause vs. workaround | Eliminated via native `interrupt()` — `ExecuteNode` re-enters with answer, scratch populated normally. **Resolved (supersedes orig Option A/B).** |
| Q4 `await_user`/`delegate` as subgraphs? | `delegate` remains an outer sidecar (planner review). `await_user` shrinks to a residual sidecar for 2 non-return origins; 3 return-to-sender origins use native `interrupt()`. **Resolved.** |
| Q5 Router guard ordering / opt-in | Superseded — guards move into `LoopNode.pre()`, routers pattern-match `RouteDecision.kind`, no decorator needed. **Superseded.** |
| Q6 Checkpoint key versioning | Version to `{loop_id}__strange_loop_v2` at subgraph introduction time. **Resolved.** |

### 8.1 Open questions remaining

- **R1 — `RouteDecision` field set:** exact fields beyond `kind`/`next_phase`/
  `clarification_origin`/`state_patch` deferred to implementation.
- **R2 — `ClarificationCapture` relocation:** whether it moves fully into the
  residual sidecar or stays for the 2 non-return origins only — deferred to
  implementation.
- **R3 — Subgraph compilation boundary:** whether each phase subgraph is
  compiled independently and composed, or compiled as one graph with internal
  subgraph nodes — a LangGraph mechanics question for the implementation spike.

---

## 9. Alternatives Considered

- **Single-dispatch spine.** One `dispatch` node reads a `next_station`
  channel nodes set; 11 routers collapse to 1. Simplest topology to draw, but
  `dispatch` becomes a god-router holding all branch logic in one function.
  Traded fan-out sprawl for centralization. **Rejected:** centralizes at the
  cost of locality.
- **Linear spine + skip-forward.** Single chain, nodes short-circuit via flags.
  Fewest edges, but branching becomes implicit (state flags) not explicit
  (graph edges) — loses the debuggability that the current flat graph provides.
  **Rejected** for a system of this size.
- **Keep executor's manual interrupt model (C-rev-1).** Would stay truly out of
  the process core, but the manual `await_user` channel + origin map survive for
  all 5 origins — losing the main simplification (6 edges deleted) that
  motivated choosing native interrupt. **Rejected** in favor of C-rev-2
  (native interrupt, touch executor seam).

---

## 10. Implementation Phasing (if approved)

| Phase | Scope | Risk | Depends on |
|-------|-------|------|---|
| **P1** | Introduce `LoopNode` base + `RouteDecision` + `GuardOutcome` + `wrap_node` adapter (non-breaking) | Low | — |
| **P2** | Migrate simple nodes (`begin_iteration`, `check_limits`, `validate_plan`, `commit_plan`) to `LoopNode` | Low | P1 |
| **P3** | Fold `validate_plan` into `CommitPlanNode.post()`; fold `begin_iteration` into `CheckLimitsNode` | Medium (checkpoint cursor) | P2 |
| **P4** | Build `preprocess` subgraph, swap into outer graph | Medium | P1 |
| **P5** | Build `plan` + `execute` + `complete` subgraphs; version checkpoint key to `__strange_loop_v2` | High (graph restructure) | P4 |
| **P6** | Replace executor interrupt seam with native `interrupt()` for 3 return-to-sender origins | High (touches `strange_loop.py:599,669`) | P5 |
| **P7** | Collapse residual `await_user` sidecar to 2 non-return origins | Medium | P6 |
| **P8** | (Optional) Migrate `execute`, `finalize` `process()` — only if natural refactor opportunity | High | P1 |

Each phase should be a standalone PR with `./scripts/verify_finally.sh` green.

---

## 11. Verification Criteria (post-implementation)

- [ ] All existing StrangeLoop tests pass without modification (no test-cheating per AGENTS.md §8).
- [ ] `./scripts/verify_finally.sh` is green (lint, format, tests, vulture, module boundaries).
- [ ] Outer graph reduced from 14 flat nodes to ~7 (4 phases + sidecars) or
      deviation documented.
- [ ] No router contains an inlined `if last_outcome == "fatal"` or
      `_pending_clarification` check (all in `LoopNode.pre()`).
- [ ] `LoopGraphState` channels `resume_synth`, `after_record_route`,
      `planner_implement_handoff` removed or replaced by `RouteDecision`.
- [ ] `await_user` edges reduced from 9 to 3 (residual sidecar only).
- [ ] Checkpoint resume tested for goals interrupted pre- and post-restructure
      on both `__strange_loop` and `__strange_loop_v2` keys.
- [ ] `docs/diagrams/strange_loop_graph_nodes.md` and `_edges.md` regenerated via
      `scripts/visualize_strange_loop_graph.py`.

---

## 12. References (internal)

- `packages/soothe/src/soothe/sloop/orchestrator/builder.py` — graph builder
- `packages/soothe/src/soothe/sloop/orchestrator/routing.py` — 11 conditional routers
- `packages/soothe/src/soothe/sloop/orchestrator/state.py` — `LoopGraphState` channels
- `packages/soothe/src/soothe/sloop/orchestrator/runtime_context.py` — `LoopRuntimeContext`
- `packages/soothe/src/soothe/sloop/orchestrator/phase_scratch.py` — `LoopPhaseScratch`
- `packages/soothe/src/soothe/sloop/orchestrator/stations.py` — canonical station ids + `normalize_station`
- `packages/soothe/src/soothe/sloop/prompts/graph_wrapper.py` — `GraphPromptWrapper` (commit `85c54753b`)
- `packages/soothe/src/soothe/sloop/clarification/origins.py` — clarification origins + `resume_node_for_clarification_origin`
- `packages/soothe/src/soothe/sloop/engine/strange_loop.py` — `StrangeLoop.run`, `_fetch_pending_interrupts_from_state` (`:599`), `_core_agent_astream_with_interrupt_resume` (`:669`)
- `packages/soothe/src/soothe/sloop/engine/executor.py` — `Executor` class, step-wave machinery (out of scope)
- `packages/soothe/src/soothe/sloop/stages/` — all 14 node implementations
- `docs/diagrams/strange_loop_graph_nodes.md` — canonical node table
- `docs/diagrams/strange_loop_graph_edges.md` — full edge dump
- `docs/specs/RFC-220-langgraph-agent-loop-orchestrator.md` — implemented parent RFC
- `docs/drafts/2026-08-18-sloop-graph-topology-design.md` — source draft merged into this revision
