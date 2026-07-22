---
title: "ContextEngine"
parent: Core Modules
grand_parent: Wiki
nav_order: 4
description: Autonomous goal management via goal DAGs, ledger, and bounded projection.
---

# ContextEngine

Autonomous goal management via goal DAGs, ledger, and bounded projection.

---

## What This Module Is

ContextEngine (`soothe.context`) is the **top tier** of Soothe's execution model — the autonomous goal engine. It manages goal execution for long-running, complex workflows. Where StrangeLoop executes a single goal iteratively, ContextEngine orchestrates *which* goals to pursue, in what order, and how they relate to each other.

> **Note**: The legacy `GoalEngine` class was deleted (RFC-625). ContextEngine is now the sole source of truth for goal management. The old goal-engine naming persists in file paths and some config keys for backward compatibility.

ContextEngine composes five subsystems into a single interface: `GoalStepDAG` (goal/step graph), `LedgerManager` (message history), `SemanticLoader` (file/context loading), `ProjectionEngine` (bounded context for prompts), and a pluggable persistence backend (SQLite or PostgreSQL).

**RFC**: [RFC-624](../../specs/RFC-624-context-engine.md), [RFC-625](../../specs/RFC-625-autopilot-monitor-context-engine-unification.md)
**Source**: `packages/soothe/src/soothe/context/engine.py`, `models.py`

---

## The Goal DAG — Why a Graph, Not a List

Goals are organized as a **Directed Acyclic Graph** (DAG), not a flat queue. This is the core design decision. A DAG captures four relationship types that a queue cannot:

- **`depends_on`** — hard dependency: goal B cannot start until goal A completes.
- **`informs`** — soft relationship: goal B should consider A's results, but can proceed without them.
- **`conflicts_with`** — mutual exclusion: goals that shouldn't run concurrently.
- **`parent_id`** — decomposition hierarchy: sub-goals spawned by a parent goal.

