# IG-528: Start-Phase LLM Intake and Branch Routing

**Guide**: IG-528
**Title**: Start-Phase LLM Intake and Branch Routing
**Created**: 2026-06-30
**Related RFCs**: RFC-630
**Status**: Draft

## Summary

Implement RFC-630: replace the binary `IntentClassifier` LLM + its `_is_likely_agentic` heuristic bypass with a 4-class intake LLM (`quiz | trivial | simple | complex`), run that LLM `asyncio.gather`-ed with the pre-graph IO cluster to hide its latency, add a `route_by_intent` branch dispatch after `init_or_resume`, and add complexity-tiered planning so `trivial`/`simple` goals skip the full plan-generation LLM call. Delete the `simple_bypass` `"I will complete this goal directly:"` prefix. The 4-class intake is the sole intent path — the legacy binary classifier, its prompt fragments, and the heuristic are removed outright (no feature flag, no backward-compat shim).

## Background

Today's start-phase pipeline (`packages/soothe/src/soothe/foundation/loop/orchestrator/builder.py:56`) runs sequentially:

```
_run_strange_loop (intent LLM @ _runner_strange_loop.py:447)
  → StrangeLoop.run_with_progress (checkpoint load @ strange_loop.py:234, CE init, sync file reads @ :510-513)
    → graph: init_or_resume → iteration_gate → iteration_start
      → bounded_evidence_gather (fresh-loop skip, IG-476)
      → plan_assess | plan_generate (planner LLM @ planner.py:1297)
      → resolve_decision → validate_evidence_bindings → execute (CoreAgent)
```

Two problems (RFC-630 §3):

1. **Heuristic judgment.** `IntentClassifier._is_likely_agentic` (`classifier.py:260`) forces any query with `len>80` / `>15 words` / `≥2 newlines` to `agentic` *without* the LLM. `simple_bypass` (`simple_bypass.py:28`) recognizes a synthetic plan by `startswith("I will complete this goal directly:")`.
2. **Sequential latency.** On a fresh first message, the intent LLM, the pre-graph IO cluster (checkpoint load, CE load, sync instruction/memory file reads, git status), and the plan-generation LLM all run strictly sequentially. None parallelized.

The fresh-loop skip (IG-476) already removed the StatusAssessment LLM from the fresh path. RFC-630 removes the remaining blockers by parallelizing the intake LLM with the IO cluster and skipping phases for easy goals.

## Design

### Part 1: 4-Class Intake Schema (`models.py`)

Add `IntakeLabel` and replace `IntentClassificationLLMResult` with a 4-class intake schema. Reuse the existing `TaskComplexity` enum (`minimal | simple | medium | complex`) — no new complexity vocabulary.

**File**: `packages/soothe/src/soothe/foundation/loop/intention/models.py`

```python
class IntakeLabel(StrEnum):
    """4-class intake label (RFC-630). Continuation is NOT a label — it is a
    structural overlay from the checkpoint (RFC-225)."""
    QUIZ = "quiz"            # greeting/thanks/trivia, no tools
    TRIVIAL = "trivial"      # single obvious action, no planning LLM needed
    SIMPLE = "simple"        # single focused step, lightweight plan
    COMPLEX = "complex"      # multi-step / multi-phase, full plan


class IntakeClassificationLLMResult(BaseModel):
    """Structured output from the intake LLM (RFC-630).

    Replaces IntentClassificationLLMResult's binary quiz/agentic with a 4-class
    label. Quiz piggybacks the answer in quiz_response (preserves the quiz
    short-circuit). Non-quiz intents carry brief reasoning for client visibility.
    """
    intake_label: IntakeLabel = Field(
        description="Primary intake: quiz (greeting/thanks/trivia, no tools), "
        "trivial (single obvious action, no planning LLM), "
        "simple (single focused step, lightweight plan), "
        "complex (multi-step/multi-phase, full plan)"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief reasoning (one sentence, max 20 words). Empty for quiz.",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description (non-quiz).",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct answer for quiz intents. Concise, from training knowledge.",
    )

    def to_intent_classification(self) -> IntentClassification:
        """Convert to runtime IntentClassification (extended to carry intake_label)."""
        ...
```

Extend `IntentClassification` with an `intake_label: IntakeLabel` field (required). `intent_type` is derived from it (`quiz` → `quiz`, all others → `agentic`) so the quiz fast-path and `IntentClassifiedEvent` wire contract keep working.

### Part 2: Intake Classifier (`classifier.py`)

