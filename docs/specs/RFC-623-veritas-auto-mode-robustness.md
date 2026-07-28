# RFC-623: Veritas Auto-Mode Robustness

**RFC**: 623
**Title**: Veritas Auto-Mode Robustness
**Status**: Draft
**Kind**: Implementation Interface Design
**Created**: 2026-06-03
**Last Updated**: 2026-06-03
**Authors**: Soothe Team
**Depends on**: RFC-622 (CoreAgent Clarification Relay), RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-403 (Unified Event Naming)
**Supersedes**: ---

---

## 1. Abstract

The veritas auto-answerer introduced by RFC-622 calls `model.with_structured_output(...).ainvoke(...)` directly. Thinking-class models (e.g. `coding-plan:glm-5`) and providers requiring the literal `json` keyword in prompts return structurally-valid but empty `VeritasAnswerSchema` payloads, which a post-hoc count-mismatch guard then coerces to `defer=True`. Every false defer terminates the StrangeLoop and parks its goal in `awaiting_clarification` for up to seven days. RFC-623 makes auto-mode robust by migrating veritas onto the shared `invoke_structured_chat` helper, enforcing the *exactly N answers or defer* contract directly in JSON Schema, classifying defer kinds for operators, and falling back to the interactive (TUI) relay when veritas itself fails.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

- The runtime path veritas uses to invoke the underlying chat model (`invoke_structured_chat`).
- A dynamic per-request JSON Schema (`build_veritas_response_schema`) that makes "exactly N non-empty answers OR defer" structurally enforced.
- A `DeferKind` taxonomy attached to `ClarificationDeferredError` and the `LOOP_CLARIFICATION_DEFERRED` event payload.
- Optional fallback from `AutoClarificationPolicy` to `InteractiveClarificationPolicy` when, and only when, veritas itself fails (`structured_output_failed`).
- Log severity adjustments and the operational-visibility rules around clarification defers.

### 2.2 Non-Goals

This RFC does **not** redefine:

- The semantics of legitimate veritas defers (`explicit`, `low_confidence`, `answer_was_question`) — those remain hard defers as defined by RFC-622.
- The `ClarificationPolicy` protocol, the `await_clarification` graph node, or the `awaiting_clarification` goal-engine state.
- Per-request `clarification_mode` resolution (`auto`/`manual`/config default).
- Retries against the LLM (the structured-output helper retries methods, not full inference).
- Any change to the `VeritasAnswerSchema` Pydantic field set (added behavior is additive at the policy layer).
- Autopilot's contract that headless runs cannot relay to a human — autopilot's behavior on veritas failure is unchanged (hard defer).

---

## 3. Background & Motivation

### 3.1 Observed regression

Loop `019e8c08-3ce2-7b11-a17d-679c0fa0090c` (referred to in operator logs as loop 090c) executed in auto mode with the goal *"refine soothe-daemon code structure and ask for my confirm for each package..."* On iteration 4, the planner emitted an `ask_user` step (`HCW-08`) with two questions. The veritas LLM call ran for ~22 seconds and returned:

```json
{"answers": [], "confidence": 0.0, "defer": false, "rationale": ""}
```

The schema's defaults (`answers: list[str] = Field(default_factory=list)`, `confidence: float = 0.0`) accept this. Pydantic validation passed. The post-hoc `len(result.answers) != len(request.questions)` guard at `subagents/veritas/implementation.py:60-66` coerced the result to `defer=True, confidence=0.0`. `AutoClarificationPolicy.answer` raised `ClarificationDeferredError("veritas explicit defer (confidence=0.00)")`. The `await_clarification` node caught the error, marked the goal `awaiting_clarification`, and returned `last_outcome="deferred"`. The StrangeLoop terminated.

### 3.2 Why this is a regression worth fixing

Defer is a **terminal action**:

1. `await_clarification` returns `last_outcome="deferred"` → `routing.route_after_clarification` routes to `END`.
2. `GoalEngine.mark_awaiting_clarification` sets `goal.status = "awaiting_clarification"`, persists `pending_clarification` on the Goal, clears `assigned_loop_id`.
3. `awaiting_clarification` is in `BLOCKED_STATES` — the scheduler will not pick the goal up again on its own.
4. Resumption requires `GoalEngine.answer_clarification(goal_id, answers)` from a human relay (TUI / API), or expiry by autopilot's stale-clarification sweeper after `agent.clarification.max_defer_age_hours` (default 168h = 7 days).

The empty-answer payload was not veritas legitimately saying "I don't know." It was a malformed model response that should have been rejected at the structured-output boundary. Every false defer caused by such a glitch is a goal that did not need to block.

### 3.3 Root cause

Commit `d6f41f07` ("improve structured output compatibility for thinking models and DashScope") added `utils/llm/structured_invoke.py:invoke_structured_chat`, a robust structured-output wrapper that:

