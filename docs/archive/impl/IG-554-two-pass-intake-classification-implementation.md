# IG-554: Two-Pass Intake Classification Implementation

**Created**: 2026-07-06
**Status**: Draft
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-540](IG-540-intent-classify-prompt-ledger-optimization.md)

---

## Executive Summary

Implement RFC-630's two-pass intake architecture that separates social/task classification (Pass 1) from scope classification (Pass 2). This resolves the systemic blind spot where acknowledgment+pivot phrasing misroutes to `chitchat` fast-path.

| Pass | Decision | Context | Prompt size |
|------|----------|---------|-------------|
| Pass 1 | Social vs task | GOAL only | ~120 tokens |
| Pass 2 | Scope (trivial/simple/complex) | GOAL + prior projection | ~100 tokens |

---

## Scope

### In Scope

- `IntakePass1Classifier` class with compact prompt
- `IntakePass2Classifier` class with 3-label scope prompt
- Two-stage pre-graph gather in `_run_strange_loop`
- Routing guard (P0 hard constraint: block social if `new_goal_created`)
- Derived fields: `intake_label`, `has_deliverable`
- Unit tests for pivot patterns, scope golden-set, routing guard
- Integration tests for branch routing

### Out of Scope

- Wire protocol changes
- Fine-tuning pipeline
- Checkpoint/goal_history fixes (separate IG)

---

## Implementation Phases

### Phase A: Pass 1 Classifier

**Files to create/modify:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/intention/pass1_classifier.py` | Create |
| `packages/soothe/src/soothe/foundation/sloop/intention/models.py` | Add `IntakePass1Result` schema |
| `packages/soothe/src/soothe/foundation/sloop/prompts/fragments/classifiers/intake_pass1_system.xml` | Create prompt file |

**`IntakePass1Result` schema:**

```python
class IntakePass1Result(TypedDict):
    is_task: bool
    confidence: Literal["high", "medium", "low"]
    social_response: str | None  # required when is_task=False
    reasoning: str  # ≤15 words
```

**Pass 1 classifier implementation:**

```python
class IntakePass1Classifier:
    """Binary social vs task classification."""

    def __init__(self, model: BaseChatModel):
        self._model = model.with_structured_output(IntakePass1Result)

    async def classify(self, query: str) -> IntakePass1Result:
        prompt = INTAKE_PASS1_PROMPT  # from xml fragment
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=query),
        ]
        try:
            result = await self._model.ainvoke(messages)
            return result
        except Exception:
            # Fail-safe: treat as task
            return IntakePass1Result(
                is_task=True,
                confidence="low",
                social_response=None,
                reasoning="LLM error, fail-safe to task",
            )
```

**Unit tests:**

```python
# tests/unit/intention/test_pass1_classifier.py

@pytest.mark.parametrize("query,expected_is_task", [
    ("hi", False),
    ("thanks!", False),
    ("who are you", False),
    ("ok", False),  # standalone acknowledgment
    ("ok, now apply the fix", True),  # pivot pattern
    ("about the refactor — finish it", True),
    ("alright, so the tests...", True),
    ("perfect. next: auth middleware", True),
    ("fix the bug in auth.py", True),
])
async def test_pass1_pivot_patterns(query, expected_is_task):
    result = await classifier.classify(query)
    assert result["is_task"] == expected_is_task
```

---

### Phase B: Pass 2 Classifier

**Files to create/modify:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/intention/pass2_classifier.py` | Create |
| `packages/soothe/src/soothe/foundation/sloop/intention/models.py` | Add `IntakePass2Result` schema |
| `packages/soothe/src/soothe/foundation/sloop/prompts/fragments/classifiers/intake_pass2_system.xml` | Create prompt file |

**`IntakePass2Result` schema:**

```python
class IntakePass2Result(TypedDict):
    scope: Literal["trivial", "simple", "complex"]
    goal_description: str
    reasoning: str  # ≤15 words
```

**Pass 2 classifier implementation:**

