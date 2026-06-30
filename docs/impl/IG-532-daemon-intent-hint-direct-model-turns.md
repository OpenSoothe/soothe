# IG-532: Daemon `intent_hint` Direct Model Turns

**Guide**: IG-532  
**Title**: Daemon `intent_hint` Direct Model Turns  
**Created**: 2026-06-30  
**Related RFCs**: RFC-450 (loop_input wire), RFC-627 (LLM utilities / structured output)  
**Status**: Implemented

## Summary

Redesign `loop_input.intent_hint` as a **daemon-only** switch for direct model invocations that bypass the Soothe agent graph. Remove agent-path hint bypasses (`quiz`, `IntentHint` enum). Replace the legacy monolithic `direct_llm` hint with explicit roles: `text_completion`, `image_to_text`, `ocr`, and `embed`. Add matching `router.ocr` model role for OCR turns.

Agent intake classification (`IntentClassifier.classify_intake`, RFC-630) is unchanged in behavior except that **wire hints no longer influence it** — all non-direct turns always run the intake LLM.

## Motivation

| Before | Problem |
|--------|---------|
| `intent_hint=quiz` | Bypassed intake LLM on agent path; duplicated quiz routing vs RFC-630 intake |
| `intent_hint=direct_llm` | Ambiguous (text vs vision); deprecated alias chain; blocked structured output on attachments |
| `IntentHint` enum + `parse_intent_hint()` | Agent runner accepted hints that only made sense on daemon wire |
| No `ocr` / `embed` hints | OCR and embedding required full agent loop or ad-hoc code |

Direct model turns and agent intake are separate concerns: hints should only select daemon-side shortcuts.

## Supported `intent_hint` Values (daemon)

| Hint | Router role | Input | Output | `response_schema` |
|------|-------------|-------|--------|-------------------|
| `text_completion` | `default` | Non-empty text, no attachments | Plain or structured JSON | Yes |
| `image_to_text` | `image` | Attachments required; text optional | Plain or structured JSON | Yes |
| `ocr` | `ocr` | Attachments required; text optional (instruction) | Extracted text | No |
| `embed` | `embedding` | Non-empty text, no attachments | JSON `{"embedding": [...], "dimensions": N}` | No |

**Removed**

| Hint | Behavior now |
|------|----------------|
| `quiz` | Ignored on agent path (intake LLM classifies as before). Not a valid direct hint. |
| `direct_llm` | **Rejected** at router validation with `INVALID_REQUEST` and message pointing to `text_completion` / `image_to_text`. |

Unknown hints (e.g. `resume_clarification`, `skill:foo`) pass through to the agent path unchanged; they do not select direct turns.

## Architecture

```
loop_input (intent_hint set?)
  → router: validate_and_normalize_intent_hint()
       ├─ direct hint → enqueue → QueryEngine → run_intent_hint_turn()
       │                  (no subprocess / StrangeLoop)
       └─ else → agent path → LoopRunRequest (no intent_hint field)
                    → IntentClassifier.classify_intake()  # always LLM, no hint bypass
```

Wire events for direct turns: single `mode=messages` chunk with `phase=<hint>` (`text_completion`, `image_to_text`, `ocr`, `embed`). Subscription complete reason: `direct_turn_end`.

## Key Files

| Area | Path |
|------|------|
| Validation | `packages/soothe-daemon/src/soothe_daemon/protocol/intent_hints.py` |
| Turn dispatch | `packages/soothe-daemon/src/soothe_daemon/services/direct_llm_turn.py` |
| Router | `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` (`_handle_loop_input`) |
| Query engine | `packages/soothe-daemon/src/soothe_daemon/query/engine.py` |
| Router role `ocr` | `packages/soothe/src/soothe/config/models.py` (`ModelRouter.ocr`, `ModelRole`) |
| Agent hint removal | `IntentHint` deleted; `LoopRunRequest.intent_hint` removed; `parse_intent_hint()` removed |
| SDK docs | `packages/soothe-sdk/.../websocket.py`, `ux/loop_stream.py` |
| TS client | `client/typescript/src/intent_hints.ts` |
| Go client | `client/go/intent_hints.go` |

