# IG-445: Loop Continuity and Goal Record Enrichment

**RFC**: RFC-225
**Status**: Draft
**Created**: 2026-05-29
**Depends on**: RFC-201, RFC-214, RFC-216, RFC-218, RFC-220

---

## Goal

Implement RFC-225:

1. Collapse `IntentClassification.intent_type` to `Literal["quiz", "agentic"]`; drop `reuse_current_goal` and unused `IntentHint` values.
2. Remove the broken `GoalEngine.list_goals()` continuation check from the agentic runner.
3. Derive `continue_loop_mode` (renamed from `continue_thread_mode`) once in `AgentLoop` from the loaded checkpoint and propagate via `LoopRuntimeContext` + graph state.
4. Rename `AgentLoopCheckpoint.status` value `ready_for_next_goal` → `idle` with on-load coercion for legacy persisted values.
5. Enrich `GoalExecutionRecord` with `current_plan`, `step_results`, `evidence_ledger`, `completed_step_ids`, `plan_revision_count`; bump `schema_version` `"3.1"` → `"3.2"`.
6. Drop dead `LoopState.continue_thread` field and `intent_type` plumbing through graph state.
7. Rename `_THREAD_CONTINUATION_GUIDE` → `_LOOP_CONTINUATION_GUIDE`, `seed_continue_thread_ledger_from_prior_goal` → `seed_loop_ledger_from_prior_goal`, `continue_thread_plan_bootstrap_allowed` → `continue_loop_plan_bootstrap_allowed`.

---

## Files to Touch

