# IG-463: Veritas auto-mode robustness

**RFC**: [RFC-623](../specs/RFC-623-veritas-auto-mode-robustness.md)
**Lineage**: [IG-460](IG-460-clarification-relay.md) introduced the relay scaffolding (policy protocol, `await_clarification` node, veritas subagent). [IG-462](IG-462-wire-auto-clarification-end-to-end.md) wired the relay end-to-end. IG-463 hardens auto mode against malformed structured-output responses from thinking models.
**Status**: Draft

---

## 1. Motivation

Loop `019e8c08-3ce2-7b11-a17d-679c0fa0090c` (loop 090c) ran in auto mode against goal *"refine soothe-daemon code structure and ask for my confirm for each package..."* On iteration 4, the planner emitted an `ask_user` step (`HCW-08`) with two questions. The veritas LLM call ran for ~22 seconds and returned:

```json
{"answers": [], "confidence": 0.0, "defer": false, "rationale": ""}
```

`VeritasAnswerSchema`'s defaults (`answers: list[str] = Field(default_factory=list)`, `confidence: float = 0.0`) accepted this. The post-hoc `len(result.answers) != len(request.questions)` guard at `subagents/veritas/implementation.py:60-66` coerced to `defer=True`. `AutoClarificationPolicy.answer` raised `ClarificationDeferredError`. `await_clarification` marked the goal `awaiting_clarification` and routed the loop to `END`. The goal blocked.

Commit `d6f41f07` introduced `utils/llm/structured_invoke.py:invoke_structured_chat` — a robust structured-output wrapper that iterates `with_structured_output` methods, injects the `json` keyword, and post-validates with `jsonschema`. `IntentClassifier` and `LLMPlanner` were migrated to it; **veritas was not**. The veritas role is `think` → `coding-plan:glm-5`, exactly the class of thinking model the helper was built for.

`VeritasAnswerSchema` itself permits empty-but-not-deferred responses to pass type validation — there is no Pydantic-level constraint that ties `answers` length to the request. The contract is enforced only by the post-hoc Python guard.

This guide closes both gaps: migrate veritas onto `invoke_structured_chat`, replace the post-hoc guard with a per-request JSON Schema (`oneOf` between defer and exactly N non-empty answers), tag every defer with a `DeferKind`, and let `AutoClarificationPolicy` fall back to the interactive (TUI) relay when veritas itself fails — but only when a human is wired (no behavior change for autopilot).

---

## 2. Changes by slice

### Slice A — veritas runtime + dynamic schema

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/subagents/veritas/schemas.py` | Add `build_veritas_response_schema(question_count: int) -> dict[str, Any]` returning the per-request JSON Schema with `oneOf` between *defer* and *exactly N non-empty answers* (`minItems = maxItems = N`, `items.minLength = 1`, `rationale.minLength = 1`). `VeritasAnswerSchema` Pydantic class is **unchanged** — still the typed in-process representation. |
| `packages/soothe/src/soothe/subagents/veritas/implementation.py` | Rewrite `answer()` to call `invoke_structured_chat(model, messages, json_schema=schema, schema_name="VeritasAnswer", strict=True)`. On `StructuredOutputError` log `WARNING` and return `VeritasAnswerSchema(defer=True, confidence=0.0, rationale=f"structured_output_failed: {exc}", answers=[])`. Drop the post-hoc count-mismatch check (schema enforces it). Keep the `?`-suffix coercion but write `rationale="answer_was_question"` so the policy can classify it. Drop the `_any_answer_is_a_question` import sequence reorganization is local. |
| `packages/soothe/src/soothe/subagents/veritas/__init__.py` | Re-export `build_veritas_response_schema` (so it can be unit-tested directly). |

### Slice B — defer kind taxonomy

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/core/loop/clarification/protocol.py` | Add `DeferKind = Literal["explicit", "low_confidence", "structured_output_failed", "answer_was_question"]`. Add `kind: DeferKind = "explicit"` keyword-only parameter to `ClarificationDeferredError.__init__` and store on the instance. Backward-compatible: existing call sites that omit `kind` get `"explicit"`. |
| `packages/soothe/src/soothe/core/loop/clarification/__init__.py` | Re-export `DeferKind`. |
| `packages/soothe/src/soothe/core/loop/clarification/auto.py` | `AutoClarificationPolicy.__init__` gains `interactive_fallback: ClarificationPolicy \| None = None`. Replace inline defer logic with `self._classify(result) -> DeferKind \| None` that maps: `result.defer` + rationale prefix `"structured_output_failed"` → `"structured_output_failed"`; `result.defer` + rationale `"answer_was_question"` → `"answer_was_question"`; `result.defer` (other) → `"explicit"`; `result.confidence < self._min_confidence` → `"low_confidence"`; otherwise `None`. When `kind == "structured_output_failed" and self._interactive_fallback is not None`, log `WARNING` and `await self._interactive_fallback.answer(request)`. Otherwise raise `ClarificationDeferredError(reason, request, kind=kind)`. The `reason` string preserves today's wording (`f"veritas explicit defer (confidence={...})"`, `f"veritas low confidence ({...} < {...})"`); add a new `"veritas structured output failed: ..."` and `"veritas answer was a question"` for the new kinds. |
| `packages/soothe/src/soothe/core/loop/clarification/interactive.py` | When raising `ClarificationDeferredError` for "operator dismissed clarification", pass `kind="explicit"` (verbose) to make intent explicit; functionally a no-op since `"explicit"` is the default. |

