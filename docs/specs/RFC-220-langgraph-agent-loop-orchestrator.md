# RFC-220: LangGraph Agent Loop Orchestrator

**RFC**: 220
**Title**: LangGraph Agent Loop Orchestrator
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-05
**Dependencies**: RFC-000, RFC-001, RFC-100, RFC-604, RFC-215, RFC-218, RFC-219
**Supersedes**: RFC-201 §loop driver (imperative Plan → Execute driver)
**Related**: RFC-203, RFC-207, RFC-211, RFC-213, RFC-214, RFC-216, RFC-217  

---

## Abstract

Layer 2 single-goal execution **must** be implemented as a **compiled LangGraph `StateGraph`** (the **Loop Graph**). The historical imperative `while`-loop driver described in RFC-201 is **removed**; there is **no** backward-compatible execution path, feature flag, or dual orchestrator.

The Loop Graph orchestrates assess → optional bounded evidence gathering → plan generation → **evidence validation** → execute → persistence → goal completion. Each graph invocation is keyed **only** by **`loop_id`** for LangGraph checkpointing and configurable routing. **CoreAgent** (Layer 1) remains a separate **CompiledStateGraph** keyed by **`thread_id`**. These two checkpoint namespaces **must never** share the same LangGraph thread/checkpoint key.

This RFC also mandates **evidence-bound plan steps**: every planned step references validated evidence identifiers before Execute proceeds.
It also defines graph-entry **intent classification** so conversational fast paths and normal loop execution share one topology.

---

## Motivation

1. **First-class orchestration**: LangGraph provides native routing, checkpoint boundaries, stream modes, and interrupt semantics for the goal runner.
2. **Explicit isolation**: Today’s risk of conflating conversation thread state with loop-scoped state is eliminated by normative ID rules.
3. **Grounded planning**: Plan-generate must not emit unconstrained steps; a small bounded tool phase plus programmatic validation enforces traceability from steps to evidence (extends RFC-604 discipline).

---

## Guiding Principles

1. **Cut-over only** — One orchestrator implementation; remove the imperative loop and obsolete entry points that depended on it.
2. **Two graphs, two keys** — Loop Graph checkpoint identity = `loop_id`; CoreAgent checkpoint identity = `thread_id`. No exceptions.
3. **Protocol reuse** — Keep `PlannerProtocol` / assess + plan structured outputs (RFC-604); keep Executor semantics for parallel / sequential / dependency execution unless a future RFC narrows them.
4. **Evidence before commitment** — Steps are not executable until validation passes (or an explicit repair cycle completes within caps).

---

## Supersedes and Obsolete Surface

When RFC-220 is **Implemented**:

- RFC-201 remains valid for **conceptual** Layer 2 responsibilities (single goal, PlanResult, delegation to CoreAgent) but its **imperative loop construction** is **obsolete**.
- Code paths that expose “AgentLoop as a hand-written async generator loop” are **deleted**, not deprecated.
- Documentation that describes Layer 2 as a Python `while` loop **must** be updated to the Loop Graph model.

Downstream specs (RFC-203, RFC-214, RFC-216, RFC-217) **must** be reconciled in the same implementation batch so they do not assume the removed driver.

---

## Architecture Position

```
Layer 3 (RFC-200) → delegates single goal to Layer 2
Layer 2 (this RFC) → CompiledStateGraph (Loop Graph), thread_id = loop_id for THIS graph only
    └── Execute node → invokes CoreAgent CompiledStateGraph with thread_id = conversation thread
Layer 1 (RFC-100) → tools / subagents
```

---

## Normative Identity and Isolation Rules

| Artifact | Checkpoint / LangGraph `thread_id` | Purpose |
|----------|-----------------------------------|---------|
| **Loop Graph** | **`loop_id`** | Resume orchestration, iteration boundaries, loop persistence correlation |
| **CoreAgent graph** | **`thread_id`** | Conversation transcript, Layer 1 checkpoint under `data/threads/{thread_id}/` |

**Hard requirements:**

1. The **string** passed to the Loop Graph’s LangGraph checkpointer as configurable `thread_id` **must** equal **`loop_id`** (semantic name in docs: **loop checkpoint key**).
2. The **`thread_id`** field on **`LoopState`** is **only** the CoreAgent conversation identifier passed into Execute; it **must not** be used as the Loop Graph’s checkpoint key.
3. Implementations **must** document the pair `(loop_id, thread_id)` on each run for debugging; tests **must** fail if a developer wires CoreAgent’s checkpoint key to `loop_id` or the Loop Graph’s key to `thread_id`.

Files on disk remain aligned with existing layout: loop runtime under **`$SOOTHE_HOME/data/loops/{loop_id}/`**, thread runtime under **`data/threads/{thread_id}/`** (RFC-215).

---

## Loop Graph Topology

### Nodes (normative names)