| File | Action | Purpose |
|------|--------|---------|
| `packages/soothe/src/soothe/core/intention/models.py` | MODIFY | Collapse `IntentClassification.intent_type` Literal to `quiz|agentic`; drop `reuse_current_goal`; drop `IntentHint.CONTINUE_THREAD`/`NEW_GOAL`; simplify `to_intent_classification()` signature |
| `packages/soothe/src/soothe/core/intention/classifier.py` | MODIFY | Drop `continue_thread` parameter from `classify_intent()` + internal methods; remove `CONTINUE_THREAD`/`NEW_GOAL` hint branches; non-quiz → `"agentic"` |
| `packages/soothe/src/soothe/core/intention/prompts.py` | MODIFY | Docstring/comment cleanup; the structured-output schema already targets `quiz|agentic` |
| `packages/soothe/src/soothe/core/runner/_runner_agentic.py` | MODIFY | Delete `GoalEngine.list_goals()` block (lines 324-337); stop passing `continue_thread=` to classifier |
| `packages/soothe/src/soothe/core/loop/engine/agent_loop.py` | MODIFY | Derive `continue_loop_mode` from loaded checkpoint; drop intent-string check; remove `state.continue_thread =` write; update log line |
| `packages/soothe/src/soothe/core/loop/engine/executor.py` | MODIFY | `_execute_graph_input()` injects `continue_loop_mode` into graph state; remove `intent_type` plumbing + `_intent_type_for_prompt` helper |
| `packages/soothe/src/soothe/core/loop/engine/scenario_classifier.py` | MODIFY | Default `intent_type = "agentic"` (was `"new_goal"`); update prompt docstring |
| `packages/soothe/src/soothe/core/loop/orchestrator/nodes/plan_assess.py` | MODIFY | Rename `continue_thread_plan_bootstrap_allowed` → `continue_loop_plan_bootstrap_allowed`; rename `seed_continue_thread_ledger_from_prior_goal` → `seed_loop_ledger_from_prior_goal`; update docstrings to reference `continue_loop_mode` |
| `packages/soothe/src/soothe/core/loop/orchestrator/nodes/execute_steps.py` | MODIFY | `checkpoint.status = "idle"` (was `"ready_for_next_goal"`) |
| `packages/soothe/src/soothe/core/loop/orchestrator/nodes/max_iterations_terminal.py` | MODIFY | Same status rename |
| `packages/soothe/src/soothe/core/loop/orchestrator/runtime_context.py` | MODIFY | Rename field `continue_thread_mode` → `continue_loop_mode` |
| `packages/soothe/src/soothe/core/loop/state/schemas.py` | MODIFY | Drop `LoopState.continue_thread: bool` field |
| `packages/soothe/src/soothe/core/loop/state/checkpoint.py` | MODIFY | Enrich `GoalExecutionRecord` (5 new fields); rename status `ready_for_next_goal` → `idle` in `_AGENT_LOOP_CHECKPOINT_STATUSES` + Literal; extend `normalize_checkpoint_data()` to coerce legacy value; bump `schema_version = "3.2"` |
| `packages/soothe/src/soothe/core/loop/state/manager.py` | MODIFY | Status string rename (5 sites); persist + restore new `GoalExecutionRecord` fields in `goal_records` table |
| `packages/soothe/src/soothe/middleware/system_prompt_optimization.py` | MODIFY | Read `state["continue_loop_mode"]` bool; drop `intent_type` string scenario branches; pass bool to `_build_scenario_section()`; rename guide reference |
| `packages/soothe/src/soothe/core/prompts/system_templates.py` | MODIFY | Rename `_THREAD_CONTINUATION_GUIDE` → `_LOOP_CONTINUATION_GUIDE` |
| `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` | MODIFY | Docstring (line 314): standard intent_hint values reduced to `"quiz"` |
| `client/go/send_methods.go` | MODIFY | Comment-only update (line 118) |
| `packages/soothe/tests/unit/core/test_intent_classification.py` | REWRITE | Assert `"agentic"` for non-quiz; drop `reuse_current_goal`; drop `continue_thread` parameter usage |
| `packages/soothe/tests/unit/core/loop/engine/test_scenario_classifier.py` | MODIFY | `"new_goal"` → `"agentic"` |
| `packages/soothe/tests/unit/core/loop/orchestrator/test_init_or_resume_intent_fast_path.py` | MODIFY | Drop `reuse_current_goal` |
| `packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py` | MODIFY | Rename references (`continue_thread_mode` → `continue_loop_mode`); flag remains bool |
| `packages/soothe/tests/unit/core/loop/state/test_checkpoint_normalize.py` | MODIFY | `idle` status + new legacy coercion assertion |
| `packages/soothe/tests/unit/core/loop/state/test_checkpoint_index_fix.py` | MODIFY | `ready_for_next_goal` → `idle` |
| `packages/soothe/tests/unit/core/loop/core/test_agent_loop_adaptive_final.py` | MODIFY | `ready_for_next_goal` → `idle` |
| `packages/soothe/tests/unit/core/loop/engine/test_goal_context_manager.py` | MODIFY | `ready_for_next_goal` → `idle` |
| `packages/soothe/tests/unit/core/loop/state/test_goal_record_enrichment.py` | CREATE | Verify per-goal persist/restore of `current_plan`, `step_results`, `evidence_ledger`, `completed_step_ids`, `plan_revision_count` |

---

## Implementation Steps

### Step 1 — Checkpoint schema (state/checkpoint.py)

Update `_AGENT_LOOP_CHECKPOINT_STATUSES`, the `AgentLoopCheckpoint.status` Literal, and `GoalExecutionRecord`:

```python
# checkpoint.py
_AGENT_LOOP_CHECKPOINT_STATUSES = {"running", "idle", "finalized", "cancelled"}

class AgentLoopCheckpoint(BaseModel):
    ...
    status: Literal["running", "idle", "finalized", "cancelled"]
    ...
    schema_version: str = "3.2"

class GoalExecutionRecord(BaseModel):
    # Identity / Lifecycle (unchanged)
    goal_id: str
    goal_text: str
    thread_id: str
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    iteration: int = 0
    max_iterations: int = 10
    started_at: datetime
    completed_at: datetime | None = None

    # ─ Orchestration (NEW) ─
    current_plan: PlanResult | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    plan_revision_count: int = 0

    # ─ Execution (NEW) ─
    step_results: list[StepResult] = Field(default_factory=list)
    evidence_ledger: list[EvidenceEntry] = Field(default_factory=list)

    # Existing conversation ledger & output
    loop_messages: list[LoopHumanMessage | LoopAIMessage] = Field(default_factory=list)
    goal_completion: str = ""
    evidence_summary: str = ""
    duration_ms: int = 0
    tokens_used: int = 0
```