- Iterates structured-output methods (`function_calling` → `None` → `json_schema` → `json_mode`), caching the first that works per chat model.
- Injects the literal `json` keyword into prompts for providers (DashScope, OpenAI-compatible APIs) that require it with `json_object` mode.
- Post-validates parsed output against the JSON Schema with `jsonschema`.
- Raises `StructuredOutputError` on any failure, masking provider-specific exceptions.

`IntentClassifier` and `LLMPlanner` were migrated to this helper in the same commit. **Veritas was not.** Veritas still calls `model.with_structured_output(VeritasAnswerSchema).ainvoke(...)` directly. The veritas role is `think` → `coding-plan:glm-5`, which is exactly the class of thinking model the helper was built for.

`VeritasAnswerSchema` itself accepts empty-but-not-deferred responses — there is no Pydantic-level constraint that ties `answers` length to the request. The contract is enforced only by the post-hoc guard in `implementation.py`.

---

## 4. Design Principles

1. **Structural enforcement over post-hoc coercion.** A constraint the model sees up front via JSON Schema beats a post-parse Python guard.
2. **Reuse the shared structured-output helper.** Veritas is one of three LLM-driven structured-output callers in soothe; they should share `invoke_structured_chat` so model-compatibility fixes land for all of them at once.
3. **Distinguish system failure from policy decision.** "Veritas was broken" and "veritas legitimately doesn't know" produce the same hard defer today; operators need to tell them apart.
4. **Headless contracts are preserved.** Autopilot has no human at the other end; its behavior on veritas failure must remain a clean hard defer. Only interactive runs may fall back to a TUI prompt.
5. **Backward compatibility on the public surface.** `VeritasAnswerSchema` field set, `ClarificationPolicy` protocol, `await_clarification` node, and goal-engine states are unchanged. New behaviors are additive.

---

## 5. Specification

### 5.1 Veritas runtime: `invoke_structured_chat` migration

`subagents/veritas/implementation.py` rewrites `answer()` to call `invoke_structured_chat`:

```python
async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
) -> VeritasAnswerSchema:
    n = len(request.questions)
    json_schema = build_veritas_response_schema(n)
    messages = [
        SystemMessage(content=build_veritas_system_prompt()),
        HumanMessage(content=build_veritas_user_prompt(request, max_context_steps=max_context_steps)),
    ]
    try:
        data = await invoke_structured_chat(
            model,
            messages,
            json_schema=json_schema,
            schema_name="VeritasAnswer",
            strict=True,
        )
    except StructuredOutputError as exc:
        logger.warning("[veritas] structured output failed: %s", exc)
        return VeritasAnswerSchema(
            defer=True,
            confidence=0.0,
            rationale=f"structured_output_failed: {exc}",
            answers=[],
        )

    result = VeritasAnswerSchema.model_validate(data)
    if not result.defer and _any_answer_is_a_question(result.answers):
        logger.info("[veritas] answer ended with '?'; coercing to defer")
        return result.model_copy(update={
            "defer": True,
            "confidence": 0.0,
            "rationale": "answer_was_question",
        })
    return result
```

Properties:

- The post-hoc count-mismatch check is removed — the schema enforces it.
- The `?`-suffix check stays (content rule, not shape rule).
- Structured-output failures return a deferred `VeritasAnswerSchema` with a `rationale` prefix (`structured_output_failed: ...`) that the policy uses to discriminate kind.
- `VeritasAnswerSchema` is unchanged; it remains the typed in-process representation policies consume.

### 5.2 Dynamic JSON Schema: `build_veritas_response_schema(n)`

Added to `subagents/veritas/schemas.py`:

```json
{
  "type": "object",
  "title": "VeritasAnswer",
  "required": ["defer", "confidence", "rationale"],
  "properties": {
    "defer": {"type": "boolean"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "rationale": {"type": "string", "minLength": 1},
    "answers": {"type": "array", "items": {"type": "string"}}
  },
  "oneOf": [
    {"properties": {"defer": {"const": true}}},
    {
      "properties": {
        "defer": {"const": false},
        "answers": {
          "type": "array",
          "minItems": N,
          "maxItems": N,
          "items": {"type": "string", "minLength": 1}
        }
      },
      "required": ["answers"]
    }
  ]
}
```

`N` is bound at call time from `len(request.questions)`. The `oneOf` makes "defer or exactly N non-empty answers" structurally enforced. The model sees this contract via the structured-output method chosen by `invoke_structured_chat`. Post-validation catches anything the provider lets through.

### 5.3 Defer kind taxonomy

`core/loop/clarification/protocol.py`:

```python
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
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.request = request
        self.kind = kind
```

