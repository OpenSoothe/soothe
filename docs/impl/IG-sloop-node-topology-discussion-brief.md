# StrangeLoop Node & Topology: Discussion Brief

> Companion to `IG-sloop-generalized-node-topology.md`.
> Purpose: distill the design doc into the decisions a reviewer must make,
> with the trade-offs and a recommendation for each. No new discovery here —
> this brief re-presents evidence from IHQ-01 and the design doc.
>
> **Revision 2026-08-18:** Updated to match the merged design doc (5-method
> lifecycle, phase-subgraph topology, `RouteDecision`, native interrupt).
> The original 3-method / flat-graph / `resume_synth`-spike questions are
> resolved; see §3 for the resolution of each orig Q.

---

## At a glance

| Dimension | Current | Proposed | Net change |
|-----------|---------|----------|------------|
| Outer graph nodes | 14 (flat) | ~7 (4 phase subgraphs + 2 sidecars) | −7 |
| Conditional routers | 11 | 4 phase-exit + internal | −7 |
| Routers with inlined fatal-check | 5 | 0 (in `LoopNode.pre()`) | −5 |
| Routers with inlined clarification-check | 4 | 0 (in `LoopNode.pre()`) | −4 |
| Shared node contract | implicit (`async def` shape) | explicit (`LoopNode` 5-method) | new |
| Route return type | free-form dict (6 flags) | `RouteDecision` sum type | new |
| `await_user` edges | 9 | 3 (residual sidecar) | −6 |

The proposal has two independent tracks that can be approved/landed separately:

- **Track A — Node pattern abstraction** (§1): 5-method `LoopNode` lifecycle + `RouteDecision`.
- **Track B — Phase-subgraph topology** (§2): restructure into 4 phase subgraphs + native interrupt.

Track A is non-breaking and low-risk. Track B changes graph shape, touches the
executor interrupt seam (bounded), and has checkpoint implications. They compose
but do not depend on each other.

---

## 1. Generalized Node Pattern (Track A)

### What it is

Every Sloop node today is `async def(ctx, state) -> dict` with the same internal
phases — guard → projection → prompt → core work → state mutation + emit →
route-key return — but that shape is implicit. The proposal makes it an explicit
`LoopNode` base class with five lifecycle methods:

| Method | Replaces today | Role |
|--------|----------------|------|
| `pre` | The `if plan_result is None: emit+return fatal` blocks, resume-skip, pending-clarification, phase status | Uniform precondition; single fatal/defer/skip contract |
| `project` | `resolve_planner_projection_mode` + `project_planner_ledger*` | DAG projection; no-op for non-planner nodes |
| `prompt` | `GraphPromptWrapper.build_messages` (hand-wired per node) | Message assembly; no-op for non-LLM nodes |
| `process` | The core work body | LLM / dispatch / transform — the one abstract method |
| `post` | Scattered `ctx.ce.defer_save()`, `plan_manager.ingest_plan(...)`, route-key dict | Post-work persistence + emit + typed `RouteDecision` |

Plus `RouteDecision` sum type and `GuardOutcome` so the fatal emit+return pair
and the route-key bag of flags live in one typed place.

### Trade-offs

| Pro | Con |
|-----|-----|
| Centralizes the fatal contract (5+ hand-rolled emit+return pairs → one `pre()` default) | Adds an abstraction layer over 14 working nodes |
| Centralizes the clarification-yield contract (4 inlined router checks → one `pre()` guard) | `execute` and `finalize` `process()` is complex; only `pre`/`post` are lightweight, `process` stays opaque |
| Each node's `pre`/`project`/`prompt` testable without graph compilation | Migration is mechanical but touches every node file |
| `GraphPromptWrapper` becomes the default `prompt()`; 4 nodes stop hand-wiring it | 5 methods is more surface than 3 — justified by non-LLM nodes no-opping cleanly (§3.2 of design doc) |
| `RouteDecision` makes the route contract structural, not conventional | — |

### Recommendation