`PlanResult`, `StepResult`, `EvidenceEntry` are imported from `soothe.core.loop.state.schemas` (already in the package — they are runtime types, so import path must avoid the existing reverse-dependency between `checkpoint.py` and `schemas.py`; if circular, declare as forward refs and resolve via `model_rebuild()` at module bottom).

### Step 2 — Status validator only allows the new vocabulary

No legacy coercion. `_AGENT_LOOP_CHECKPOINT_STATUSES` lists only the post-rename literals. Persisted rows holding `"ready_for_next_goal"` will fail Pydantic validation on load — operators start a fresh `loop_id` (the common path: `/clear`).

### Step 3 — State manager renames + new field persistence (state/manager.py)

Update all 5 `ready_for_next_goal` references to `idle` (initialize() default, save-status setter, recovery branch comparison, log lines). For PostgreSQL `goal_records` table writes/reads, serialize / deserialize the new fields:

- Pydantic auto-handles `current_plan` (nested `PlanResult` JSONB), `step_results` (list of `StepResult`), `evidence_ledger` (list of `EvidenceEntry`), `completed_step_ids` (serialize as list, deserialize back to set), `plan_revision_count` (int).
- For SQLite path: same approach via Pydantic `model_dump()` / `model_validate()`.

### Step 4 — Intent models (intention/models.py)

```python
class IntentHint(StrEnum):
    QUIZ = "quiz"   # only remaining value

class IntentClassification(BaseModel):
    intent_type: Literal["quiz", "agentic"]
    goal_description: str | None = None
    task_complexity: TaskComplexity
    quiz_response: str | None = None
    # reuse_current_goal: REMOVED

class IntentClassificationLLMResult(BaseModel):
    intent_type: Literal["agentic", "quiz"]
    goal_description: str | None = None
    task_complexity: TaskComplexity
    quiz_response: str | None = None

    def to_intent_classification(self) -> IntentClassification:
        if self.intent_type == "quiz":
            return IntentClassification(
                intent_type="quiz",
                goal_description=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=self.quiz_response,
            )
        return IntentClassification(
            intent_type="agentic",
            goal_description=self.goal_description,
            task_complexity=self.task_complexity,
            quiz_response=None,
        )
```

### Step 5 — Classifier (intention/classifier.py)

- Drop `continue_thread: bool = False` parameter from `classify_intent`, `_classify_intent_llm`, `_build_intent_from_hint`, `_build_heuristic_agentic`, `_fallback_intent`.
- Remove `CONTINUE_THREAD`/`NEW_GOAL` branches from `_build_intent_from_hint`.
- All non-quiz paths construct `IntentClassification(intent_type="agentic", ...)`.
- Log line drops `reuse_goal=` field.

### Step 6 — Runner (runner/_runner_agentic.py)

Delete lines 324-337 (GoalEngine query). Call sites:

```python
intent_classification = await self._intent_classifier.classify_intent(
    user_input,
    intent_hint=intent_hint,
)
```

No `continue_thread=` kwarg. No goal-engine probe.

### Step 7 — Runtime context + AgentLoop (loop/orchestrator/runtime_context.py, loop/engine/agent_loop.py)

Rename `LoopRuntimeContext.continue_thread_mode` → `continue_loop_mode`.

In `AgentLoop.run_with_progress()`:

