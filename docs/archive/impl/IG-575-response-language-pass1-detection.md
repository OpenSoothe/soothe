# IG-575: Pass 1 Response Language Detection

**Created**: 2026-07-10  
**Status**: Implemented  
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [RFC-214](../specs/RFC-214-strangeloop-loop-message-surface.md), [IG-554](IG-554-two-pass-intake-classification-implementation.md), [IG-567](IG-567-heuristic-to-rules-migration.md)  
**Design draft**: [2026-07-10-response-language-pass1-design.md](../drafts/2026-07-10-response-language-pass1-design.md)

---

## Executive Summary

Agent-generated prose often drifts to English because language preference is inferred vaguely from goal text. This guide adds a structured `response_language` field to Pass 1 intake, propagates it through `IntentClassification` and `LoopState`, and replaces the static `RESPONSE_LANGUAGE_HINT` with an explicit per-loop directive. Removes the brittle `query_prefers_chinese()` Unicode heuristic.

**Scope**: Agent-generated text only (chitchat, plan, execute, synthesis, goal completion). Static TUI chrome is out of scope.

---

## Problem

| Issue | Location |
|-------|----------|
| Vague static hint | `RESPONSE_LANGUAGE_HINT_FRAGMENT` in `system_templates.py` |
| Duplicated language-lock copy | `plan_generate_instructions.xml`, `synthesis_report_system.xml`, `scenario_classifier_system.xml`, `goal_completion.py` |
| No structured signal | Pass 1 matches language implicitly; nothing on `LoopState` |
| Brittle heuristic | `query_prefers_chinese()` in `chitchat_fallbacks.py` |

---

## Solution

```
User message
  → Pass 1: response_language ∈ {en, zh, ja, ko, other}
  → IntentClassification.response_language
  → LoopState.response_language
  → build_response_language_hint(language) in plan / execute / synthesis prompts
```

---

## Scope

### In Scope

- `ResponseLanguage` enum (`en`, `zh`, `ja`, `ko`, `other`)
- `response_language` on `IntakePass1LLMResult`, `IntentClassification`, `LoopState`
- Pass 1 prompt rules + `prior_response_language` coordinator context
- `build_response_language_hint()` dynamic fragment
- Wire hint into execute system prompt, plan builder, goal completion, synthesis, resume topic
- Remove redundant per-fragment language-lock XML lines
- Delete `query_prefers_chinese()`; update `pick_generic_chitchat_fallback(language=...)`
- Unit + integration tests

### Out of Scope

- TUI i18n (spinners, slash help, daemon errors)
- BCP-47 locale (`zh-CN` vs `zh-TW`)
- Pass 2 language re-detection
- Localized JA/KO chitchat fallback pools (use EN pool until added)

---

## Implementation Phases

### Phase A: Schema and Pass 1

**Files:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/sloop/intention/models.py` | Add `ResponseLanguage`; extend `IntakePass1LLMResult`, `IntentClassification` |
| `packages/soothe/src/soothe/sloop/intention/pass1_social_response.py` | Add `response_language` to JSON schema |
| `packages/soothe/src/soothe/sloop/prompts/fragments/classifiers/intake_pass1_system.xml` | Detection rules, examples with `response_language` |
| `packages/soothe/src/soothe/sloop/intention/pass1_classifier.py` | Validate enum; accept `prior_response_language`; pass language to social-reply path |

**`ResponseLanguage`:**

```python
class ResponseLanguage(StrEnum):
    EN = "en"
    ZH = "zh"
    JA = "ja"
    KO = "ko"
    OTHER = "other"
```

**Pass 1 prompt rules** (add to `intake_pass1_system.xml`):

1. Detect conversational language, not code/paths in the message.
2. Explicit override wins (“请用英文回答” → `en`).
3. Mixed input: conversational language wins over embedded English code.
4. When `prior_response_language` is provided and the message is a short ack, inherit it.
5. JSON schema adds `"response_language":"en"|"zh"|"ja"|"ko"|"other"`.

**`IntakePass1Classifier.classify()` signature:**

```python
async def classify(
    self,
    query: str,
    *,
    prior_response_language: ResponseLanguage | None = None,
    observability_metadata: dict[str, str] | None = None,
    goal_trace: Any | None = None,
) -> IntakePass1LLMResult:
```

When `prior_response_language` is set, inject a one-line structural hint into the human task (not keyword heuristics on query content).

**Fail-safe:** On LLM error / no model, `response_language` is omitted (`None` at propagation layer); generic fallback hint applies.

---

### Phase B: Propagation

**Files:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/sloop/intention/classifier.py` | Copy `response_language` in `pass1_to_intent`, `_pass2_to_intent`, `_patch_missing_fields` |
| `packages/soothe/src/soothe/sloop/intention/two_pass_coordinator.py` | Pass `prior_response_language` into Pass 1 |
| `packages/soothe/src/soothe/sloop/nodes/intent_classify.py` | Set `loop_state.response_language` from intent |
| `packages/soothe/src/soothe/sloop/engine/strange_loop.py` | Set language on pre-graph social fast-path; pass prior language into `classify_pass1` |
| `packages/soothe/src/soothe/sloop/state/schemas.py` | Add `LoopState.response_language` |