### Slice C — runtime wiring & event payload

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/core/loop/clarification/selector.py` | `build_default_clarification_policy` gains `interactive_fallback: ClarificationPolicy \| None = None` keyword-only argument; forwarded into `AutoClarificationPolicy(...)` for `mode="auto"`. Manual mode ignores it. |
| `packages/soothe/src/soothe/core/loop/clarification/runtime_factory.py` | `build_clarification_policy_for_runner` gains `emit: EmitFn \| None = None` keyword-only argument. When `resolved_mode == "auto"` and `emit is not None`, build `interactive_fallback = InteractiveClarificationPolicy(emit=emit)`; otherwise leave it `None`. Pass through to `build_default_clarification_policy`. Manual mode keeps today's behavior (it can already accept `emit`). |
| `packages/soothe/src/soothe/core/runner/_runner_agentic.py` | When calling `build_clarification_policy_for_runner(...)`, pass the same `emit` already in scope (currently used elsewhere in this runner). Interactive runs gain the fallback automatically. |
| `packages/soothe/src/soothe/core/runner/_runner_autopilot_worker.py` | Calls `build_clarification_policy_for_runner(self._config, mode="auto")` — does **not** pass `emit`. Autopilot's `interactive_fallback` is therefore `None` (today's hard-defer behavior preserved). No code change required, but add a one-line comment noting this contract. |
| `packages/soothe/src/soothe/core/loop/orchestrator/nodes/await_clarification.py` | Bump line 85 (`policy deferred`) log severity from `INFO` to `WARNING`. Extend `LOOP_CLARIFICATION_DEFERRED` event payload with `defer_kind: exc.kind`. The "no policy configured" branch keeps today's payload (no `defer_kind`) — that path is system misconfiguration, not a veritas event. |

### Slice D — tests

| File | Change |
|------|--------|
| `packages/soothe/tests/unit/subagents/veritas/test_implementation.py` | New test file. Cases: (1) `happy_path_n_answers` — `invoke_structured_chat` returns N answers, confidence ≥ threshold → `VeritasAnswerSchema(defer=False, ...)`; (2) `explicit_defer` — returns `defer=True` directly; (3) `answer_was_question` — returns `answers=["foo?"]`, `defer=False` → coerced to `defer=True, rationale="answer_was_question"`; (4) `structured_output_failed` — `invoke_structured_chat` raises `StructuredOutputError` → returns `defer=True, rationale.startswith("structured_output_failed")`. Mock `invoke_structured_chat` via `unittest.mock.patch`. |
| `packages/soothe/tests/unit/subagents/veritas/test_schemas.py` | New test file. Cases: (1) `schema_for_n_questions` returns `oneOf` with `minItems == maxItems == n`; (2) JSON Schema rejects `defer=False` + empty `answers` (`jsonschema.validate` raises); (3) JSON Schema rejects `defer=False` + wrong-count answers; (4) JSON Schema accepts `defer=True` with no answers; (5) JSON Schema accepts `defer=False` with exactly N non-empty answers. |
| `packages/soothe/tests/unit/core/loop/clarification/test_auto.py` | Extend / add. Cases: (1) `kind_explicit` — veritas returns `defer=True` → policy raises with `kind="explicit"`; (2) `kind_low_confidence` — `defer=False, confidence=0.1` → raises with `kind="low_confidence"`; (3) `kind_answer_was_question` — `defer=True, rationale="answer_was_question"` → raises with `kind="answer_was_question"`; (4) `kind_structured_output_failed_no_fallback` — `defer=True, rationale="structured_output_failed: ..."`, `interactive_fallback=None` → raises with `kind="structured_output_failed"`; (5) `kind_structured_output_failed_with_fallback` — same input but fallback wired → fallback's `answer` is called; no error raised. |
| `packages/soothe/tests/unit/core/loop/clarification/test_runtime_factory.py` | Extend. Add cases: (a) auto mode + `emit=None` → returned `AutoClarificationPolicy._interactive_fallback is None`; (b) auto mode + `emit` provided → `_interactive_fallback` is a wired `InteractiveClarificationPolicy`. |
| `packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_await_clarification.py` | Extend. Verify `LOOP_CLARIFICATION_DEFERRED` event payload contains `defer_kind` matching `exc.kind` for each `DeferKind` value. |

---

## 3. Concrete signatures

```python
# subagents/veritas/schemas.py
def build_veritas_response_schema(question_count: int) -> dict[str, Any]: ...