```python
checkpoint = await state_manager.load()

continue_loop_mode = (
    checkpoint is not None
    and len(checkpoint.goal_history) >= 1
    and checkpoint.status in ("running", "idle")
)

# ─ delete the old intent.intent_type == "continue_thread" block ─
# ─ delete `state.continue_thread = True` write ─
```

The derivation MUST happen before any branch that reassigns `checkpoint` (e.g., the `state_manager.initialize()` call in the `else` branch).

Update log line:

```python
logger.info(
    "[Goal] %s (max_iterations=%d, iteration=%d, continue_loop=%s)",
    log_preview(execution_goal, 80), max_iterations, state.iteration, continue_loop_mode,
)
```

Pass to `LoopRuntimeContext(continue_loop_mode=continue_loop_mode, ...)`.

### Step 8 — Executor (loop/engine/executor.py)

- Drop `_intent_type_for_prompt()` static method.
- Drop `intent_type` parameter from `_execute_graph_input()` and `_execute_step_collecting_events()` call chain.
- Add `continue_loop_mode: bool = False` parameter to `_execute_graph_input()`:

```python
@staticmethod
def _execute_graph_input(
    messages,
    *,
    routing_classification=None,
    workspace=None,
    git_status=None,
    continue_loop_mode: bool = False,
    synthesis_scenario: str | None = None,
) -> dict[str, Any]:
    out = {"messages": messages}
    if routing_classification is not None:
        out["routing_classification"] = routing_classification
    if workspace:
        out["workspace"] = workspace
    if git_status is not None:
        out["git_status"] = git_status
    if continue_loop_mode:
        out["continue_loop_mode"] = True
    if synthesis_scenario:
        out["synthesis_scenario"] = synthesis_scenario
    return out
```

At call sites use `getattr(state, "continue_loop", False)` reading from `LoopState` if a state field is reintroduced — but per the design, the executor reads from its `LoopRuntimeContext` via parameters passed in. Specifically, propagate the mode from `LoopRuntimeContext.continue_loop_mode` into the executor by passing through `loop_state` (add a transient attribute set by `agent_loop.py` for executor use) or via constructor injection. **Implementation choice**: add a transient `LoopState` attribute `continue_loop: bool = False` (NEW, replaces the dropped `continue_thread`); set it in `agent_loop.py` next to `LoopRuntimeContext` creation; executor reads `state.continue_loop`. This keeps a single read-only carrier across the per-request lifetime.

Update `schemas.py` accordingly: remove `continue_thread: bool` and add `continue_loop: bool = False`.

### Step 9 — Middleware (middleware/system_prompt_optimization.py)

```python
# in _get_dynamic_content (or wherever scenario_section is built):
continue_loop_mode = bool(state.get("continue_loop_mode"))
goal_type = ""
scen = (state.get("synthesis_scenario") or "").strip()
if scen == "code_architecture_design":
    goal_type = "architecture_analysis"
elif scen == "research_synthesis":
    goal_type = "research_synthesis"

if continue_loop_mode or goal_type:
    scenario_section = self._build_scenario_section(continue_loop_mode, goal_type)
    if scenario_section:
        semi_static_sections.append(scenario_section.strip())

def _build_scenario_section(
    self, continue_loop_mode: bool, goal_type: str
) -> str | None:
    from soothe.core.prompts.system_templates import (
        _ARCHITECTURE_ANALYSIS_GUIDE,
        _LOOP_CONTINUATION_GUIDE,
        _RESEARCH_SYNTHESIS_GUIDE,
        _QUIZ_RESPONSE_GUIDE,
    )
    # Quiz handled elsewhere (fast-path); guide here only for residual surfaces.
    if continue_loop_mode:
        return _LOOP_CONTINUATION_GUIDE
    if goal_type == "architecture_analysis":
        return _ARCHITECTURE_ANALYSIS_GUIDE
    if goal_type == "research_synthesis":
        return _RESEARCH_SYNTHESIS_GUIDE
    return None
```