**Adopt the 5-method base, but do NOT force-migrate `execute` and `finalize`
`process()` in v1.** Introduce `LoopNode` as opt-in with a `wrap_node` adapter
that detects base-vs-legacy. Migrate the simplest nodes first (`begin_iteration`,
`check_limits`, `validate_plan`, `commit_plan`) to validate the pattern. Let
`execute`/`finalize` `process()` remain opaque; their `pre`/`post` still
centralize guards.

### Decision needed

- **D1**: Approve Track A (5-method `LoopNode` + `RouteDecision`) as opt-in with legacy adapter? (Y/N — low risk, non-breaking)

---

## 2. Phase-Subgraph Topology (Track B)

### What it changes

Restructure the flat 14-node graph into 4 phase subgraphs (`preprocess`, `plan`,
`execute`, `complete`) + residual sidecars (`delegate`, `await_user`), plus
native `interrupt()` for return-to-sender clarification origins:

| Change | What it eliminates | Rationale |
|--------|---------------------|-----------|
| **Phase subgraphs** | 7 outer nodes + 7 cross-phase routers | Bounds fan-out by phase boundary; each phase owns internal routing |
| **Fold `validate_plan` → `commit_plan.post()`** | 1 node + 2 routers (internal to execute subgraph) | Deterministic check belongs in `CommitPlanNode.post()` |
| **Fold `begin_iteration` → `check_limits.process()`** | 1 node + 1 edge (internal) | Pure setup; merge as non-terminal branch |
| **Native `interrupt()` for 3 origins** | 6 of 9 `await_user` edges + origin map | `execute`/`generate_plan`/`evaluate` re-enter in-place via `Command(resume)` |
| **Residual `await_user` sidecar** | (retained for 2 non-return origins) | `planner_subagent_review` → `delegate`, `rail_pause` → host |
| **Typed `RouteDecision`** | 6 route-key flags | Structural route contract; no bag-of-flags |

### Trade-offs

| Pro | Con / Risk |
|-----|------------|
| Outer graph shrinks 14 → ~7; easier to reason about | Phase-subgraph restructure is larger than flat folds — higher implementation risk |
| Cross-phase fan-out bounded by phase boundary | Checkpoint key must version to `__strange_loop_v2` (in-flight goal migration) |
| Native `interrupt()` deletes 6 `await_user` edges + origin map | Touches executor interrupt seam (`strange_loop.py:599,669`) — bounded but in the process core |
| `resume_synth` eliminated entirely via native interrupt (no spike needed) | Subgraph compilation mechanics need a LangGraph spike (R3) |
| Each phase subgraph independently testable | — |

### Recommendation

Approve in the order the design doc phases them (P1 → P8), each as a standalone
PR with `verify_finally.sh` green:

1. **P1–P2 (low)**: introduce `LoopNode` base + migrate simple nodes — non-breaking.
2. **P3 (medium)**: fold `validate_plan` + `begin_iteration` (internal to execute).
3. **P4–P5 (high)**: build phase subgraphs + version checkpoint key.
4. **P6 (high)**: replace executor interrupt seam with native `interrupt()`.
5. **P7 (medium)**: collapse residual `await_user` sidecar.

### Decisions needed

- **D2**: Approve folding `validate_plan` into `CommitPlanNode.post()`? (Y/N — accept checkpoint cursor move, addressed by key versioning)
- **D3**: Approve folding `begin_iteration` into `CheckLimitsNode`? (Y/N — anchor capture guarded to non-terminal branch)
- **D4**: Approve native `interrupt()` for 3 return-to-sender origins, touching executor seam? (Y/N — replaces `resume_synth` workaround + deletes 6 edges)
- **D5**: Checkpoint key — version as `__strange_loop_v2` at subgraph introduction? (Y/N)

---

## 3. Open Questions Flagged for Review

**The original Q1–Q6 are resolved by the 2026-08-18 revision.** They are
retained below for traceability, with the resolution cross-referenced to the
design doc (§8 of `IG-sloop-generalized-node-topology.md`).