1. **`init_or_resume`** — Load or initialize loop checkpoint via `AgentLoopStateManager`; construct `LoopState`; run single-shot intent classification for this loop entry; handle thread-continuation bootstrap where applicable.
2. **`iteration_start`** — Iteration begin hooks; checkpoint anchors “start” (RFC-218).
3. **`intent_fast_path`** — Terminal branch for intent `chitchat` / `quiz`; emits graph event payload for runner to execute direct response flow without entering planning nodes.
4. **`bounded_evidence_gather`** — Pre-plan placeholder node in current implementation (retained for topology compatibility).
5. **`plan_assess`** — RFC-604 `StatusAssessment` structured call only.
6. **`plan_pre_generate`** — Deterministic readonly preflight probe (max three probes) to collect baseline workspace evidence.
7. **`plan_generate`** — RFC-604 `PlanGeneration` → `PlanResult` fragment merged into loop contract.
8. **`validate_evidence_bindings`** — Deterministic validation: each step’s evidence references resolve to ledger entries and/or completed prior step ids in scope. On failure: bounded repair loop back to `plan_generate` and/or `bounded_evidence_gather`.
9. **`execute`** — Existing Executor-style execution (parallel / sequential / dependency); streams CoreAgent; records `StepResult`s.
10. **`record_iteration`** — Persist iteration, anchors “end”, emit iteration-complete semantics.
11. **`goal_completion`** — RFC-219 policy branch (skip / direct / synthesize / summary); finalize goal output.

Edges form a directed graph with back-edges only where validation and caps allow (no unbounded cycles).
`init_or_resume` conditionally routes either to `intent_fast_path` or the normal iteration path.

---

## State and Schemas

### Loop graph state

- Carries **`LoopState`** fields required for planning and execution.
- Adds **`evidence_ledger: list[EvidenceEntry]`** (exact shape defined in implementation; must include stable **`evidence_id`**, provenance, and compact summary).
- Adds **`validation_feedback`** / **`repair_round`** counters for bounded repair.

### Step schema extension

Each **`StepAction`** includes **`evidence_refs: list[str]`** (non-empty when the ledger for this iteration is non-empty).

Validation **rejects** plans where any step violates binding rules.

---

## Bounded Evidence Gathering

- **Cap**: Global config for maximum tool invocations per gather phase (small integer).
- **Allowlist**: Read-biased tools and policy-compliant actions only; exact list is policy- and product-dependent (documented in IG).
- **Outputs**: Every successful gather produces ≥1 ledger row or explicit negative evidence row where applicable (implementation guide defines failure ledger semantics).

---

## Persistence Strategy

**Cut-over simplification:** Implementation **may** consolidate loop orchestration persistence into **one** authoritative mechanism:

- Preferred: LangGraph checkpointer for the Loop Graph keyed by `loop_id`, with `AgentLoopStateManager` adapted as the serializer/deserializer for loop checkpoint rows **or** migration of stored rows into the LangGraph store — **single writer**, no duplicate iteration records.

Exact consolidation is specified in the Implementation Guide; this RFC requires **no** duplicate conflicting sources of truth after implementation completes.

---

## Streaming and Observability

The runner **consumes** `compiled.astream` (and compatible modes) from the Loop Graph and maps stream chunks to existing progress contracts (`RFC-614`, event catalog). Execute-phase suppression rules (e.g. IG-304) **remain**; breaking changes to client payloads are allowed **only** if RFC-614 / event catalog updates ship in the same change batch.

Intent classification executed in the graph entry node **must** attach Langfuse metadata consistent with loop tracing (`component=agent_loop.intent_classification`, `phase=agent_loop_graph`, `loop_id`, `thread_id`) so classifier spans are correlated with the same session trace as plan/execute nodes.

---

## Configuration

New configuration keys are introduced for evidence caps, allowlists, repair bounds, and gather skip policies. **`config.yml` template and `config.dev.yml` must be updated together** when defaults are added.

---

## Testing Obligations

- Unit tests per graph node with mocked CoreAgent and planner.
- Integration tests: resume mid-goal, max iterations, fatal execute error, validation failure repair paths.
- **Isolation tests**: assert Loop Graph `thread_id` ≠ CoreAgent `thread_id` at runtime; assert checkpoint DB paths / keys do not collide.

---

## Non-Goals (this RFC)

- Replacing deepagents / CoreAgent internals.
- Changing Layer 3 GoalEngine protocol shapes.
- Preserving API compatibility with pre-RFC-220 runner entrypoints.

---

## Implementation Sequence

1. Follow **Implementation Guides** [IG-394](../impl/IG-394-langgraph-agent-loop-orchestrator.md) and [IG-396](../impl/IG-396-rfc-220-loop-graph-topology-langfuse.md).
2. Implement Loop Graph + delete imperative loop.
3. Reconcile dependent RFCs and docs in the same merge series.
4. Run `./scripts/verify_finally.sh`; update RFC status to **Implemented** when complete.

---

## Summary

RFC-220 normatively defines Layer 2 as a **LangGraph Loop Graph** keyed by **`loop_id`**, strictly isolated from CoreAgent’s **`thread_id`** graph, with **mandatory evidence-bound steps** and **no backward compatibility** with the imperative RFC-201 loop driver.
