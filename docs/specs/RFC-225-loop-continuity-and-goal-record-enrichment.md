# RFC-225: Loop Continuity and Goal Record Enrichment

**RFC**: 225
**Title**: Loop Continuity and Goal Record Enrichment
**Status**: Draft
**Kind**: Architecture Design
**Authors**: xiaming
**Created**: 2026-05-29
**Last Updated**: 2026-05-29
**Depends on**: RFC-201, RFC-214, RFC-216, RFC-218, RFC-220
**Supersedes**: ---
**Related**: RFC-217 (Goal Context Management), RFC-223 (Thread Inheritance with Checkpoint Forking), RFC-224 (Automatic Context Window Management)

---

## 1. Abstract

This RFC defines the loop as the single unit of conversational continuity in StrangeLoop. Intent classification produces only `quiz | agentic`; whether an agentic query continues an in-flight conversation is derived structurally from the persisted checkpoint, not from the classifier. The per-goal record (`GoalExecutionRecord`) is enriched to retain the latest plan DAG, accumulated step results, and the evidence ledger, so the StrangeLoop checkpoint becomes the durable orchestration log across all goals within a loop. Status terminology is aligned with this model (`ready_for_next_goal` → `idle`; `continue_thread_mode` → `continue_loop_mode`).

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

- The runtime model for intent classification: a two-value `intent_type` (`quiz | agentic`) and the structural derivation of `continue_loop_mode` from the loaded checkpoint inside `StrangeLoop`.
- The orchestration ownership boundary between the StrangeLoop checkpoint and the LangChain checkpointer.
- The enriched layout of `GoalExecutionRecord` and the associated `StrangeLoopCheckpoint` status vocabulary.
- The migration / compatibility contract for legacy persisted checkpoint values and stale intent strings.
- The rename of `continue_thread_*` to `continue_loop_*` and `_THREAD_CONTINUATION_GUIDE` to `_LOOP_CONTINUATION_GUIDE`.

### 2.2 Non-Goals

This RFC does **not** define:

- Changes to `ThreadForkManager` semantics or the LangChain checkpointer (RFC-223 remains authoritative).
- Per-thread tracking inside `thread_health_metrics` for forked threads.
- New event types; existing event taxonomy is unchanged.
- A storage cap for `step_results` or `evidence_ledger`; size policy is a future config knob.
- The autonomous / autopilot path's use of `GoalEngine` (RFC-222); only the agentic solo-mode runner is corrected here.

---

## 3. Background & Motivation

Commit `184bf0e1` collapsed the LLM intent classifier's structured output to `quiz | agentic`. However, the runtime still resolves "agentic" into `continue_thread` / `new_goal` strings via a `GoalEngine.list_goals()` check in the agentic runner (`core/runner/_runner_strange_loop.py:324-337`). This produces two defects:

1. **Semantic mismatch.** Whether a query continues an existing conversation is structural — does the loop have prior goals? — not a property of the user's intent. The classifier should not encode loop topology.
2. **Functional regression.** `GoalEngine` is recreated per request in solo mode (the daemon binds it only in autopilot flows), so `list_goals()` is always empty and `continue_thread` is always `False`. The entire same-loop continuation pathway is dead code in non-autopilot use.

Meanwhile, `StrangeLoopCheckpoint` already persists `goal_history` across requests within the same `loop_id` (PostgreSQL or SQLite), so the correct signal exists — it is being read from the wrong place. And while the per-goal record (`GoalExecutionRecord`) holds the conversation ledger (`loop_messages`), it does not retain the plan DAG, per-step results, or evidence — so cross-goal context within a loop must be reconstructed from the conversation alone, and post-mortem inspection of completed goals has no structured artifact.

This RFC corrects the structural derivation, removes dead code, enriches the per-goal record to make the StrangeLoop checkpoint the canonical orchestration log, and renames status / flag identifiers so the loop-centric model is honestly named in the source.

---

## 4. Design Principles

