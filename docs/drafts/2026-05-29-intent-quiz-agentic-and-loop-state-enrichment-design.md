# Intent Collapse to `quiz | agentic` + AgentLoop Checkpoint Enrichment

**Date:** 2026-05-29
**Status:** Draft (Platonic Brainstorming output)
**Scope:** Refactor intent classification to `quiz | agentic`; make `continue_loop` the structural default for agentic queries within a loop; enrich `GoalExecutionRecord` to carry the per-goal plan DAG, step results, and evidence ledger so the AgentLoop checkpoint becomes the durable orchestration log.

---

## 1. Motivation

Commit `184bf0e1` collapsed the LLM intent classifier output to `quiz | agentic`. The runtime still resolves "agentic" into `continue_thread` / `new_goal` strings via a `GoalEngine.list_goals()` check in `core/runner/_runner_agentic.py:324-337`. Two problems:

1. **Semantically wrong.** Whether a query continues an existing conversation is structural (does the loop have prior goals?), not part of the user's intent classification.
2. **Actually broken.** `GoalEngine` is recreated per request in solo mode → `list_goals()` is always empty → `continue_thread` is always `False` → the entire "thread continuation" pathway is dead code in non-autopilot flows.

Meanwhile, the AgentLoop checkpoint already persists `goal_history` across requests within the same `loop_id` (PostgreSQL / SQLite), so the correct signal is already available — it's just being read from the wrong place. And while we are here, the per-goal record is anaemic: it does not retain the plan DAG, per-step results, or evidence ledger, so cross-goal continuity within a loop has to reconstruct context from the conversation ledger alone.

---

## 2. Design Principles

1. **A `loop_id` is the unit of continuity.** Within one loop, all agentic queries continue on the main thread. Loop boundaries (`/clear`, first start) are the only events that reset goal context.
2. **Intent classification answers one question: quiz vs. agentic.** Structural state (is there prior history?) is derived, not classified.
3. **Single source of truth for "continue".** One flag, derived once in `AgentLoop` from the checkpoint, flows where needed. The dead `LoopState.continue_thread` field is removed.
4. **AgentLoop checkpoint owns orchestration history; LangChain checkpointer owns messages.** A loop has one main thread (`main_thread_id = loop_id`) plus any forked threads from `ThreadForkManager` (RFC-223) for parallel step execution. LangChain checkpoints exist for each of those thread_ids and remain untouched. AgentLoop checkpoint references thread_ids but does not duplicate message-level state.
5. **Per-goal record is the durable orchestration log.** Each `GoalExecutionRecord` carries the latest plan DAG, accumulated step results, and evidence — enough for resume, audit, and continuation context.

---

## 3. Naming Decisions

### 3.1 `continue_thread_mode` → `continue_loop_mode`

Rationale:
- "Thread" is overloaded with LangChain checkpointer threads (multiple per loop with forks).
- The unit of continuity in this design is the **loop**, not a thread.
- The flag's semantic is "this is not the first goal of this loop" — `continue_loop_mode` says exactly that.

The `_THREAD_CONTINUATION_GUIDE` system-prompt section is renamed to `_LOOP_CONTINUATION_GUIDE` for the same reason. `seed_continue_thread_ledger_from_prior_goal()` (which already runs unconditionally) is renamed to `seed_loop_ledger_from_prior_goal()` to match.

### 3.2 Checkpoint status `ready_for_next_goal` → `idle`

The `AgentLoopCheckpoint.status` enum value `ready_for_next_goal` is renamed to `idle`. Shorter, clearer that the loop is alive but not currently executing a goal. Persisted checkpoints with the legacy value are coerced to `idle` in `normalize_checkpoint_data()` on load (see §8 Migration).

---

## 4. Architecture

### 4.1 Intent Model

`IntentClassification` collapses to `quiz | agentic`:

```python
class IntentClassification(BaseModel):
    intent_type: Literal["quiz", "agentic"]
    goal_description: str | None = None
    task_complexity: TaskComplexity
    quiz_response: str | None = None  # piggybacked from LLM for quiz fast-path
```