Replace `classify_intent` with `classify_intake`. Delete `_is_likely_agentic`. Keep the `intent_hint == QUIZ` bypass (structural caller assertion, not content) and the single-retry loop. **Fallback label is `complex`** (fail-safe = run the full pipeline).

**File**: `packages/soothe/src/soothe/foundation/loop/intention/classifier.py`

```python
async def classify_intake(
    self,
    query: str,
    *,
    observability_metadata: dict[str, str] | None = None,
    intent_hint: IntentHint | None = None,
) -> IntentClassification:
    """Classify the query into a 4-class intake label (RFC-630).

    - intent_hint=quiz short-circuits to quiz (caller assertion).
    - Otherwise: one structured LLM call with retry; fallback to complex.
    """
    if intent_hint == IntentHint.QUIZ:
        return self._build_quiz_intent()

    if not self._fast_model:
        return self._fallback_intent(query)  # label = complex

    result: IntentClassification | None = None
    last_error: Exception | None = None
    for retry_mode in (False, True):
        try:
            result = await self._classify_intake_llm(
                query, retry_mode=retry_mode,
                observability_metadata=observability_metadata,
            )
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Intake classification failed (%s), retrying...",
                           "retry" if retry_mode else "primary")

    if result is None:
        return self._fallback_intent(query, error_context=last_error)  # complex
    return self._patch_missing_fields(result, query)

def _fallback_intent(self, query, *, error_context=None) -> IntentClassification:
    """Safe fallback to complex (RFC-630 §9.3): run the full pipeline."""
    reason = type(error_context).__name__ if error_context else "classification_disabled"
    return IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        intent_type="agentic",
        reasoning=f"Classification fallback ({reason})",
        goal_description=query,
        task_complexity=TaskComplexity.COMPLEX,
        quiz_response=None,
    )
```

**Delete**: `_is_likely_agentic` (lines 260-269) and its call site (line 93).

### Part 3: Intake Prompt (XML fragment)

Replace the binary quiz/agentic prompt with a 4-class intake prompt. Lock the `trivial`/`simple`/`complex` boundary definitions (RFC-630 §15.3).

**Files**:
- `packages/soothe/src/soothe/foundation/loop/prompts/fragments/classifiers/intake_classification.xml` (new, replaces `intent_classification.xml`)
- `.../intake_classification_retry.xml` (new, replaces `intent_classification_retry.xml`)
- `packages/soothe/src/soothe/foundation/loop/intention/prompts.py` — load the new fragments (`INTAKE_CLASSIFICATION_PROMPT`, `INTAKE_CLASSIFICATION_RETRY_PROMPT`)

Boundary definitions (from RFC-630 §8.1, to be locked with the §14 golden set):

```xml
intake_label:
  "quiz"     — greeting/thanks/static trivia, no tools
  "trivial"  — one obvious tool call or direct answer, no decomposition
               (e.g. "what time is it?", "list files in this dir")
  "simple"   — a single focused step with light planning
               (e.g. "read RFC-220 and summarize the topology")
  "complex"  — multi-step, architectural, or multi-phase work
When uncertain, prefer "complex".
```

### Part 4: Parallelized Pre-Graph Gather (`_runner_strange_loop.py`, `strange_loop.py`)

Restructure the pre-graph sequence into a two-stage `asyncio.gather`. Stage split is a correctness constraint: CE construct + `create_goal`/`activate_goal` branch on the checkpoint result, so they cannot run in stage 1.

**File**: `packages/soothe/src/soothe/runner/_runner_strange_loop.py` (the `_run_strange_loop` body, starting around line 445)

```python
# Stage 1: independent — intake LLM ∥ checkpoint.load ∥ git_status
# (checkpoint.load happens inside run_with_progress today; refactor so the
#  runner can await it concurrently with the intake LLM and git_status.)
intake_task = self._intent_classifier.classify_intake(user_input, intent_hint=intent_hint) \
    if (self._intent_classifier and not clarification_answer) else _no_intake()
checkpoint_task = state_manager.load()
git_task = get_git_status(Path(workspace)) if workspace else _none()

intake_classification, checkpoint, git_status = await asyncio.gather(
    intake_task, checkpoint_task, git_task, return_exceptions=True,
)

# Stage 2: depends on checkpoint — CE construct+load ∥ instruction/memory file reads
# Wrap the three sync file reads (strange_loop.py:510-513) in to_thread and
# gather them with ce.load(). CE create_goal/activate_goal branch on checkpoint.status.
await _hydrate_ce_and_state(checkpoint, intake_classification, git_status, ...)
```