1. **A `loop_id` is the unit of continuity.** Within one loop, every agentic query continues on the main thread. Loop boundaries (`/clear`, fresh start) are the only events that reset goal context.
2. **Intent classification answers one question.** Quiz vs. agentic. Structural state (does the loop have prior goals?) is derived, never classified.
3. **Single source of truth for "continue".** One flag, derived once in `StrangeLoop` from the loaded checkpoint, flows where needed. No parallel state in `LoopState`.
4. **StrangeLoop checkpoint owns orchestration history; LangChain checkpointer owns message state.** A loop has one main thread (`main_thread_id = loop_id`) plus any forked threads from `ThreadForkManager` (RFC-223). LangChain checkpoints exist per `thread_id` for raw messages and tool calls. StrangeLoop checkpoint references thread_ids but does not duplicate message content.
5. **The per-goal record is the durable orchestration log.** Each `GoalExecutionRecord` retains the latest plan DAG, accumulated step results, and the evidence ledger — sufficient for resume, audit, and continuation context.

---

## 5. Architecture

### 5.1 Intent Model

`IntentClassification` collapses to a two-value `intent_type`:

```
IntentClassification:
  intent_type: "quiz" | "agentic"
  goal_description: str | None       # populated for agentic
  task_complexity: minimal | simple | medium | complex
  quiz_response: str | None          # piggybacked from LLM for quiz fast-path
```

Removed:

- `reuse_current_goal` — derivable from `intent_type` in the prior schema; no remaining consumer.
- `IntentHint.CONTINUE_THREAD`, `IntentHint.NEW_GOAL` — bypass paths unreachable in the new model; `IntentHint.QUIZ` is retained.

`IntentClassificationLLMResult.to_intent_classification()` no longer accepts a `continue_thread` parameter. Non-quiz LLM results MUST return `intent_type = "agentic"` directly.

### 5.2 Structural Derivation of `continue_loop_mode`

The agentic runner (`core/runner/_runner_strange_loop.py`) MUST NOT consult `GoalEngine` to determine continuation. `StrangeLoop.run_with_progress()` MUST derive `continue_loop_mode` exactly once, immediately after `state_manager.load()` and before any branch-specific checkpoint mutation:

```
continue_loop_mode :=
    checkpoint is not None
    AND len(checkpoint.goal_history) >= 1
    AND checkpoint.status ∈ {"running", "idle"}
```

Gating on `status` excludes `finalized` and `cancelled` loops, which the existing else-branch wipes to a fresh checkpoint; such loops MUST NOT inherit dead history. In practice, `/clear` mints a fresh `loop_id`, so finalized loops are rarely loaded; the gate is correctness belt-and-braces.

The derived flag is the single source of truth and is propagated by two paths:

- Direct: stored on `LoopRuntimeContext.continue_loop_mode` for use by `plan_assess` (bootstrap gating).
- State: injected into LangGraph input state by `_execute_graph_input()` so middleware reads `state["continue_loop_mode"]` rather than inferring from a stale `intent_type` string.

### 5.3 Thread Model (Boundary Reaffirmation)

One `loop_id` ↔ one main thread (`main_thread_id = loop_id`) ↔ many short-lived forked threads created by `ThreadForkManager` (RFC-223) for parallel plan-step isolation.

- **LangChain checkpointer** — holds raw message / tool-call state. Rows exist per `thread_id`:
  - `main_thread_id` (= loop_id): CoreAgent orchestration thread (Plan node, single-step Execute).
  - Forked `thread_id`s: per-step branches that inherit predecessor history.
  Untouched by this RFC.
- **StrangeLoop checkpoint** — keyed by `loop_id` only. Holds the orchestration ledger: goals, plans, step outcomes, evidence, and the orchestration Human-AI message pairs (`loop_messages`). References thread_ids in `thread_ids` and `GoalExecutionRecord.thread_id` but does not duplicate message-level content.

### 5.4 State Flow

```
Runner                  StrangeLoop                              Executor / Middleware
─────────────           ────────────────────                   ───────────────────────────
classify_intent()       load checkpoint
returns quiz|agentic    derive continue_loop_mode (once)

                        LoopRuntimeContext
                         .continue_loop_mode  ──────────────► _execute_graph_input()
                                                              injects continue_loop_mode
                                                              into LangGraph state

                                                              system_prompt_optimization
                                                              reads state["continue_loop_mode"]
                                                              (intent_type plumbing removed)

                        plan_assess reads
                        ctx.continue_loop_mode
                        for bootstrap gating
```