Each `GoalNode` also embeds its own `StepDAG` — a per-goal DAG of execution steps with dependencies. This two-level structure (goals form a DAG, each goal's steps form a sub-DAG) lets the engine reason about both inter-goal ordering and intra-goal execution sequencing.

### Goal Lifecycle States

Goals move through these states: `pending → active → completed` (happy path), with branches for `failed`, `suspended`, `blocked`, `awaiting_clarification`, `validated`, and `cancelled`.

Key groupings:
- **Terminal states** (`completed`, `failed`, `cancelled`) — no further transitions.
- **Blocked states** (`awaiting_clarification`, `suspended`) — paused, can resume.

### Goal Depth Limit

There's a `MAX_GOAL_DEPTH = 5` constant — the decomposition hierarchy can't nest deeper than 5 levels. This prevents infinite goal decomposition chains.

---

## The Planning Submodule

ContextEngine exposes a planning facade with three sub-engines:

- **`StepPlanningSubengine`** — plans steps within a single goal's step DAG.
- **`GoalPlanningSubengine`** — decomposes goals, detects relationships between goals.
- **`GoalScheduler`** — decides which ready goals to activate next (priority-based, dependency-aware).

Access via `engine.planning.step`, `engine.planning.goal`, `engine.planning.scheduler`.

---

## Projection — Bounded Context for Prompts

A critical responsibility: ContextEngine produces **bounded projections** of its state for injection into LLM prompts. Without bounds, a long-running workflow with 50 goals and 200 steps would blow the context window.

Projection limits are configured under `agent.loop.context_engine`:

```yaml
agent:
  loop:
    context_engine:
      projection_max_goals: 5
      projection_max_steps_per_goal: 10
      projection_max_ledger_chars: 4000
      projection_max_ledger_messages: 20
      projection_max_lineage_chars: 2000
```

The `ProjectionEngine` assembles a `ContextBundle` containing: DAG snapshot (truncated goals/steps), ledger entries (optionally filtered by phase), goal lineage, and project instructions — all within character/count bounds.

### Ledger Phase Filtering

`get_ledger_entries(phases=["plan", "execute"])` returns only messages from specified phases. This lets the projection include just the relevant reasoning history, not the entire conversation.

---

## Persistence — Follows the Global Backend

ContextEngine does **not** have its own persistence configuration. It follows `persistence.default_backend`:

- When the global backend is `postgresql`, ContextEngine uses `PgsqlContextPersistence` with the same DSN.
- When `sqlite` (default), it uses `SqliteContextPersistence`.
- If no persistence is supplied, it defaults to **in-memory SQLite** (`:memory:`) — suitable for tests only. Production code must supply an explicit backend.

---

## Goal Lifecycle Operations

The async API manages goal state transitions:

- `create_goal(description, priority=, depends_on=)` — creates a pending goal with optional dependencies.
- `activate_goal(goal_id, loop_id=)` — transitions pending → active, assigning it to a StrangeLoop instance.
- `complete_goal(goal_id)` — terminal transition to completed.
- `fail_goal(goal_id, error=, evidence=, allow_retry=True)` — failure with retry support; if retries remain, the goal can be re-activated.
- `suspend_goal(goal_id, reason)` / `block_goal(goal_id)` / `unblock_goal(goal_id)` — temporary pauses.
- `cancel_goal(goal_id, reason=)` — terminal cancellation.

### Retry and Backoff

`GoalNode` tracks `retry_count`, `max_retries` (default 2), `send_back_count`, and `max_send_backs` (default 3). The `fail_goal` call with `allow_retry=True` checks whether retries remain before transitioning to the terminal `failed` state. This gives the engine automatic retry without external orchestration.

### Dreaming (RFC-625)

Goals have `topic` and `findings` fields for "cross-loop dreaming" — a mechanism where completed goals' findings can inform future goal planning. This is part of the autopilot-monitor unification (RFC-625).

---

## Callback System

ContextEngine fires callbacks for lifecycle events: `goal_created`, `goal_activated`, `goal_completed`, `goal_failed`, `goal_suspended`, `goal_cancelled`, `goal_blocked`, `goal_unblocked`, `step_completed`, `step_failed`, `step_skipped`.

```python
engine.on("goal_completed", lambda goal_id: log.info(f"Done: {goal_id}"))
```

This is a simple pub/sub for in-process observers — not to be confused with the event system's client-facing stream.

---

## Step DAG Dependency Resolution

A non-obvious detail: `StepDAG.ready_steps()` uses **dependency token expansion**. When a composite step ID like `KFA-01` is completed, later plans may reference it as `01` or `1`. The `_expand_dependency_satisfaction_ids()` function adds these numeric aliases — but only when unambiguous (i.e., only one completed step has that numeric suffix). This handles the LLM's tendency to use shorthand step references.

---

## Integration Points

- **StrangeLoop** — ContextEngine activates goals and assigns them to StrangeLoop instances via `loop_id`. StrangeLoop reports back via `complete_goal`/`fail_goal`.
- **SootheRunner** — the runner creates loop-scoped ContextEngine instances (RFC-624 Phase 4) and uses projection for prompt context injection.
- **Autopilot** — the daemon-owned autopilot system dispatches goals through ContextEngine, arriving via `LoopRunRequest.autopilot_job`.

---

## Gotchas

- **In-memory default is for tests only** — if you construct `ContextEngine()` without a persistence backend, you get `:memory:` SQLite. State vanishes on process exit. Always pass an explicit backend in production.
- **`max_entries=0` means unlimited** — the `LedgerManager` is initialized with `max_entries=0`, which preserves *full* ledger history. A positive value caps it. This is intentional: downstream LLM calls benefit from full history unless explicitly bounded.
- **Goal source tracking** — `GoalNode.source` can be `user`, `directive`, `file_discovery`, or `decomposition`. This affects how the goal is displayed and whether it can be auto-cancelled.
- **`awaiting_clarification` is a blocked state** — goals in this state won't be scheduled until clarification is provided (RFC-622). They're not terminal.

---

## Related

- **[StrangeLoop](strangeloop.md)** — single-goal execution (middle tier)
- **[SootheRunner](runner.md)** — runner orchestration
- **[RFC-624](../../specs/RFC-624-context-engine.md)** — Context Engine specification
- **[RFC-625](../../specs/RFC-625-autopilot-monitor-context-engine-unification.md)** — unification spec