# subagents/veritas/implementation.py
async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
) -> VeritasAnswerSchema: ...

# core/loop/clarification/protocol.py
DeferKind = Literal[
    "explicit",
    "low_confidence",
    "structured_output_failed",
    "answer_was_question",
]

class ClarificationDeferredError(Exception):
    def __init__(
        self,
        reason: str,
        request: ClarificationRequest,
        *,
        kind: DeferKind = "explicit",
    ) -> None: ...
    reason: str
    request: ClarificationRequest
    kind: DeferKind

# core/loop/clarification/auto.py
class AutoClarificationPolicy:
    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
    ) -> None: ...

# core/loop/clarification/runtime_factory.py
def build_clarification_policy_for_runner(
    config: SootheConfig,
    *,
    mode: str | None = None,
    emit: EmitFn | None = None,
) -> ClarificationPolicy: ...
```

---

## 4. Behavior matrix

| Scenario | Today (auto) | After IG-463 (auto, interactive) | After IG-463 (auto, autopilot) |
|---|---|---|---|
| Veritas returns N valid answers | continue | continue | continue |
| Veritas `defer=true` confidently | hard defer | hard defer, `defer_kind="explicit"` | hard defer, `defer_kind="explicit"` |
| Veritas confidence below threshold | hard defer | hard defer, `defer_kind="low_confidence"` | hard defer, `defer_kind="low_confidence"` |
| Answer ends in `?` | hard defer | hard defer, `defer_kind="answer_was_question"` | hard defer, `defer_kind="answer_was_question"` |
| Empty `answers=[]` + `defer=false` | post-hoc coerce → defer | schema rejects → fallback to TUI relay | schema rejects → hard defer, `defer_kind="structured_output_failed"` |
| Wrong-count answers | post-hoc coerce → defer | as above | as above |
| Malformed JSON | Pydantic raises uncaught | retries methods → fallback to TUI relay on full failure | retries methods → hard defer, `defer_kind="structured_output_failed"` |
| Provider error | bubbles uncaught | `StructuredOutputError` → fallback to TUI relay | `StructuredOutputError` → hard defer, `defer_kind="structured_output_failed"` |

---

## 5. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Thinking model rejects `oneOf` in JSON Schema | Medium | `invoke_structured_chat` already iterates four methods (`function_calling` → `None` → `json_schema` → `json_mode`) and post-validates; on full failure the existing fallback path (TUI relay or hard defer) absorbs it. |
| `interactive_fallback.answer()` calls LangGraph `interrupt(...)` from a context that didn't expect to pause | Low | Only triggered when `emit` is wired — that signals an interactive run, which already supports interrupts (manual mode uses the same path). Autopilot has `emit=None` and never reaches this branch. |
| Rationale-prefix discriminator for `defer_kind` becomes brittle | Low | Confined to `AutoClarificationPolicy._classify`. RFC-623 §8 documents a future migration to a typed `defer_kind` field on `VeritasAnswerSchema` if a fifth kind is needed. |
| New `kind` field on `ClarificationDeferredError` breaks existing handlers | Very low | Only `await_clarification.py:84` catches the error, and only reads `.reason`. `kind` defaults to `"explicit"` for legacy raise sites. |

---

## 6. Verification

1. `make format-check` — formatting passes
2. `make lint` — zero errors
3. `make test-unit` — 900+ tests pass plus the new unit tests in Slice D
4. `./scripts/verify_finally.sh` — full verification suite green
5. Manual smoke: run a goal that the planner is likely to ask about (e.g. `soothe "refine the daemon"`), watch for `soothe.subagent.veritas.requested` → `…answered` events with non-empty `answers`. If structured output happens to fail, verify the TUI surfaces a clarification prompt instead of the loop terminating silently.