On goal completion, transient `LoopState` fields (`current_decision.plan_result`, `completed_step_ids`, `step_results`, `evidence_ledger`) MUST be written back into the active `GoalExecutionRecord` before the loop transitions to `idle`.

---

## 6. Data Model

### 6.1 `StrangeLoopCheckpoint`

No new top-level fields. Two changes:

1. `status` literal: `ready_for_next_goal` → `idle`.
2. `schema_version`: bumped `"3.1"` → `"3.2"` to signal the per-goal enrichment.

```
StrangeLoopCheckpoint:
  # Identity
  loop_id: str
  thread_ids: list[str]
  current_thread_id: str          # = main_thread_id = loop_id in steady state

  # Lifecycle
  status: "running" | "idle" | "finalized" | "cancelled"
  #   ─ renamed: "ready_for_next_goal" → "idle"

  # Goal history (enriched — see §6.2)
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
  schema_version: str             # "3.2"
```

### 6.2 `GoalExecutionRecord` (enriched)

Fields are grouped by concern; the layout remains flat for query simplicity. `(NEW)` marks additions vs. schema 3.1.

```
GoalExecutionRecord:
  # ── Identity ──
  goal_id: str                                  # "{loop_id}_goal_{seq}"
  goal_text: str
  thread_id: str                                # main thread that owned the goal

  # ── Lifecycle ──
  status: "running" | "completed" | "failed" | "cancelled"
  iteration: int
  max_iterations: int
  started_at: datetime
  completed_at: datetime | None

  # ── Orchestration: plan DAG (latest revision only) ── (NEW)
  current_plan: PlanResult | None               # latest PlanResult; supersedes previous
  completed_step_ids: set[str]                  # mirror of LoopState.completed_step_ids
  plan_revision_count: int                      # monotonic; full history emitted via events

  # ── Execution: per-step outcomes & evidence ── (NEW)
  step_results: list[StepResult]                # rolling, all steps for this goal
  evidence_ledger: list[EvidenceEntry]          # rolling EvidenceEntry list

  # ── Conversation ledger (orchestration Human-AI pairs) ──
  loop_messages: list[LoopHumanMessage | LoopAIMessage]

  # ── Output ──
  goal_completion: str
  evidence_summary: str

  # ── Metrics ──
  duration_ms: int
  tokens_used: int
```

Storage MUST treat the new fields as optional with safe defaults (`None`, empty collection) so prior `schema_version="3.1"` records deserialize without migration.

### 6.3 Plan DAG Recoverability (Invariant)

The full plan DAG of any persisted goal MUST be recoverable from `GoalExecutionRecord` alone, with no external lookup:

| DAG element | Source field |
|---|---|
| Nodes (steps) | `current_plan.decision.steps: list[StepAction]` — `id`, `description`, `expected_output` |
| Edges (dependencies) | `StepAction.dependencies: list[str] \| None` |
| Execution mode | `current_plan.decision.execution_mode` (`parallel` \| `dependency`) |
| Planner metadata | `current_plan.decision.reasoning`, `adaptive_granularity` |
| Done-node overlay | `completed_step_ids` |
| Per-node outcomes | `step_results: list[StepResult]` (keyed by `step_id`) |
| Overall plan status | `current_plan.status` (`continue` \| `replan` \| `done`), `goal_progress` |

What is **not** recoverable from the checkpoint by design: prior plan revisions. Only their count survives in `plan_revision_count`. Revision content flows through the event stream.

### 6.4 Persistence Write Path

On goal completion (existing transition from `running` → `idle`), the manager MUST mirror transient `LoopState` into the active `GoalExecutionRecord`:

```
LoopState (transient)              ──►  GoalExecutionRecord (persisted)
─────────────────────────────────       ─────────────────────────────────
current_decision.plan_result        ►   current_plan
completed_step_ids                  ►   completed_step_ids
step_results                        ►   step_results
evidence_ledger                     ►   evidence_ledger
plan revisions (counted)            ►   plan_revision_count++ on each new plan
loop_messages (already mirrored)    ►   loop_messages
final answer text                   ►   goal_completion
evidence_summary                    ►   evidence_summary
```