**File**: `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py`

- Wrap `load_project_instructions()`, `load_agent_instructions()`, `load_memory()` (lines 510-513) in `asyncio.to_thread(...)` and gather them with `await ce_instance.load()` (line 488).
- Refactor `run_with_progress` so checkpoint load is awaitable from the runner's gather (currently it's internal to `run_with_progress` at line 234). Either expose a `load_checkpoint()` coroutine or split `run_with_progress` so the runner orchestrates stages 1-2 and passes the hydrated state in. **Implementation choice**: expose `load_checkpoint()` and `hydrate_from_checkpoint(checkpoint, ...)` as separable methods on `StrangeLoop`; `run_with_progress` becomes the composer using the new split methods.

### Part 5: `route_by_intent` (`routing.py`, `builder.py`, `state.py`)

Add the `intake_label` state key and the `route_by_intent` conditional edge. Replace `route_after_init` (two-valued) with `route_by_intent` (multi-way). Continuation is checked first as a structural overlay.

**File**: `packages/soothe/src/soothe/foundation/loop/orchestrator/state.py`

```python
class LoopGraphState(TypedDict):
    # ... existing keys ...
    intake_label: IntakeLabel  # set by init_or_resume, read by route_by_intent
```

**File**: `packages/soothe/src/soothe/foundation/loop/orchestrator/routing.py`

```python
def route_by_intent(state: dict[str, Any], ctx: LoopRuntimeContext) -> str:
    """RFC-630: branch dispatch by intake label, with continuation overlay.

    Continuation is checked first from checkpoint state (structural), not the
    LLM label. Then matches the 4-class intake label.
    """
    # Structural continuation overlay (RFC-225/RFC-226)
    if ctx.continue_loop_mode and _has_prior_completed_goal(ctx):
        return "plan_assess"          # continuation branch (existing path)

    label = state.get("intake_label")
    if label == IntakeLabel.QUIZ:
        return END                    # quiz handled pre-graph; defensive duplicate
    if label == IntakeLabel.TRIVIAL:
        return "resolve_decision"     # synth plan injected in init_or_resume
    if label == IntakeLabel.SIMPLE:
        return "plan_generate"        # skip bounded_evidence_gather + plan_assess
    return "bounded_evidence_gather"  # complex: full existing spine
```

**File**: `packages/soothe/src/soothe/foundation/loop/orchestrator/builder.py` (line 117-122)

```python
graph.add_edge(START, "init_or_resume")
graph.add_conditional_edges(
    "init_or_resume",
    route_by_intent,
    {
        "bounded_evidence_gather": "bounded_evidence_gather",  # complex
        "plan_generate": "plan_generate",                      # simple
        "plan_assess": "plan_assess",                          # continuation
        "resolve_decision": "resolve_decision",                # trivial (synth in scratch)
        END: END,                                              # quiz
    },
)
```

All downstream conditional edges (`route_after_assess`, `route_after_plan`, `route_after_resolve_decision`, `route_after_validate_evidence`, `route_after_execute`) are unchanged. The `complex` branch's internals are unchanged.

### Part 6: `init_or_resume` Trivial-Branch Plan (`init_or_resume.py`)

For the `trivial` label, inject a minimal 1-step `PlanResult` into `ctx.scratch` so `resolve_decision` can ingest it. No synthetic reasoning prose; goal-as-step-action; `## Result` evidence contract retained.

**File**: `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/init_or_resume.py`

```python
async def node_init_or_resume(ctx, state):
    # ... existing intent surfacing + intent_classified event ...
    intake_label = ctx.loop_state.intent.intake_label
    state["intake_label"] = intake_label

    if intake_label == IntakeLabel.TRIVIAL:
        # Inject minimal 1-step plan; skip plan_generate entirely.
        try:
            ctx.scratch.plan_result = build_trivial_plan(
                goal=ctx.loop_state.intent.goal_description or ctx.loop_state.goal,
            )
            ctx.scratch.plan_assessment = _create_fresh_loop_assessment()  # synth assess
        except Exception:
            logger.exception("[init_or_resume] trivial plan build failed; downgrading to complex")
            state["intake_label"] = IntakeLabel.COMPLEX  # fall through to full spine
    return {"intake_label": intake_label}
```

**File**: `packages/soothe/src/soothe/foundation/loop/planning/trivial_plan.py` (new — extracts the `## Result` contract from `simple_bypass.py`)