Removed:
- `reuse_current_goal: bool` (was always derivable from `intent_type`)
- `IntentHint.CONTINUE_THREAD`, `IntentHint.NEW_GOAL` (bypass paths unreachable; `IntentHint.QUIZ` remains)

`IntentClassificationLLMResult.to_intent_classification()` no longer takes a `continue_thread` parameter; non-quiz results return `intent_type="agentic"` directly.

### 4.2 Structural derivation of `continue_loop_mode`

The runner deletes the broken `GoalEngine.list_goals()` block entirely. `AgentLoop.run_with_progress()` derives the flag once, right after `state_manager.load()`, before any branch-specific checkpoint mutation:

```python
checkpoint = await state_manager.load()
continue_loop_mode = (
    checkpoint is not None
    and len(checkpoint.goal_history) >= 1
    and checkpoint.status in ("running", "idle")
)
```

Gating on `status` excludes `finalized` / `cancelled` loops, which the existing else-branch wipes to a fresh checkpoint — those should not inherit dead history. In practice, `/clear` mints a fresh `loop_id`, so finalized loops are rarely loaded; the gate is a correctness belt-and-braces.

The derived flag lives on `LoopRuntimeContext.continue_loop_mode` and is injected into graph state via `executor._execute_graph_input()` so middleware can read `state["continue_loop_mode"]` directly.

### 4.3 State flow

```
Runner                  AgentLoop                            Executor / Middleware
─────────────           ────────────────────                 ───────────────────────────
classify_intent()       load checkpoint
returns quiz|agentic    derive continue_loop_mode (once)

                        LoopRuntimeContext
                         .continue_loop_mode  ────────────►  _execute_graph_input()
                                                              injects continue_loop_mode
                                                              into graph state

                                                              system_prompt_optimization
                                                              reads state["continue_loop_mode"]
                                                              (intent_type plumbing removed)

                        plan_assess reads
                        ctx.continue_loop_mode
                        for bootstrap gating
```

### 4.4 Thread model

One `loop_id` ↔ one main thread (`main_thread_id = loop_id`) ↔ many short-lived forked threads created by `ThreadForkManager` (RFC-223) for parallel plan-step isolation.

- **LangChain checkpointer** holds raw message/tool-call state. Rows per thread_id: `main_thread_id` (CoreAgent orchestration: Plan node, single-step Execute) plus per-step forked thread_ids that inherit predecessor history. Untouched by this refactor.
- **AgentLoop checkpoint** is keyed by `loop_id` only and holds the orchestration ledger. References thread_ids in `thread_ids` and `GoalExecutionRecord.thread_id` but does not duplicate message content.

---

## 5. Checkpoint Layout

### 5.1 `AgentLoopCheckpoint` (top-level, loop-scoped)

No new top-level fields. Schema bump signals the per-goal enrichment.

```python
class AgentLoopCheckpoint(BaseModel):
    # Identity
    loop_id: str
    thread_ids: list[str]          # main + any historical / forked threads referenced
    current_thread_id: str          # = main_thread_id = loop_id in steady state

    # Lifecycle
    status: Literal["running", "idle", "finalized", "cancelled"]   # renamed from ready_for_next_goal

    # Goal history (enriched — see 5.2)
    goal_history: list[GoalExecutionRecord]
    current_goal_index: int

    # Working memory (cleared per goal)
    working_memory_state: WorkingMemoryState

    # Health / metrics
    thread_health_metrics: ThreadHealthMetrics
    total_goals_completed: int
    total_thread_switches: int
    total_duration_ms: int
    total_tokens_used: int

    # RFC-217 goal-context injection
    thread_switch_pending: bool

    # Timestamps + schema
    created_at: datetime
    updated_at: datetime
    schema_version: str = "3.2"     # bumped from "3.1"
```

### 5.2 `GoalExecutionRecord` (per-goal, enriched)

Fields grouped by concern; layout remains flat for query simplicity. `(NEW)` marks additions.