`current_plan` retains only the latest revision; prior revisions are observable via the event stream and are not retained in the checkpoint.

---

## 7. Naming Decisions

### 7.1 `continue_thread_mode` → `continue_loop_mode`

The flag's semantic is "this is not the first goal of this loop". The "thread" terminology is overloaded with LangChain checkpointer threads (multiple per loop with forks); the unit of continuity in this design is the loop. `continue_loop_mode` says exactly what the flag tracks.

Related renames:

- `_THREAD_CONTINUATION_GUIDE` → `_LOOP_CONTINUATION_GUIDE` (system-prompt section).
- `seed_continue_thread_ledger_from_prior_goal()` → `seed_loop_ledger_from_prior_goal()` (already runs unconditionally).
- `continue_thread_plan_bootstrap_allowed()` → `continue_loop_plan_bootstrap_allowed()`.

### 7.2 Status `ready_for_next_goal` → `idle`

Shorter, clearer that the loop is alive but not currently executing a goal. The status' role is unchanged; only the spelling moves. Legacy persisted values are coerced on load (see §9 Migration).

---

## 8. Deletions

The following constructs MUST be removed:

| Item | Reason |
|---|---|
| `LoopState.continue_thread: bool` (`core/loop/state/schemas.py`) | Written but never read; pure dead field. |
| The `state.continue_thread = True` write block in `StrangeLoop` | Follows from dropping the field. |
| `IntentHint.CONTINUE_THREAD`, `IntentHint.NEW_GOAL` enum values | Both bypass paths unreachable; `parse_intent_hint()` already returns `None` (with warning) on unknown values, so external clients sending these strings degrade gracefully. |
| `intent_type` string in LangGraph state (`executor._execute_graph_input`, middleware scenario branches) | Replaced by `continue_loop_mode: bool` flowing through state. |
| `GoalEngine.list_goals()` structural check in `core/runner/_runner_strange_loop.py` | Broken in solo mode; replaced by checkpoint-based derivation in `StrangeLoop`. |

The following constructs are retained as the single source of truth:

| Item | Role |
|---|---|
| `LoopRuntimeContext.continue_loop_mode: bool` | Canonical flag. Derived once in `StrangeLoop`; passed to `plan_assess` and injected into graph state. |
| `continue_loop_plan_bootstrap_allowed()` | Plan-bootstrap gating; takes the bool. |
| `_LOOP_CONTINUATION_GUIDE` | System-prompt section; middleware injects when `state["continue_loop_mode"]` is `True`. |
| `seed_loop_ledger_from_prior_goal()` | Already runs unconditionally for any same-loop new goal. |

---

## 9. Migration and Compatibility

This is a clean cut. No backward-compatibility shims are introduced.

- **`StrangeLoopCheckpoint.status`** rename: persisted rows that hold the legacy literal `"ready_for_next_goal"` will fail Pydantic validation on load. Operators MUST start a fresh checkpoint (`/clear` mints a new `loop_id`) or migrate offline. The validator set `_STRANGE_LOOP_CHECKPOINT_STATUSES` lists only the new vocabulary.
- **`GoalExecutionRecord`** new fields default to `None` / empty collection — old rows that lack the `extras_jsonb` column deserialize to empty enrichment; this is field-default behavior, not a compat shim.
- **External clients** sending `intent_hint=continue_thread` / `new_goal`: `parse_intent_hint()` already returns `None` with a `logger.warning` on unknown values, so the daemon protocol degrades to "no hint" — but the values are no longer documented as supported.
- **`schema_version`** bump `"3.1"` → `"3.2"` is informational metadata.

---

## 10. Examples

### 10.1 First Query in a Fresh Loop

```
User: /clear
TUI: mints fresh loop_id = L1
User: "list large files in repo"
Runner:
  classify_intent("list large files...") → IntentClassification(intent_type="agentic", ...)
StrangeLoop.run_with_progress(loop_id=L1):
  checkpoint = state_manager.load()           # None
  continue_loop_mode = False                  # no checkpoint, no history
  state.intent = IntentClassification(...)    # no continue_thread field anywhere
  LoopRuntimeContext.continue_loop_mode = False
  Plan → Execute → goal completes
  checkpoint.status = "idle"
  goal_history = [GoalExecutionRecord(current_plan=…, step_results=[…], …)]
```