```python
class IntakePass2Classifier:
    """Scope classification for work requests."""

    def __init__(self, model: BaseChatModel):
        self._model = model.with_structured_output(IntakePass2Result)

    async def classify(
        self,
        query: str,
        prior_projection: str | None,
    ) -> IntakePass2Result:
        prompt = INTAKE_PASS2_PROMPT
        messages = [
            SystemMessage(content=prompt),
        ]
        if prior_projection:
            messages.append(
                SystemMessage(content=f"PRIOR_GOAL_SUMMARY:\n{prior_projection}")
            )
        messages.append(
            HumanMessage(content=f"CURRENT_GOAL: {query}\nTASK: classify scope only")
        )

        try:
            result = await self._model.ainvoke(messages)
            return result
        except Exception:
            # Fail-safe: complex
            return IntakePass2Result(
                scope="complex",
                goal_description=query,
                reasoning="LLM error, fail-safe to complex",
            )
```

**Unit tests:**

```python
# tests/unit/intention/test_pass2_classifier.py

@pytest.mark.parametrize("query,expected_scope", [
    ("list the files in src/", "trivial"),
    ("what is the capital of France", "trivial"),
    ("fix the type error in auth.py", "simple"),
    ("add tests for the new API endpoint", "simple"),
    ("refactor SessionStore across all callers", "complex"),
    ("migrate the auth system to OAuth2", "complex"),
])
async def test_pass2_scope_classification(query, expected_scope):
    result = await classifier.classify(query, prior_projection=None)
    assert result["scope"] == expected_scope
```

---

### Phase C: Pre-Graph Gather Restructure

**Files to modify:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/engine/strange_loop.py` | Add `new_goal_created` to loop state |
| `packages/soothe/src/soothe/foundation/sloop/runner/_runner_strange_loop.py` | Two-stage gather with Pass 1/2 |

**Stage 1 gather:**

```python
# _runner_strange_loop.py

async def _run_strange_loop(...):
    # Stage 1: Pass 1 ∥ checkpoint ∥ git_status
    pass1_task = asyncio.create_task(pass1_classifier.classify(query))
    checkpoint_task = asyncio.create_task(state_manager.load())
    git_task = asyncio.create_task(get_git_status())

    pass1_result, checkpoint, git_status = await asyncio.gather(
        pass1_task, checkpoint_task, git_task, return_exceptions=True
    )

    # Handle Pass 1 result
    if isinstance(pass1_result, Exception):
        pass1_result = IntakePass1Result(is_task=True, ...)  # fail-safe

    if not pass1_result["is_task"]:
        # Social fast-path: emit response and END
        await emit_social_response(pass1_result["social_response"])
        return  # END

    # Stage 2: Pass 2 ∥ CE load ∥ file reads
    prior_projection = project_last_goal_completion_for_intake(checkpoint)
    pass2_task = asyncio.create_task(
        pass2_classifier.classify(query, prior_projection)
    )
    ce_task = asyncio.create_task(ce_backend.load())
    file_reads_task = asyncio.to_thread(load_instructions_and_memory)

    pass2_result, ce_state, instructions = await asyncio.gather(
        pass2_task, ce_task, file_reads_task, return_exceptions=True
    )

    # Handle Pass 2 result
    if isinstance(pass2_result, Exception):
        pass2_result = IntakePass2Result(scope="complex", ...)  # fail-safe

    # Derive intake_label
    intake_label = pass2_result["scope"]  # since is_task=True

    # Set loop state
    loop_state.new_goal_created = (checkpoint is None or checkpoint.goal_history == [])
    loop_state.intake_label = intake_label
    ...
```

---

### Phase D: Routing Guard

**Files to modify:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/engine/routing.py` | Add guard to `route_by_intent` |

**Routing guard implementation:**

```python
# routing.py

def route_by_intent(state: LoopGraphState, ctx: LoopRuntimeContext) -> str:
    """Dispatch after init_or_resume, with routing guard."""

    intake_label = state.get("intake_label", "complex")
    new_goal_created = ctx.loop_state.new_goal_created

    # P0 hard constraint: block social-path if new goal created
    if new_goal_created and intake_label == "chitchat":
        logger.warning(
            "intake_label chitchat blocked by new_goal_created constraint; "
            "forcing complex route"
        )
        intake_label = "complex"

    # Check continuation overlay first
    if ctx.continue_loop_mode:
        return "plan_assess"  # RFC-226 overlay

    # Branch dispatch
    if intake_label == "chitchat":
        return END
    elif intake_label == "trivial":
        return "resolve_decision"
    elif intake_label == "simple":
        return "plan_generate"
    elif intake_label == "complex":
        return "bounded_evidence_gather"
    else:
        return "bounded_evidence_gather"  # fail-safe
```

**Unit tests:**

