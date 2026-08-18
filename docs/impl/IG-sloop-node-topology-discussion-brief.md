# StrangeLoop Node & Topology: Discussion Brief

> Companion to `IG-sloop-generalized-node-topology.md`.
> Purpose: distill the design doc into the decisions a reviewer must make,
> with the trade-offs and a recommendation for each. No new discovery here —
> this brief re-presents evidence from IHQ-01 and the design doc.

---

## At a glance

| Dimension | Current | Proposed | Net change |
|-----------|---------|----------|------------|
| Graph nodes | 14 | 11 | −3 (two folds + one workaround removal) |
| Conditional edges | 11 | 8 | −3 |
| Unconditional edges | 7 | 6 | −1 |
| Routers with inlined fatal-check | 5 | 0 (centralized) | −5 |
| Routers with inlined clarification-check | 5 | 0 (centralized) | −5 |
| Shared node contract | implicit (`async def` shape) | explicit (`LoopNode` protocol) | new |

The proposal has two independent tracks that can be approved/landed separately:

- **Track A — Node pattern abstraction** (§1): make the implicit node shape explicit.
- **Track B — Topology simplification** (§2): collapse serial validation chokepoints and centralize cross-cutting guards.

Track A is non-breaking and low-risk. Track B changes graph shape and has checkpoint implications. They compose but do not depend on each other.

---

## 1. Generalized Node Pattern (Track A)

### What it is

Every Sloop node today is `async def(ctx, state) -> dict` with the same internal
phases — guard → status emit → core work → state mutation → event emit →
route-key return — but that shape is implicit. The proposal makes it an explicit
`LoopNode` protocol with three lifecycle hooks:

| Hook | Replaces today | Role |
|------|----------------|------|
| `precheck` | The `if plan_result is None: emit+return fatal` blocks | Uniform precondition; single fatal contract |
| `run` | The core work body | LLM / dispatch / transform |
| `postrun` | Scattered `ctx.ce.defer_save()`, `plan_manager.ingest_plan(...)` | Post-work persistence |

Plus standard `NodeResult` and `FatalGuard` types so the fatal emit+return
pair (currently hand-rolled in 5+ nodes) lives in one place.

### Trade-offs

| Pro | Con |
|-----|-----|
| Centralizes the fatal contract (5+ hand-rolled emit+return pairs → one `FatalGuard.apply`) | Adds an abstraction layer over 14 working nodes |
| Centralizes the clarification-yield contract (5 inlined router checks → one guard) | `execute` and `finalize` are complex enough that the 3 hooks may not cleanly partition their logic |
| Each node's `run` becomes a pure function testable without graph compilation | Migration is mechanical but touches every node file |
| Wrapper can auto-emit `node_started`/`node_completed` with timing, replacing per-node status calls | — |
| Single docstring = single source of truth for "how a Sloop node works" | — |

### Recommendation

**Adopt the protocol, but do NOT force-migrate `execute` and `finalize` in v1.**
Introduce `LoopNode` as opt-in with a `wrap_node` adapter that detects
protocol-vs-legacy. Migrate the simplest nodes first (`begin_iteration`,
`check_limits`, `validate_plan`, `commit_plan`) to validate the pattern. Let
`execute`/`finalize` remain legacy-wrapped until a natural refactor opportunity.

### Decision needed

- **D1**: Approve Track A as opt-in with legacy adapter? (Y/N — low risk, non-breaking)

---

## 2. Simplified Topology (Track B)

### What it changes

Three concrete folds/removals plus two centralizations:

| Change | What it eliminates | Rationale |
|--------|---------------------|-----------|
| **Fold `validate_plan` → `commit_plan`** | 1 node + 2 routers (`route_after_resolve_decision`, `route_after_validate_evidence`) | `validate_plan` is a single deterministic check + fatal-guard; it belongs in `commit_plan.postrun` |
| **Fold `begin_iteration` → `check_limits`** | 1 node + 1 unconditional edge | `begin_iteration` is pure setup (scratch reset, anchor capture, status emit); merge as the non-terminal branch of `check_limits` |
| **Remove `resume_synth` channel** | 1 special-case router branch + 1 state channel | Root-cause fix: make `node_execute` always populate `ctx.scratch.decision`/`plan_result` on the resume path |
| **Centralize fatal-guard** | 5 inlined `if last_outcome == "fatal"` checks | One `with_standard_guards` decorator on routers |
| **Centralize clarification-yield** | 5 inlined `_pending_clarification` checks | Same decorator, applied as router precondition |

### Trade-offs

| Pro | Con / Risk |
|-----|------------|
| Fewer nodes = smaller checkpoint surface, easier resume reasoning | Folding `validate_plan` moves its checkpoint cursor to `commit_plan` — semantically equivalent (plan not yet committed) but cursor position changes |
| Centralized guards = one place to fix a routing bug | Decorator ordering is load-bearing: fatal > clarification > node-own route; must be opt-in per router (not blanket) |
| Removes `resume_synth` workaround → fewer special cases | Root-cause fix requires understanding the full clarification-resume flow (`graph_interrupt.py`, `continuation_context.py`) — higher risk, may need a spike first |
| Smaller graph = faster compile, smaller state schema | In-flight goals at migration time may resume at a different station → needs checkpoint key versioning or a migration shim |