`kind` defaults to `"explicit"` for backward compatibility — existing call sites and the `InteractiveClarificationPolicy`'s `"operator dismissed clarification (no answer)"` raise still work without changes.

### 5.4 `AutoClarificationPolicy` classification & fallback

`core/loop/clarification/auto.py` is updated:

```python
class AutoClarificationPolicy:
    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
    ) -> None:
        ...
        self._interactive_fallback = interactive_fallback

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        result = await self._veritas_answer(request)
        kind = self._classify(result)

        if kind == "structured_output_failed" and self._interactive_fallback is not None:
            logger.warning(
                "[veritas] structured output failed; falling back to interactive relay"
            )
            return await self._interactive_fallback.answer(request)

        if kind is not None:
            raise ClarificationDeferredError(
                self._reason_for(kind, result),
                request,
                kind=kind,
            )

        return ClarificationAnswer(
            answers=tuple(result.answers),
            source="veritas",
            confidence=result.confidence,
            defer=False,
            audit={"rationale": result.rationale},
        )

    def _classify(self, result: VeritasAnswerSchema) -> DeferKind | None:
        if result.defer:
            if result.rationale.startswith("structured_output_failed"):
                return "structured_output_failed"
            if result.rationale == "answer_was_question":
                return "answer_was_question"
            return "explicit"
        if result.confidence < self._min_confidence:
            return "low_confidence"
        return None
```

The rationale-prefix discriminator is a small coupling between veritas's coercion strings and the policy's classifier. It is confined to one private method. A future migration to a typed `defer_kind: DeferKind | None` field on `VeritasAnswerSchema` is permitted by this RFC but not required.

### 5.5 `runtime_factory` wiring

`core/loop/clarification/runtime_factory.py` updates `build_clarification_policy_for_runner` so that when `mode=="auto"`, it also constructs an `InteractiveClarificationPolicy` and passes it as `interactive_fallback`:

```python
def build_clarification_policy_for_runner(config, *, mode=None, emit=None):
    resolved = resolve_clarification_mode(mode, config)
    if resolved == "manual":
        return build_default_clarification_policy(mode="manual", emit=emit)

    veritas_cfg = config.agent.veritas
    veritas_model = config.create_chat_model(veritas_cfg.model_role)

    async def _veritas(request):
        return await veritas_answer(
            request,
            model=veritas_model,
            max_context_steps=veritas_cfg.max_context_steps,
        )

    interactive_fallback = (
        InteractiveClarificationPolicy(emit=emit) if emit is not None else None
    )

    return build_default_clarification_policy(
        mode="auto",
        veritas_answer=_veritas,
        emit=emit,
        min_confidence=config.agent.clarification.auto_min_confidence,
        interactive_fallback=interactive_fallback,
    )
```

`build_default_clarification_policy` is extended with an optional `interactive_fallback` keyword that it forwards to `AutoClarificationPolicy`. Autopilot worker (which constructs the policy with `emit=None`) gets `interactive_fallback=None` — the fallback is silently disabled and behavior on veritas failure is identical to today (hard defer). Interactive callers (`_runner_strange_loop`) wire `emit`, getting the fallback automatically.

### 5.6 `await_clarification` event payload

`core/loop/orchestrator/nodes/await_clarification.py`:

- Log severity at line 85 (`policy deferred`) is raised from `INFO` to `WARNING`.
- The `LOOP_CLARIFICATION_DEFERRED` event payload gains a `defer_kind` field populated from `exc.kind`:

```python
await ctx.emit(
    LOOP_CLARIFICATION_DEFERRED,
    {
        "reason": exc.reason,
        "defer_kind": exc.kind,
        "question_summary": _summary(request.questions),
    },
)
```

The "no policy configured" branch keeps the original payload (no `defer_kind`) — that is a system-misconfiguration path, not a veritas event.

### 5.7 Behavior matrix

| Scenario | Today (auto mode) | After RFC-623 (auto mode, interactive run) | After RFC-623 (auto mode, autopilot run) |
|---|---|---|---|
| Veritas returns N valid answers | continue | continue (identical) | continue (identical) |
| Veritas returns `defer=true` confidently | hard defer | hard defer, `defer_kind="explicit"` | hard defer, `defer_kind="explicit"` |
| Veritas returns `confidence < threshold` | hard defer | hard defer, `defer_kind="low_confidence"` | hard defer, `defer_kind="low_confidence"` |
| Veritas returns answer ending in `?` | hard defer | hard defer, `defer_kind="answer_was_question"` | hard defer, `defer_kind="answer_was_question"` |
| LLM returns empty `answers=[]`, `defer=false` | post-hoc coercion → hard defer | schema rejects → `StructuredOutputError` → fallback to TUI relay (durable interrupt) | schema rejects → `StructuredOutputError` → hard defer, `defer_kind="structured_output_failed"` |
| LLM returns wrong-count answers | post-hoc coercion → hard defer | as above | as above |
| LLM returns malformed JSON | Pydantic raises uncaught | `invoke_structured_chat` retries methods; on full failure → fallback to TUI relay | retries methods; on full failure → hard defer, `defer_kind="structured_output_failed"` |
| Provider error (rate limit, timeout) | bubbles up uncaught | `StructuredOutputError` → fallback to TUI relay | `StructuredOutputError` → hard defer, `defer_kind="structured_output_failed"` |