Drop the `intent_type` extraction and the `intent_type == "quiz"` / `"continue_thread"` branches (the quiz fast-path in the runner handles quiz before reaching middleware; if any residual need exists, gate on `state.get("intent_type") == "quiz"` only).

### Step 10 — Plan-assess + ledger helpers (loop/orchestrator/nodes/plan_assess.py)

- Rename `continue_thread_plan_bootstrap_allowed(*, continue_thread_mode, ...)` → `continue_loop_plan_bootstrap_allowed(*, continue_loop_mode, ...)`.
- Rename `seed_continue_thread_ledger_from_prior_goal(...)` → `seed_loop_ledger_from_prior_goal(...)`.
- Update docstrings to reference `continue_loop_mode` / "loop continuation".
- Update call sites: `agent_loop.py` (`seed_loop_ledger_from_prior_goal(...)`), the bootstrap allowed check, etc.

### Step 11 — Templates (core/prompts/system_templates.py)

Rename `_THREAD_CONTINUATION_GUIDE` → `_LOOP_CONTINUATION_GUIDE`. Update body text where it mentions "thread continuation" → "loop continuation" for accuracy (low-risk wording cleanup).

### Step 12 — Persistence write back from LoopState to GoalExecutionRecord

Identify the goal-completion site (look in `state/manager.py` `save()` paths and `orchestrator/nodes/execute_steps.py` where `checkpoint.status = "idle"` is set). At that boundary, mirror:

```python
goal_record.current_plan = (
    loop_state.current_decision.plan_result
    if loop_state.current_decision is not None
    else None
)
goal_record.completed_step_ids = set(loop_state.completed_step_ids)
goal_record.step_results = list(loop_state.step_results)
goal_record.evidence_ledger = list(loop_state.evidence_ledger)
# plan_revision_count incremented separately on each new plan in plan_assess
```

`plan_revision_count` increment goes in `plan_assess` where `plan_action == "new"` produces a fresh `PlanResult` — increment `goal_record.plan_revision_count += 1` and persist via `state_manager.save(checkpoint)`.

### Step 13 — SDK / client doc touch-ups

`packages/soothe-sdk/src/soothe_sdk/client/websocket.py:314`:

```
intent_hint: Suggested intent. Standard value bypasses in-agent classification:
    ``quiz``. Daemon-only values ``direct_llm`` invoke a configured chat model directly
    (no Soothe agent graph). ...
```

`client/go/send_methods.go:118`: align the comment text to the Python docstring.

### Step 14 — Tests

Rewrite `tests/unit/core/test_intent_classification.py`:
- All agentic paths assert `intent.intent_type == "agentic"`.
- Drop `reuse_current_goal` assertions.
- Drop `continue_thread=True/False` parameters from classifier calls.
- Quiz path unchanged: assert `intent_type == "quiz"` and `quiz_response` populated.

`tests/unit/core/loop/engine/test_scenario_classifier.py`: change default `"new_goal"` → `"agentic"`.

`tests/unit/core/loop/orchestrator/test_init_or_resume_intent_fast_path.py`: drop `reuse_current_goal`.

`tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py`: rename to keep grep-discoverability but no behavior change; references updated to `continue_loop_mode` and renamed helpers.

`tests/unit/core/loop/state/test_checkpoint_normalize.py`: assert that a checkpoint with legacy `status="ready_for_next_goal"` loads as `status="idle"`.

`tests/unit/core/loop/state/test_checkpoint_index_fix.py`, `tests/unit/core/loop/core/test_agent_loop_adaptive_final.py`, `tests/unit/core/loop/engine/test_goal_context_manager.py`: simple string replace `ready_for_next_goal` → `idle`.

`tests/unit/core/loop/state/test_goal_record_enrichment.py` (NEW): construct an `AgentLoopCheckpoint` with one `GoalExecutionRecord`; populate `current_plan` (synthetic `PlanResult` with one `AgentDecision` and 2 `StepAction`s), `step_results` (2 `StepResult`s), `evidence_ledger` (1 `EvidenceEntry`), `completed_step_ids={"s1"}`, `plan_revision_count=3`; call `state_manager.save()` and `state_manager.load()`; assert round-trip equality.