### Q1 — Is `validate_plan` as a separate node load-bearing? (orig §5.2)
**Resolved.** Folded into `CommitPlanNode.post()`; checkpoint cursor moves to
`commit_plan`, addressed by key versioning (§7.2 of design doc).

### Q2 — Anchor capture timing after `begin_iteration` fold (orig §5.3)
**Resolved.** Folded into `CheckLimitsNode.process()` non-terminal branch;
anchor capture guarded by `if last_outcome not in ("max_iterations", "rate_limited")`.

### Q3 — `resume_synth` root-cause vs. workaround (orig §5.4)
**Resolved (supersedes orig Option A/B).** Eliminated via native `interrupt()`:
`ExecuteNode` re-enters with answer, scratch populated normally, `record_progress`
runs without special-casing. No spike needed — the native-interrupt path makes
the `resume_synth` channel structurally unnecessary.

### Q4 — Should `await_user`/`delegate` become subgraphs? (orig §5.5)
**Resolved.** `delegate` remains an outer sidecar (planner review).
`await_user` shrinks to a residual sidecar for 2 non-return origins; 3
return-to-sender origins use native `interrupt()`.

### Q5 — Router guard ordering and opt-in scope (orig §5.6)
**Superseded.** Guards move into `LoopNode.pre()`; routers pattern-match
`RouteDecision.kind` and do not re-check guards. No `with_standard_guards`
decorator needed.

### Q6 — Checkpoint key versioning (orig §5.7)
**Resolved.** Version to `{loop_id}__strange_loop_v2` at subgraph introduction
time; in-flight v1 goals resume on v1 key or via migration shim.

### Remaining open questions (deferred to implementation)

- **R1** — Exact `RouteDecision` field set beyond `kind`/`next_phase`/`clarification_origin`/`state_patch`.
- **R2** — Whether `ClarificationCapture` moves fully into the residual sidecar or stays for the 2 non-return origins.
- **R3** — Subgraph compilation boundary: independently-compiled-and-composed vs. one graph with internal subgraph nodes (LangGraph mechanics spike).

---

## 4. Recommended Approval Slice

If the reviewer wants a minimal first step, the lowest-risk approvable slice is:

> **Approve D1 (Track A opt-in: 5-method `LoopNode` + `RouteDecision`) + P1–P2 (introduce base, migrate simple nodes).**

This delivers the bulk of the maintainability benefit (centralized fatal +
clarification contracts, explicit node lifecycle, typed route contract) with
**zero graph shape change** and **zero checkpoint risk**. Everything else
(D2–D5, P3–P8) can follow as separate review-gated PRs.

---

## 5. Verification Bar (carried from design doc §11)

Any approved phase must clear before merge:

- All existing StrangeLoop tests pass unmodified (no test-cheating, AGENTS.md §8)
- `./scripts/verify_finally.sh` green (lint, format, tests, vulture, module boundaries)
- Outer graph reduced as claimed (14 → ~7) or deviation documented
- No router contains inlined `if last_outcome == "fatal"` or `_pending_clarification` (all in `LoopNode.pre()`)
- `resume_synth`, `after_record_route`, `planner_implement_handoff` channels removed or replaced by `RouteDecision`
- `await_user` edges reduced from 9 to 3 (residual sidecar only)
- Checkpoint resume tested on both `__strange_loop` and `__strange_loop_v2` keys
- `docs/diagrams/strange_loop_graph_nodes.md` and `_edges.md` regenerated

---

## 6. References

- Design doc: `docs/impl/IG-sloop-generalized-node-topology.md`
- IHQ-01 inventory (pattern locations): prior step output
- Builder: `packages/soothe/src/soothe/sloop/orchestrator/builder.py`
- Routers: `packages/soothe/src/soothe/sloop/orchestrator/routing.py`
- State schema: `packages/soothe/src/soothe/sloop/orchestrator/state.py`
- Node implementations: `packages/soothe/src/soothe/sloop/stages/`
