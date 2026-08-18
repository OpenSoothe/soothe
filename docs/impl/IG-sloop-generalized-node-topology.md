# StrangeLoop: Generalized Node Pattern & Topology Simplification

> Implementation guide for RFC-903.
> Status: **Implemented** (P1–P3, commits `ffaa88890`, `fb493aa34`, `da849dc24`).

---

## 1. Executive Summary

The StrangeLoop graph is a compiled `StateGraph(LoopGraphState)`. This guide
documents the implemented simplification:

1. **`LoopNode` base class** with a 5-method lifecycle (`pre` / `project` /
   `prompt` / `process` / `post`) that makes the implicit node shape explicit,
   testable, and uniform.
2. **Typed `RouteDecision` sum type** replacing the free-form route-key dict.
3. **Two node folds** (`validate_plan` → `commit_plan`, `begin_iteration` →
   `check_limits`), reducing topology from 14→12 nodes and 11→8 routers.

The flat graph is retained. Wire-stable phases and the two-graphs-two-keys
invariant are preserved.

---

## 2. Evidence: Current Node Shape

### 2.1 Uniform signature

All graph nodes conform to `async def(ctx, state) -> dict`. The builder wraps
each in a closure binding `ctx`. Migrated nodes use `LoopNode` subclasses
detected by `wrap_node`.

### 2.2 Lifecycle stages (made explicit by `LoopNode`)

| Stage | Responsibility |
|---|---|
| `pre` | Guards (fatal, resume-skip, pending-clarification), phase status |
| `project` | CE ledger projection (no-op for non-LLM nodes) |
| `prompt` | Message assembly (no-op for non-LLM nodes) |
| `process` | Core work (LLM, CoreAgent dispatch, transform) |
| `post` | Scratch/state writes, event emit, route decision |

---

## 3. `LoopNode` Lifecycle

### 3.1 Base class

See RFC-903 §Generalized Node Lifecycle for the full class definition.

### 3.2 Typed contracts

- `RouteDecision(kind, next_phase, clarification_origin, state_patch)` —
  replaces route-key bag of flags.
- `GuardOutcome(kind, state_patch)` — `pre()` short-circuit.
- `NodeResult(payload, events)` — `process()` return fed to `post()`.

### 3.3 `wrap_node` adapter

`wrap_node(station, node, ctx)` detects `LoopNode` vs legacy functions. The
graph builder uses it for migrated nodes.

### 3.4 Migrated nodes

| Node | Class | Notes |
|---|---|---|
| `check_limits` | `CheckLimitsNode` | Folded `begin_iteration` into non-terminal branch |
| `commit_plan` | `CommitPlanNode` | Folded `validate_plan` into `process()` |
| `begin_iteration` | (deleted) | Folded into `check_limits` |
| `validate_plan` | (deleted) | Folded into `commit_plan` |

---

## 4. Node Folds

### 4.1 `validate_plan` → `CommitPlanNode.process()`

Evidence-binding validation (`validate_plan_evidence`) runs after decision
scoping in `CommitPlanNode.process()`. Fatal failure returns
`NodeResult(payload=None, events=[("fatal_error", ...)])`.

Eliminates: `VALIDATE_PLAN` node, `route_after_resolve_decision`,
`route_after_validate_evidence`. Replaced by `route_after_commit`.

### 4.2 `begin_iteration` → `CheckLimitsNode.process()`

Scratch reset, start anchor capture, `iteration_started` emit, and
`resume_synth` clear run in `CheckLimitsNode.process()` non-terminal branch.

Eliminates: `BEGIN_ITERATION` node, unconditional `BEGIN_ITERATION →
GATHER_EVIDENCE` edge. `route_after_iteration_gate` routes directly to
`GATHER_EVIDENCE`.

### 4.3 Topology after folds

12 nodes, 8 conditional routers, 6 unconditional edges.

---

## 5. Migration Path

| Phase | Scope | Status |
|---|---|---|
| P1 | Introduce `LoopNode` base + `RouteDecision` + `GuardOutcome` + `wrap_node` | Done |
| P2 | Migrate `begin_iteration`, `check_limits`, `validate_plan`, `commit_plan` | Done |
| P3 | Fold `validate_plan` + `begin_iteration`; update builder, routers, topology test | Done |

Each phase was a standalone commit with `verify_finally.sh` green.

---

## 6. Verification Criteria

- [x] All existing StrangeLoop tests pass without modification.
- [x] `./scripts/verify_finally.sh` green.
- [x] Node count reduced 14→12, router count 11→8.
- [x] `BEGIN_ITERATION`/`VALIDATE_PLAN` no longer graph nodes.
- [x] `normalize_station` maps legacy IDs for checkpoint resume compat.
- [x] `test_loop_graph_topology.py` asserts the folded node set.

---

## 7. References

- RFC-903: `docs/specs/RFC-903-sloop-graph-topology.md`
- Builder: `packages/soothe/src/soothe/sloop/orchestrator/builder.py`
- Routers: `packages/soothe/src/soothe/sloop/orchestrator/routing.py`
- Node base: `packages/soothe/src/soothe/sloop/orchestrator/node_base.py`
- Node implementations: `packages/soothe/src/soothe/sloop/stages/execute/`
- Topology test: `packages/soothe/tests/unit/core/loop/orchestrator/test_loop_graph_topology.py`