---

## Test Plan

| Layer | Test | Purpose |
|---|---|---|
| Unit | `test_intent_classification.py` (rewritten) | LLM → `quiz | agentic` only; structural derivation no longer in classifier |
| Unit | `test_scenario_classifier.py` | Default intent_type literal aligned with new model |
| Unit | `test_plan_assess_continue_thread.py` | `continue_loop_plan_bootstrap_allowed` gating |
| Unit | `test_checkpoint_normalize.py` | Legacy `ready_for_next_goal` coercion → `idle` |
| Unit | `test_goal_record_enrichment.py` (NEW) | Persist + restore round-trip for new `GoalExecutionRecord` fields |
| Unit | `test_init_or_resume_intent_fast_path.py` | Quiz fast-path unchanged behaviorally |
| Integration | Solo-mode AgentLoop second-query test | `continue_loop_mode=True` flows into middleware and into prompt section |

---

## Verification

```bash
cd packages/soothe
python -m pytest tests/unit/core/test_intent_classification.py -v
python -m pytest tests/unit/core/loop/state/ -v
python -m pytest tests/unit/core/loop/ -v
python -m pytest tests/unit/ -x --timeout=60
python -m mypy src/soothe/core/intention/ src/soothe/core/loop/state/ --ignore-missing-imports
./scripts/verify_finally.sh
```

Manual:
1. `soothe` (fresh) → query "list files" → expect `continue_loop_mode=False` in DEBUG logs.
2. Same session, second query "explain them" → expect `continue_loop_mode=True`, `_LOOP_CONTINUATION_GUIDE` in semi-static prompt sections.
3. Inspect persisted checkpoint (SQLite via `sqlite3 ~/.soothe/state.db "SELECT data FROM checkpoints LIMIT 1"`) — confirm `status="idle"` for completed-then-paused loops, `current_plan` populated for completed goals.
4. Load a checkpoint that was written by pre-IG-445 code (status=`ready_for_next_goal`) — confirm it loads with `status="idle"` after normalization, no Pydantic errors.

---

## Migration / Compatibility

Clean cut. No backward-compat shims.

- **No DB migration step.** Old checkpoints with `status="ready_for_next_goal"` fail Pydantic validation on load. Operators start a fresh `loop_id` (the common path: `/clear`).
- **`goal_records.extras_jsonb` column** is added via the in-house `_ensure_goal_record_columns` migration; old rows have NULL in this column, which deserializes to empty enrichment fields (default Pydantic behavior, not a compat shim).
- **`intent_hint`** legacy values (`continue_thread`, `new_goal`) parse as unknown → returns `None` with a `logger.warning` (existing behavior). Removed from documentation and Go client comment.
- **Schema version** `3.1` → `3.2` is informational metadata only.

---

## Risks

| Risk | Mitigation |
|---|---|
| Circular import between `state/checkpoint.py` and `state/schemas.py` after pulling in `PlanResult`/`StepResult`/`EvidenceEntry` | Use forward references + `model_rebuild()` at module bottom, or relocate the shared types if circularity is unavoidable. |
| `step_results` checkpoint bloat over long goals | Out of scope for this IG; tracked as RFC-225 §12 open question (cap as future config knob). |
| Middleware regressions from dropping `intent_type` plumbing | Covered by integration test + manual verification step 2; `_LOOP_CONTINUATION_GUIDE` injection observable in prompt logs at DEBUG. |
| Test files referencing renamed symbols by string in commit messages or unrelated tests | Run `git grep` for `continue_thread_mode`, `ready_for_next_goal`, `seed_continue_thread`, `_THREAD_CONTINUATION_GUIDE` before final commit to catch stragglers. |