### 10.2 Second Query in the Same Loop

```
User (same loop L1): "summarize them"
Runner:
  classify_intent("summarize them") → IntentClassification(intent_type="agentic", ...)
StrangeLoop.run_with_progress(loop_id=L1):
  checkpoint = state_manager.load()
  # checkpoint.status == "idle", goal_history >= 1
  continue_loop_mode = True
  LoopRuntimeContext.continue_loop_mode = True
  Executor injects state["continue_loop_mode"] = True
  Middleware: _LOOP_CONTINUATION_GUIDE selected
  plan_assess: continue_loop_plan_bootstrap_allowed() honored
  seed_loop_ledger_from_prior_goal() seeds the new goal from prior GoalExecutionRecord.loop_messages
```

---

## 11. Relationship to Other RFCs

- **RFC-201 (Agentic Goal Execution Loop)** — This RFC tightens the runtime model of intent and continuation; the plan / execute control flow defined by RFC-201 is unchanged.
- **RFC-214 (StrangeLoop Loop-Message Surface)** — `loop_messages` semantics in `GoalExecutionRecord` are preserved; this RFC adds adjacent fields (plan, step_results, evidence_ledger).
- **RFC-216 (StrangeLoop Multi-Thread Lifecycle)** — Status vocabulary inherited from RFC-216 is updated (`ready_for_next_goal` → `idle`). The `loop_id`-centric continuity contract is reaffirmed.
- **RFC-217 (Goal Context Management)** — Unchanged. `thread_switch_pending` and `GoalContextManager` continue to operate as specified.
- **RFC-218 (StrangeLoop Checkpoint Tree Architecture)** — Schema layout follows RFC-218 conventions; the schema bump to `3.2` is recorded here.
- **RFC-220 (LangGraph StrangeLoop Orchestrator)** — The Plan / Execute orchestration nodes consume the new `continue_loop_mode` state key; node graph topology is unchanged.
- **RFC-222 (Autopilot Goal Engine Architecture)** — Out of scope; autopilot's `GoalEngine` usage is unaffected. This RFC only removes a broken solo-mode consumer of `GoalEngine` inside the agentic runner.
- **RFC-223 (Thread Inheritance with Checkpoint Forking)** — Authoritative for the LangChain thread model. This RFC reaffirms the boundary between StrangeLoop checkpoint and LangChain checkpointer.
- **RFC-224 (Automatic Context Window Management)** — Independent; context-window policies operate per LangChain thread and are unaffected by this RFC.

---

## 12. Open Questions

1. **`step_results` size cap.** Long-running multi-iteration goals may accumulate many step results. A configurable cap (e.g., `loop.checkpoint.max_step_results_per_goal`) is a future config knob.
2. **Plan revision audit.** `plan_revision_count` is a monotonic counter; revision content is only available via the event stream. If audit demands grow, a compact `list[PlanRevisionSummary]` MAY be added without breaking the flat layout.
3. **Cross-goal evidence reuse.** With `evidence_ledger` now per-goal-durable, a follow-up RFC could surface prior-goal evidence to the planner directly (today, only the orchestration ledger crosses goal boundaries via `seed_loop_ledger_from_prior_goal()`).

---

## 13. Conclusion

A loop is a conversation. Within one loop, every agentic query is, by structure, a continuation of the loop's prior work; only loop boundaries reset goal context. Pushing this truth out of the intent classifier and into the checkpoint removes a class of broken indirection (solo-mode `GoalEngine` reads), eliminates dead state (`LoopState.continue_thread`), and aligns the source vocabulary (`continue_loop_mode`, `idle`) with the design. Enriching the per-goal record to carry the plan DAG, step results, and evidence makes the StrangeLoop checkpoint the canonical orchestration log — durable, recoverable, and inspectable — while leaving the LangChain checkpointer's message-level ownership undisturbed.

> Classify intent. Derive continuity. Persist the orchestration. Let the checkpointer keep the conversation.