```python
class GoalExecutionRecord(BaseModel):
    # ── Identity ──
    goal_id: str                                  # "{loop_id}_goal_{seq}"
    goal_text: str
    thread_id: str                                # main thread that owned the goal

    # ── Lifecycle ──
    status: Literal["running", "completed", "failed", "cancelled"]
    iteration: int = 0
    max_iterations: int = 10
    started_at: datetime
    completed_at: datetime | None = None

    # ── Orchestration: plan DAG (latest revision only) ── (NEW)
    current_plan: PlanResult | None = None        # latest PlanResult; supersedes previous
    completed_step_ids: set[str] = set()          # mirror of LoopState.completed_step_ids
    plan_revision_count: int = 0                  # monotonic; full history emitted via events

    # ── Execution: per-step outcomes & evidence ── (NEW)
    step_results: list[StepResult] = []           # rolling, all steps for this goal
    evidence_ledger: list[EvidenceEntry] = []     # rolling EvidenceEntry list

    # ── Conversation ledger (orchestration Human-AI pairs) ──
    loop_messages: list[LoopHumanMessage | LoopAIMessage] = []

    # ── Output ──
    goal_completion: str = ""
    evidence_summary: str = ""

    # ── Metrics ──
    duration_ms: int = 0
    tokens_used: int = 0
```

### 5.3 Persistence write path (on goal completion)

```
LoopState (transient)              ────►  GoalExecutionRecord (persisted)
─────────────────────────────────         ─────────────────────────────────
current_decision.plan_result        ►     current_plan
completed_step_ids                  ►     completed_step_ids
step_results                        ►     step_results
evidence_ledger                     ►     evidence_ledger
plan revisions (counted)            ►     plan_revision_count++ on each new plan
loop_messages (already mirrored)    ►     loop_messages
final answer text                   ►     goal_completion
evidence_summary                    ►     evidence_summary
```

Storage notes:
- `step_results` is unbounded by design (mirrors runtime). A future cap is a config knob; out of scope here.
- `current_plan` keeps only the latest revision. Prior revisions are observable via the existing event stream, not the checkpoint.

### 5.4 Plan DAG recoverability

The full plan DAG of any goal is recoverable from `GoalExecutionRecord` alone:

| DAG element | Source field |
|---|---|
| Nodes (steps) | `current_plan.decision.steps: list[StepAction]` — each `StepAction` carries `id`, `description`, `expected_output` |
| Edges (dependencies) | `StepAction.dependencies: list[str] \| None` |
| Execution mode (parallel vs. dependency) | `current_plan.decision.execution_mode` |
| Planner metadata | `current_plan.decision.reasoning`, `current_plan.decision.adaptive_granularity` |
| Done-node overlay | `completed_step_ids: set[str]` |
| Per-node outcomes | `step_results: list[StepResult]` (keyed by `step_id`) |
| Overall plan status | `current_plan.status` (`continue` / `replan` / `done`), `current_plan.goal_progress` |

What is **not** recoverable from the checkpoint: prior plan revisions (only their count survives in `plan_revision_count`). Revision content flows through the event stream by design.

---

## 6. What Stays vs. What We Drop

### Drop (dead weight in the target design)

| Item | Reason |
|---|---|
| `LoopState.continue_thread: bool` (`core/loop/state/schemas.py:823`) | Written at `agent_loop.py:325`; no reader anywhere. Pure dead field. |
| `state.continue_thread = True` write block (`agent_loop.py:323-326`) | Follows from dropping the field. |
| `IntentHint.CONTINUE_THREAD`, `IntentHint.NEW_GOAL` | Both bypass paths unreachable. `parse_intent_hint()` already warns + returns None on unknown values, so external clients sending these strings degrade gracefully. |
| `intent_type` string in graph state (`executor.py:954-966`, `system_prompt_optimization.py:438-451`) | Replaced by `continue_loop_mode: bool` flowing through state. |
| `GoalEngine.list_goals()` structural check in runner (`_runner_agentic.py:324-337`) | Broken in solo mode; replaced by checkpoint-based derivation in `AgentLoop`. |
| Status literal `"ready_for_next_goal"` | Renamed to `"idle"`; coercion handled in `normalize_checkpoint_data()` for legacy persisted values. |

### Keep (load-bearing, single source of truth)