```python
# tests/unit/engine/test_routing.py

def test_routing_guard_blocks_chitchat_on_new_goal():
    state = LoopGraphState(intake_label="chitchat")
    ctx = LoopRuntimeContext(loop_state=LoopState(new_goal_created=True))

    result = route_by_intent(state, ctx)
    assert result == "bounded_evidence_gather"  # forced complex

def test_routing_guard_allows_chitchat_on_idle_loop():
    state = LoopGraphState(intake_label="chitchat")
    ctx = LoopRuntimeContext(loop_state=LoopState(new_goal_created=False))

    result = route_by_intent(state, ctx)
    assert result == END
```

---

### Phase E: Legacy Removal

**Files to delete:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/intention/classifier.py` | Remove `_is_likely_agentic` and `classify_intent` |
| `packages/soothe/src/soothe/foundation/sloop/planning/simple_bypass.py` | Delete file (prefix detector removed) |
| `packages/soothe/src/soothe/foundation/sloop/prompts/fragments/classifiers/intake_classification_system.xml` | Update or replace |

**Schema changes:**

| Schema | Change |
|--------|--------|
| `IntentClassificationLLMResult` | Remove (replaced by Pass 1 + Pass 2 results) |
| `IntakeLabel` enum | Keep for routing compatibility |

---

### Phase F: Integration Tests

**Files to create:**

| File | Action |
|------|--------|
| `tests/integration/test_two_pass_intake.py` | Create |

**Test fixtures:**

```python
@pytest.mark.asyncio
async def test_two_pass_branch_routing_trivial():
    """Trivial goal skips plan_generate."""
    result = await run_strange_loop("list files in src/")
    assert result.visited_nodes == ["init_or_resume", "resolve_decision", "validate", "execute"]

@pytest.mark.asyncio
async def test_two_pass_branch_routing_complex():
    """Complex goal runs full spine."""
    result = await run_strange_loop("refactor SessionStore across all callers")
    assert "bounded_evidence_gather" in result.visited_nodes
    assert "plan_generate" in result.visited_nodes

@pytest.mark.asyncio
async def test_pivot_pattern_not_chitchat():
    """Acknowledgment+pivot routes to task, not chitchat."""
    result = await run_strange_loop("ok, now apply the signature change")
    assert result.intake_label != "chitchat"
    assert "plan_generate" in result.visited_nodes or "resolve_decision" in result.visited_nodes

@pytest.mark.asyncio
async def test_social_fast_path():
    """Pure greeting ends immediately."""
    result = await run_strange_loop("hi there!")
    assert result.intake_label == "chitchat"
    assert result.social_response is not None
```

---

## Migration Checklist

1. **Create Pass 1 classifier** — prompt, schema, class
2. **Create Pass 2 classifier** — prompt, schema, class
3. **Restructure pre-graph gather** — two-stage with Pass 1 ∥ checkpoint ∥ git
4. **Add routing guard** — P0 hard constraint in `route_by_intent`
5. **Update `init_or_resume`** — derive `intake_label`, inject trivial plan
6. **Remove legacy** — `_is_likely_agentic`, `simple_bypass`, old intake prompt
7. **Unit tests** — Pass 1 pivot patterns, Pass 2 scope, routing guard
8. **Integration tests** — branch routing, social fast-path
9. **Run `./scripts/verify_finally.sh`**

---

## Verification

| Check | Command |
|-------|---------|
| Lint | `make lint` |
| Unit tests | `pytest packages/soothe/tests/unit/intention/` |
| Integration tests | `pytest tests/integration/test_two_pass_intake.py` |
| Full verify | `./scripts/verify_finally.sh` |

---

## Latency Benchmarks

Measure before/after on:

| Query type | Baseline (one-pass) | Target (two-pass) |
|------------|--------------------|--------------------|
| Social (`"hi"`) | ~100ms | ~100ms (unchanged) |
| Task trivial | ~150ms | ~250ms (+100ms) |
| Task complex | ~200ms (intake only) | ~350ms (+150ms) |

Target: <200ms added on task queries (median).

---

## References

- [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md)
- [IG-540](IG-540-intent-classify-prompt-ledger-optimization.md) — prior projection
- `packages/soothe/src/soothe/foundation/sloop/intention/classifier.py` (legacy, to be replaced)
- `packages/soothe/src/soothe/foundation/sloop/prompts/plan_ledger_projection.py`