## Validation Rules (router)

- `text_completion`: requires content; rejects attachments.
- `image_to_text` / `ocr`: requires attachments.
- `embed`: requires content; rejects attachments.
- `response_schema`: only with `text_completion` or `image_to_text`; schema body validated via `validate_response_schema`.
- `direct_llm`: immediate error — not normalized.

Content is not required for direct hints that allow attachments-only input (`image_to_text`, `ocr`).

## Client Migration

```typescript
// Before (removed)
intentHint: "direct_llm" | "quiz"

// After
import { INTENT_HINT_TEXT_COMPLETION, INTENT_HINT_IMAGE_TO_TEXT } from "@mirasoth/soothe-client";

intentHint: INTENT_HINT_TEXT_COMPLETION          // text-only LLM
intentHint: INTENT_HINT_IMAGE_TO_TEXT           // + attachments
intentHint: INTENT_HINT_OCR                    // + attachments
intentHint: INTENT_HINT_EMBED                  // embedding JSON
```

Go: `soothe.IntentHintTextCompletion`, `IntentHintImageToText`, `IntentHintOCR`, `IntentHintEmbed`.

Appkit deliverable phases extended: `DEFAULT_DELIVERABLE_PHASES` / `DefaultDeliverablePhases()` include the new direct-hint phases.

## Config Example (`local-deploy`)

```yaml
router:
  default: "omlx:Qwen3.6-27B-OptiQ-4bit"
  fast: "omlx:gemma-4-12b-coder-fable5-composer2.5"
  image: "omlx:GLM-4.6V-Flash-4bit"
  ocr: "omlx:DeepSeek-OCR-4bit"
  embedding: "omlx:nomicai-modernbert-embed-base-bf16"
```

## Tests

| Suite | Coverage |
|-------|----------|
| `tests/unit/protocol/test_intent_hints.py` | Validation matrix, `direct_llm` rejection |
| `tests/unit/protocol/test_router_loop_input.py` | Wire enqueue / error paths |
| `tests/unit/services/test_direct_llm_turn.py` | Per-hint turn dispatch (mocked models) |
| `tests/integration/daemon/test_direct_llm_structured.py` | `text_completion` + `response_schema` (integration) |
| Go `TestIntegration_IntentHintDirectLLMRemoved` | Wire rejection of `direct_llm` |
| TS/Go unit tests | Constants, appkit turn_runner, input options |

Run daemon unit tests:

```bash
cd packages/soothe-daemon && uv run pytest tests/unit/protocol/test_intent_hints.py \
  tests/unit/protocol/test_router_loop_input.py tests/unit/services/test_direct_llm_turn.py -q
```

Run clients (unit):

```bash
cd client/go && go test -short ./...
cd client/typescript && npm test -- --run
```

## Out of Scope / Follow-ups

- `job_create.intent_hint` — still in schema, unused by handler (pre-existing).
- AsyncAPI `loopInputParams` — still missing several optional fields; SDK docstring is authoritative.
- Renaming module `direct_llm_turn.py` → `intent_hint_turns.py` (cosmetic; deferred).

## Checklist

- [x] `intent_hints.py` validation module
- [x] `text_completion`, `image_to_text`, `ocr`, `embed` turn implementations
- [x] `response_schema` on text and vision direct turns
- [x] Remove `direct_llm` (reject, not deprecate)
- [x] Remove `quiz` / `IntentHint` from agent runner
- [x] Add `router.ocr` model role
- [x] Update TS/Go clients + SDK docs
- [x] Unit tests passing

## Relation to IG-528 / RFC-630

IG-528 added 4-class **intake** classification (`quiz | trivial | simple | complex`) on the agent path. This IG **removes the parallel `intent_hint=quiz` bypass** so quiz routing comes only from the intake LLM. Direct model shortcuts are exclusively via the four daemon hints above — no overlap with `intake_label` / `intent_type`.