**Clarification resume:** When Pass 1 is skipped, inherit existing `LoopState.response_language` (no re-detection).

**Mid-loop language switch:** New user turn re-runs Pass 1; overwrite `LoopState.response_language`.

---

### Phase C: Dynamic language hint

**Files:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/sloop/prompts/system_templates.py` | Add `build_response_language_hint()`; rename static fragment to `RESPONSE_LANGUAGE_HINT_FALLBACK` |
| `packages/soothe/src/soothe/sloop/prompts/builder.py` | Use builder with `state.response_language` |
| `packages/soothe/src/soothe/middleware/system_prompt.py` | Use builder with loop state language |
| `packages/soothe/src/soothe/sloop/nodes/goal_completion.py` | Language-aware ledger human line |
| `packages/soothe/src/soothe/sloop/prompts/user_message.py` | Synthesis message uses explicit language when set |
| `packages/soothe/src/soothe/sloop/state/resume_topic.py` | Use explicit language when available |

**Builder contract:**

```python
def build_response_language_hint(language: ResponseLanguage | None) -> str:
    if language is None or language == ResponseLanguage.OTHER:
        return RESPONSE_LANGUAGE_HINT_FALLBACK
    # explicit: "Write all user-facing prose in Chinese (zh). ..."
```

**Remove redundant language lines from:**

- `prompts/fragments/instructions/plan_generate_instructions.xml`
- `prompts/fragments/instructions/synthesis_report_system.xml`
- `prompts/fragments/classifiers/scenario_classifier_system.xml` (locale line only)
- `prompts/fragments/classifiers/intake_pass1_social_reply.xml` (replace “match language” with explicit param when known)

Keep `RESPONSE_LANGUAGE_HINT` XML tag name for cache-slot stability (RFC-214).

---

### Phase D: Remove heuristics

**Files:**

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/sloop/chitchat_fallbacks.py` | Delete `query_prefers_chinese`; change `pick_generic_chitchat_fallback(language=...)` |
| `packages/soothe/src/soothe/sloop/intention/pass1_classifier.py` | Pass `result.response_language` to fallback |
| `packages/soothe/src/soothe/sloop/intention/classifier.py` | Same |

**Fallback pools:**

| `response_language` | Pool |
|-------------------|------|
| `zh` | `GENERIC_CHITCHAT_FALLBACKS_ZH` |
| `en` | `GENERIC_CHITCHAT_FALLBACKS_EN` |
| `ja`, `ko`, `other`, `None` | `GENERIC_CHITCHAT_FALLBACKS_EN` (until localized) |

Verify no remaining imports of `query_prefers_chinese` (grep + vulture).

---

## Testing

| Test file | Cases |
|-----------|-------|
| `tests/unit/core/test_intent_classification.py` | Pass 1 schema includes `response_language`; prompt mentions override rule |
| `tests/integration/core/test_two_pass_intake_integration.py` | Propagation mock sets language on intent |
| `tests/unit/middleware/test_system_prompt.py` | `zh` → “Chinese (zh)” in system prompt; `None` → generic fallback |
| `tests/unit/core/prompts/test_builder_prior_progress.py` | Plan system prompt uses dynamic hint |
| `tests/unit/core/prompts/test_user_envelope.py` | Hint still not in user envelope |
| New: `tests/unit/core/test_response_language_hint.py` | Builder unit tests for all enum values |
| New or extend chitchat fallback tests | `pick_generic_chitchat_fallback(ZH)` returns Chinese string |

**Manual smoke:**

1. Chinese goal → plan reasoning and final report in Chinese.
2. “请用英文回答” + Chinese body → English responses.
3. Short “好的” on turn 2 → inherits Chinese from turn 1.
4. English code + Chinese question → Chinese prose.

---

## Verification

```bash
./scripts/verify_finally.sh
```

All tests pass; zero lint; no `query_prefers_chinese` references.

---

## Rollout / Compatibility

- No config flag required (behavioral improvement, fail-safe fallback preserved).
- Checkpoint resume: `response_language` on `LoopState` is optional; missing → generic hint (same as today).
- RFC-630 Pass 1 schema amendment: document `response_language` in RFC when promoting from Draft (optional follow-up).

---

## Checklist

- [x] Phase A: Schema + Pass 1 prompt + classifier
- [x] Phase B: Propagation to `IntentClassification` + `LoopState`
- [x] Phase C: Dynamic hint wired; redundant XML removed
- [x] Phase D: `query_prefers_chinese` deleted
- [x] Tests added/updated
- [x] `./scripts/verify_finally.sh` passes