```python
"""Trivial-branch plan builder (RFC-630 §11).

Goal-as-step-action, no synthetic reasoning prefix. The ## Result evidence
contract is retained from simple_bypass (functional, not cosmetic).
"""
from soothe.foundation.loop.planning.simple_bypass import SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT

def build_trivial_plan(goal: str) -> PlanResult:
    """Build a minimal 1-step plan: goal as the step action, no reasoning prose."""
    return PlanResult(
        status="execute",
        next_action=goal,                         # no prefix
        plan_reasoning=None,                      # no synthetic prose
        expected_output=SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
        steps=[...],  # single step
    )
```

### Part 7: Lightweight Plan (`phase.py`, `planner.py`)

Add `plan_phase.generate_lightweight(...)` for the `simple` branch — reuses `generate_from_assessment`'s structured-output path with a reduced context window.

**File**: `packages/soothe/src/soothe/foundation/loop/planning/phase.py`

```python
async def generate_lightweight(self, *, goal, state, context, plan_manager, context_engine):
    """Cheaper plan for the simple branch (RFC-630 §6.4).

    Same PlanGeneration schema, reduced context: last N step results, no full
    evidence ledger. Exact slots dropped — see Open Question 1 (§15.1).
    """
    # Reuse generate_from_assessment's structured-output path with a
    # stripped PlanContext (fewer history slots, no full ledger).
    ...
```

`node_plan_generate` reads `ctx.loop_state.intent.task_complexity`; when `simple` (and not the fresh-loop bypass), it calls `generate_lightwise` instead of `generate_from_assessment`.

### Part 8: No Feature Flag (direct replacement)

The 4-class intake is the sole intent path — there is no feature flag and no backward-compat shim. The runner always calls `classify_intake`; the graph always uses `route_by_intent`. The legacy binary `IntentClassificationLLMResult`, `classify_intent`, the binary prompt fragments, and `_is_likely_agentic` are removed in the same change.

No config changes are required for the intake itself (the `loop:` config block is unchanged). Config files are touched only by the pre-existing breakage fix (Part 9).

## Files Modified

| File | Changes |
|------|---------|
| `intention/models.py` | Add `IntakeLabel`; replace `IntentClassificationLLMResult` with 4-class `IntakeClassificationLLMResult`; extend `IntentClassification` with `intake_label` |
| `intention/classifier.py` | `classify_intake` replaces `classify_intent`; delete `_is_likely_agentic`; fallback label = `complex` |
| `intention/prompts.py` | Load `intake_classification.xml` / `intake_classification_retry.xml` |
| `prompts/fragments/classifiers/intake_classification.xml` | New 4-class prompt (replaces `intent_classification.xml`) |
| `prompts/fragments/classifiers/intake_classification_retry.xml` | New retry prompt (replaces `intent_classification_retry.xml`) |
| `runner/_runner_strange_loop.py` | Two-stage parallel pre-graph gather; always call `classify_intake` |
| `foundation/loop/engine/strange_loop.py` | Expose `load_checkpoint()` / `hydrate_from_checkpoint()`; wrap instruction/memory file reads in `to_thread`; gather with `ce.load()` |
| `orchestrator/state.py` | Add `intake_label` to `LoopGraphState` |
| `orchestrator/routing.py` | Add `route_by_intent`, replacing `route_after_init` |
| `orchestrator/builder.py` | `route_by_intent` conditional edge after `init_or_resume` (replaces `route_after_init`) |
| `orchestrator/nodes/init_or_resume.py` | Set `intake_label`; inject trivial-branch synth plan |
| `planning/trivial_plan.py` | New: `build_trivial_plan(goal)` (goal-as-step, `## Result` contract) |
| `planning/phase.py` | Add `generate_lightweight` for `simple` branch |
| `planning/simple_bypass.py` | Delete `SIMPLE_QUERY_DIRECT_PREFIX` + `is_simple_query_direct_next_action`; keep `SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT` (moved to `trivial_plan.py` usage) |
| `backends/memory/memu/memory/actions/base_action.py` | Pre-existing fix: add `from __future__ import annotations` (F821 `TimestampedMemoryItem`) |
| `foundation/loop/engine/executor.py` | Pre-existing fix: import sort (I001) |

## Testing

Per RFC-630 §14. Tests live in `packages/soothe/tests/unit/` and `tests/integration/`.