### Recommendation

Approve in the order the design doc phases them (P3 → P4 → P5), each as a
standalone PR with `verify_finally.sh` green:

1. **P3 (medium)**: centralize the two guards first — pure refactor, no shape change.
2. **P4 (medium)**: fold `validate_plan` and `begin_iteration` — shape change but low logic risk.
3. **P5 (high)**: eliminate `resume_synth` — defer until a clarification-resume spike confirms the root-cause fix is safe.

### Decisions needed

- **D2**: Approve folding `validate_plan` into `commit_plan`? (Y/N — accept checkpoint cursor move)
- **D3**: Approve folding `begin_iteration` into `check_limits`? (Y/N — anchor capture guarded to non-terminal branch)
- **D4**: `resume_synth` — root-cause fix (Option A) or keep as documented first-class route (Option B)?
- **D5**: Checkpoint key — version as `__strange_loop_v2` at fold time, or add migration shim for in-flight goals?

---

## 3. Open Questions Flagged for Review

These are the items where the design doc explicitly asks for a reviewer call
rather than recommending a default:

### Q1 — Is `validate_plan` as a separate node load-bearing? (§5.2)
Does anything depend on `validate_plan` being a distinct graph node —
checkpoints, interrupts, observability dashboards? If nothing does, the fold
is safe. If resume logic keys off the `validate_plan` station, the fold needs a
shim.

### Q2 — Anchor capture timing after `begin_iteration` fold (§5.3)
`begin_iteration` calls `capture_iteration_start_anchor`. Folded into
`check_limits`, the anchor must be captured **only on the non-terminal branch**
(guarded against `max_iterations`/`rate_limited`). Is that guard sufficient, or
does any downstream consumer assume the anchor is captured at a distinct step?

### Q3 — `resume_synth` root-cause vs. workaround (§5.4)
Option A (fix `node_execute` to always populate scratch on resume) removes the
special-case channel entirely but requires a spike into the clarification-resume
flow. Option B keeps the channel but documents it. Which does the reviewer
prefer, and is a spike in scope for this work?

### Q4 — Should `await_user`/`delegate` become subgraphs? (§5.5)
They're topologically inline but semantically sidecars (clarification relay,
subagent dispatch). Extracting to subgraphs would clean the main topology but
adds LangGraph subgraph checkpoint complexity. Design doc recommends: **keep
inline for v1, revisit if a third sidecar appears.** Confirm?

### Q5 — Router guard ordering and opt-in scope (§5.6)
The `with_standard_guards` decorator applies fatal → clarification → node-own
route. `route_after_preprocess` and `route_after_iteration_gate` must be
excluded (they run outside the mid-pipeline window). Confirm the decorator is
opt-in per router, not blanket-applied?

### Q6 — Checkpoint key versioning (§5.7)
Folding nodes changes which stations a checkpoint can resume from. For in-flight
goals at migration time, a one-time resume mismatch is possible. Version the key
(`__strange_loop_v2`) or add a migration shim? Needs investigation in
`graph_interrupt.py` / `continuation_context.py`.

---

## 4. Recommended Approval Slice

If the reviewer wants a minimal first step, the lowest-risk approvable slice is:

> **Approve D1 (Track A opt-in) + P3 (centralize guards).**

This delivers the bulk of the maintainability benefit (centralized fatal +
clarification contracts, explicit node protocol) with **zero graph shape change**
and **zero checkpoint risk**. Everything else (D2–D5, P4–P5) can follow as
separate review-gated PRs.

---

## 5. Verification Bar (carried from design doc §7)

Any approved phase must clear before merge:

- All existing StrangeLoop tests pass unmodified (no test-cheating, AGENTS.md §8)
- `./scripts/verify_finally.sh` green (lint, format, tests, vulture, module boundaries)
- Node count reduced as claimed (or rejection documented)
- No router contains inlined `if last_outcome == "fatal"` or `_pending_clarification`
- `resume_synth` channel removed (if D4 = Option A) or documented (if Option B)
- Checkpoint resume tested for goals interrupted pre- and post-fold
- `docs/diagrams/strange_loop_graph_nodes.md` and `_edges.md` regenerated

---

## 6. References

- Design doc: `docs/impl/IG-sloop-generalized-node-topology.md`
- IHQ-01 inventory (pattern locations): prior step output
- Builder: `packages/soothe/src/soothe/sloop/orchestrator/builder.py`
- Routers: `packages/soothe/src/soothe/sloop/orchestrator/routing.py`
- State schema: `packages/soothe/src/soothe/sloop/orchestrator/state.py`
- Node implementations: `packages/soothe/src/soothe/sloop/stages/`