---

## 6. Examples

### 6.1 Healthy auto-mode answer

Veritas LLM, given the dynamic schema, returns:

```json
{
  "defer": false,
  "confidence": 0.86,
  "rationale": "User said 'soothe-daemon' twice; pick that package first.",
  "answers": ["soothe-daemon", "yes, create an implementation guide"]
}
```

`invoke_structured_chat` validates against the schema. `AutoClarificationPolicy._classify` returns `None` (not deferred, confidence above threshold). Policy returns `ClarificationAnswer(source="veritas", confidence=0.86, ...)`. The originating step resumes; loop continues.

### 6.2 Forced defer in autopilot

Same call, but the model returns malformed JSON. `invoke_structured_chat` exhausts methods, raises `StructuredOutputError`. Veritas catches, returns `VeritasAnswerSchema(defer=True, rationale="structured_output_failed: ...", confidence=0.0)`. Policy classifies kind as `"structured_output_failed"`. Autopilot wired `emit=None` → no `interactive_fallback`. Policy raises `ClarificationDeferredError(kind="structured_output_failed")`. `await_clarification` logs `WARNING`, emits `LOOP_CLARIFICATION_DEFERRED` with `defer_kind="structured_output_failed"`, marks goal `awaiting_clarification`, returns `last_outcome="deferred"`. Loop ends.

### 6.3 Forced defer in interactive run

Same scenario but a TUI is attached: `_runner_strange_loop` wired `emit`, so `interactive_fallback=InteractiveClarificationPolicy(emit=emit)`. Policy detects `kind="structured_output_failed"`, calls `interactive_fallback.answer_as_manual_fallback(request)`. That path re-emits `clarification_requested` with `mode="manual"` (the earlier `await_clarification` emit used `mode=auto`), then calls `interrupt(...)`. The LangGraph checkpointer captures the pending question; the TUI renders the prompt; the operator types an answer; `Command(resume=...)` returns the payload. Veritas's failure is invisible to the policy's caller — the loop continues with the human's answer.

---

## 7. Relationship to Other RFCs

- **RFC-622 (CoreAgent Clarification Relay)**: RFC-623 strengthens the auto-mode policy introduced by RFC-622 without changing its protocol or surface area. `ClarificationPolicy`, `await_clarification`, `awaiting_clarification`, and the `veritas` subagent are all defined by RFC-622 and consumed verbatim here.
- **RFC-220 (Agentic Goal Execution / StrangeLoop)**: The defer terminal path (`last_outcome="deferred"` → `END` via `route_after_clarification`) is RFC-220's. Unchanged.
- **RFC-403 (Unified Event Naming)**: The `LOOP_CLARIFICATION_DEFERRED` event keeps its `soothe.loop.clarification_deferred` type; the `defer_kind` field is an additive payload extension.
- **RFC-222 (Autopilot Mode)**: The autopilot worker's contract — headless, always auto, no human at the other end — is preserved. RFC-623's interactive fallback is statically disabled when `emit is None`.

---

## 8. Open Questions

- Should `VeritasAnswerSchema` eventually expose `defer_kind: DeferKind | None` as a typed field, replacing the rationale-prefix discriminator? Deferring this until a fifth defer kind appears.
- Should the `defer_kind` value also propagate onto `Goal.pending_clarification` so an operator inspecting a stuck goal sees the original failure category? Likely yes; not required by the current relay flow and out of scope here.
- Should autopilot's stale-clarification sweep treat `structured_output_failed` defers differently (e.g. shorter TTL, automatic retry after backoff)? Out of scope; revisit if production data shows a meaningful share of defers come from this kind.

---

## 9. Conclusion

RFC-623 closes a structured-output reliability gap in the RFC-622 auto-mode clarification relay. By migrating veritas onto the shared `invoke_structured_chat` helper and enforcing the *exactly N non-empty answers or defer* contract directly in the JSON Schema sent to the model, the empty-but-not-deferred failure mode that prematurely defers loops becomes structurally impossible. A defer-kind taxonomy and an opt-in interactive fallback give operators the visibility and the recovery path that auto mode was missing.

> Auto mode is only useful if veritas can actually answer; veritas can only answer if the structured-output path enforces the contract upfront. RFC-623 makes that contract first-class.