1. **Intake classifier unit tests** — golden-set queries per label, including the long-trivia case that today's heuristic misroutes. Assert the LLM is called for all queries (no heuristic bypass).
2. **Routing unit tests** — `route_by_intent` truth table over `(label, continue_loop_mode, has_prior_completed_goal)`.
3. **Parallelization tests** — assert intake, `checkpoint.load`, `git_status` run concurrently (mock with `asyncio.Event` latches); assert file reads go through `to_thread`.
4. **Branch integration tests** — one fixture per branch: assert the visited node sequence (e.g., `trivial` skips `plan_generate`; `simple` skips `bounded_evidence_gather` and `plan_assess`).
5. **Latency regression test** — timing-based with generous bounds, asserting a fresh `complex` first-message does not exceed today's p95 by more than gather overhead; skippable in CI if flaky.
6. **Mislabel recovery test** — force `trivial` on a multi-step goal; assert the loop replans on iteration 2 via `plan_assess`.

## Risks

- **Intake mislabel** — a `complex` goal mislabeled `trivial` produces a 1-step plan. Mitigation: the loop's existing post-execution `plan_assess` replans on the next iteration; the intake prompt errs toward `complex` when uncertain. The §14 golden set locks the boundary.
- **Pre-graph refactor ordering bugs** — splitting `run_with_progress` to expose `load_checkpoint()` risks breaking the continuation/clarification-resume paths (RFC-225/RFC-622). Mitigation: integration tests for continuation and clarification-resume must pass; the split methods are the sole path (no legacy fallback).
- **Latency regression** — if the gather overhead or the intake LLM round-trip exceeds the IO it overlaps, latency regresses for `complex` goals. Mitigation: the §14 latency regression test guards the p95.
- **Token cost** — the 4-class intake prompt is slightly larger than the binary prompt. Mitigation: reuse the IG-518 prompt-efficiency work (condensed rules, inline schema, examples in retry-only prompt).

## Verification

- [ ] `make lint` passes (ruff, zero errors)
- [ ] `./scripts/verify_finally.sh` passes (project rule)
- [ ] All 6 test groups above pass
- [ ] No legacy `classify_intent`/`IntentClassificationLLMResult`/`_is_likely_agentic` symbols remain
- [ ] Cross-references to RFC-630 in code comments/docstrings only (never user-visible strings — project terminology rule)
- [ ] No `IG-528`/`RFC-630` identifiers in logs, CLI output, errors, or config field descriptions

## Implementation Phases

### Phase A: Intake schema + classifier + prompt + legacy removal (no graph change)
**Goal**: 4-class intake LLM is the sole intent path; legacy binary classifier and heuristic removed.
- [x] Part 1 (models), Part 2 (classifier), Part 3 (prompt fragments), Part 8 (no flag — direct replacement)
- [x] Pre-existing breakage fix (base_action.py, executor.py)
- [x] Test group 1

### Phase B: Branch routing + trivial plan + lightweight plan (graph change)
**Goal**: `route_by_intent` dispatches to four branches; `trivial`/`simple` skip the right phases.
- [ ] Part 5 (routing/state/builder), Part 6 (init_or_resume + trivial_plan), Part 7 (generate_lightweight)
- [ ] Test groups 2, 4, 6

### Phase C: Parallelized pre-graph gather (runner/engine refactor)
**Goal**: intake LLM ∥ IO cluster; latency win on fresh messages.
- [ ] Part 4 (two-stage gather, to_thread file reads, expose load_checkpoint)
- [ ] Test groups 3, 5

### Phase D: Cleanup
**Goal**: remove dead `simple_bypass` code.
- [ ] Delete `SIMPLE_QUERY_DIRECT_PREFIX` + `is_simple_query_direct_next_action` (after Phase B trivial branch is wired)

## Open Questions (from RFC-630 §15)

1. **Lightweight plan context scope** — exactly which slots to drop for `simple`. Proposal: drop evidence-ledger history beyond last 2 step results, drop full prior-goal context. Confirm with planning-quality eval during Phase B.
2. **Intake boundary calibration** — lock `trivial`/`simple`/`complex` definitions with the §14 golden set before Phase B.

## Related Documents

- [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md) — Start-Phase LLM Intake and Branch Routing
- [RFC-225](../specs/RFC-225-loop-continuity-and-goal-record-enrichment.md) — intent taxonomy (extended)
- [RFC-220](../specs/RFC-220-langgraph-agent-loop-orchestrator.md) — orchestrator topology (revised)
- [RFC-226](../specs/RFC-226-continuation-aware-plan-assess.md) — continuation discriminator (preserved)
- Design draft: `docs/drafts/2026-06-30-start-phase-llm-intake-routing-design.md`
- Predecessor: IG-518 (intent-classify reasoning/perf — heuristic-bypass path superseded)