| Item | Role |
|---|---|
| `LoopRuntimeContext.continue_loop_mode: bool` | Canonical flag. Derived once in `AgentLoop`; passed to `plan_assess` and injected into graph state. |
| `continue_thread_plan_bootstrap_allowed()` → renamed `continue_loop_plan_bootstrap_allowed()` | Plan-bootstrap gating; takes the bool. |
| `_LOOP_CONTINUATION_GUIDE` (renamed from `_THREAD_CONTINUATION_GUIDE`) | System-prompt section; middleware injects when `state["continue_loop_mode"]` is `True`. |
| `seed_loop_ledger_from_prior_goal()` (renamed from `seed_continue_thread_ledger_from_prior_goal`) | Already runs unconditionally for any same-loop new goal. |

---

## 7. Files Touched

| Area | File | Change |
|---|---|---|
| Intent | `core/intention/models.py` | Literal collapse, drop `reuse_current_goal`, drop `CONTINUE_THREAD` / `NEW_GOAL` hints |
| Intent | `core/intention/classifier.py` | Drop `continue_thread` parameter; non-quiz → `"agentic"`; remove fallback / heuristic mode resolution |
| Intent | `core/intention/prompts.py` | Already matches `quiz | agentic`; doc cleanup only |
| Runner | `core/runner/_runner_agentic.py` | Delete `GoalEngine` check (lines 324-337); stop passing `continue_thread` to classifier |
| Loop | `core/loop/engine/agent_loop.py` | Derive `continue_loop_mode` from checkpoint; drop intent-string check; drop `state.continue_thread =` write; update log line |
| Loop | `core/loop/engine/executor.py` | `_execute_graph_input()` injects `continue_loop_mode` into state; remove `intent_type` plumbing |
| Loop | `core/loop/engine/scenario_classifier.py` | Default `intent_type = "agentic"`; update prompt docstring |
| Loop | `core/loop/orchestrator/nodes/plan_assess.py` | Rename helpers + docstrings; use `continue_loop_mode` |
| Loop | `core/loop/orchestrator/runtime_context.py` | Rename `continue_thread_mode` → `continue_loop_mode` |
| Middleware | `middleware/system_prompt_optimization.py` | Read `state["continue_loop_mode"]` bool; drop `intent_type` string scenario branches; rename guide |
| Prompts | `core/prompts/system_templates.py` | Rename `_THREAD_CONTINUATION_GUIDE` → `_LOOP_CONTINUATION_GUIDE` |
| State | `core/loop/state/schemas.py` | Drop `LoopState.continue_thread` field |
| State | `core/loop/state/checkpoint.py` | Enrich `GoalExecutionRecord` (current_plan, step_results, evidence_ledger, completed_step_ids, plan_revision_count); rename status `ready_for_next_goal` → `idle` (Literal + `_AGENT_LOOP_CHECKPOINT_STATUSES`); coerce legacy value in `normalize_checkpoint_data()`; bump `schema_version = "3.2"` |
| State | `core/loop/state/manager.py` | Persist + restore new `GoalExecutionRecord` fields; rename `ready_for_next_goal` references (5 sites: `initialize()`, save-status setter, recovery branch, log lines) |
| Loop | `core/loop/orchestrator/nodes/execute_steps.py` | Rename `ready_for_next_goal` setter → `idle` |
| Loop | `core/loop/orchestrator/nodes/max_iterations_terminal.py` | Rename `ready_for_next_goal` setter → `idle` |
| Tests | `tests/unit/core/test_intent_classification.py` | Rewrite assertions to `"agentic"`; drop `reuse_current_goal` |
| Tests | `tests/unit/core/loop/engine/test_scenario_classifier.py` | `"new_goal"` → `"agentic"` |
| Tests | `tests/unit/core/loop/orchestrator/test_init_or_resume_intent_fast_path.py` | Drop `reuse_current_goal` |
| Tests | `tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py` | Rename references; flag is bool — no behavior change |
| Tests | `tests/unit/core/loop/state/test_checkpoint_normalize.py` | Update for `idle` status + legacy coercion assertion |
| Tests | `tests/unit/core/loop/state/test_checkpoint_index_fix.py` | Rename `ready_for_next_goal` → `idle` |
| Tests | `tests/unit/core/loop/core/test_agent_loop_adaptive_final.py` | Rename `ready_for_next_goal` → `idle` |
| Tests | `tests/unit/core/loop/engine/test_goal_context_manager.py` | Rename `ready_for_next_goal` → `idle` |
| Tests | new: `tests/unit/core/loop/state/test_goal_record_enrichment.py` | Verify per-goal persist/restore of plan, steps, evidence |
| SDK | `soothe-sdk/.../client/websocket.py:314` | Docstring: intent_hint standard values reduced to `"quiz"` |
| Client | `client/go/send_methods.go:118` | Comment update |

---

## 8. Migration Safety

- `LoopState.intent: Any | None` (`schemas.py:831`) is loose-typed — old checkpoints carrying stale `intent_type="continue_thread"` strings won't fail Pydantic validation on load.
- New `GoalExecutionRecord` fields all default to `None` / empty collections; old records deserialize cleanly under `schema_version="3.1"`. The version bump to `"3.2"` is informational (per RFC-216 the field is metadata, not a migration gate).
- Status rename `ready_for_next_goal` → `idle`: `normalize_checkpoint_data()` already validates `status` against `_AGENT_LOOP_CHECKPOINT_STATUSES` and defaults unknown values. We extend it with an explicit coercion: if `status == "ready_for_next_goal"`, rewrite to `"idle"` before the validation gate. This makes legacy persisted checkpoints (PostgreSQL JSONB rows, SQLite blobs) load cleanly without a schema migration.
- Live daemons mid-deploy: stale `intent_type` strings flowing through middleware state become unreachable (middleware switches to `continue_loop_mode` bool), so they are silently ignored.
- External clients sending `intent_hint=continue_thread` / `new_goal`: `parse_intent_hint()` already returns `None` on unknown values with a `logger.warning`. Behavior degrades to "no hint" — same as omitting the parameter.

---

## 9. Verification

```bash
cd packages/soothe
python -m pytest tests/unit/core/test_intent_classification.py -v
python -m pytest tests/unit/core/loop/state/ -v
python -m pytest tests/unit/core/loop/ -v
python -m pytest tests/unit/ -x --timeout=60
python -m mypy src/soothe/core/intention/ src/soothe/core/loop/state/ --ignore-missing-imports
./scripts/verify_finally.sh
```

Manual verification:
- Fresh `/clear` → new `loop_id` → first agentic query routes as `continue_loop_mode = False` → new_goal scenario in prompt.
- Second query in same loop → checkpoint loaded with `goal_history >= 1` and `status == "idle"` → `continue_loop_mode = True` → `_LOOP_CONTINUATION_GUIDE` injected; prior goal ledger seeds the new goal.
- Daemon-mode (PostgreSQL) and solo-mode (SQLite) checkpoints both yield correct derivation — solo mode was previously broken.
- Per-goal record after completion contains: latest `current_plan` (with full `decision.steps` DAG), all `step_results`, accumulated `evidence_ledger`, `completed_step_ids`. Inspect via direct DB query or a debug CLI.
- Legacy checkpoint with `status="ready_for_next_goal"` loads under new code and surfaces as `status="idle"` (verified via `normalize_checkpoint_data()` coercion test).

---

## 10. Open Questions / Future Work

- **`step_results` size cap.** Long-running multi-iteration goals may accumulate many step results. A configurable cap (e.g., `loop.checkpoint.max_step_results_per_goal`) is a future knob.
- **Plan revision audit.** `plan_revision_count` is a monotonic counter; the full revision history is only available via the event stream. If audit demands grow, a compact `list[PlanRevisionSummary]` can be added without breaking the layout.
- **Cross-goal evidence reuse.** With `evidence_ledger` now per-goal-durable, a follow-up RFC could surface prior-goal evidence to the planner directly (today only the orchestration ledger crosses goal boundaries via `seed_loop_ledger_from_prior_goal()`).

---

## 11. Out of Scope

- Renaming `RoutingClassification` or restructuring the routing flow.
- Changes to `ThreadForkManager` / fork semantics (RFC-223 remains as-is).
- Changes to the LangChain checkpointer.
- `thread_health_metrics` per-thread tracking with forks.
- New event types (existing events suffice; only docstrings update).
