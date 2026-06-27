# IG-518: Intent Classification Reasoning Field and Performance Enhancement

## Summary

Enhance intent-classify to:
1. Add `reasoning` field for agentic intents, emit as cognition event to client
2. Optimize prompt token efficiency without reducing classification accuracy

## Background

Current intent-classify returns:
- `intent_type`: "quiz" or "agentic"
- `goal_description`: normalized goal (agentic only)
- `task_complexity`: routing level
- `quiz_response`: direct answer (quiz only)

No reasoning is exposed to clients, leading to opaque "first response" when entering agentic mode. Users see `STRANGE_LOOP_STARTED` but not why.

## Design

### Part 1: Reasoning Field + Event Emission

**Data Model Changes** (`models.py`):
```python
class IntentClassificationLLMResult(BaseModel):
    intent_type: Literal["quiz", "agentic"]
    reasoning: str | None = Field(
        default=None,
        description="Brief reasoning for agentic classification (why tools/action needed). Empty for quiz."
    )
    goal_description: str | None = None
    task_complexity: TaskComplexity
    quiz_response: str | None = None
```

**Prompt Changes** (`intent_classification.xml`):
Add reasoning instruction for agentic:
```xml
When intent_type is "agentic", also provide:
- reasoning: ONE brief sentence (max 20 words) explaining why tools/action needed.
  Examples: "Needs file analysis", "Follow-up on prior work", "Requires web search", "Multi-step code change"
```

**Event Definition** (`constants.py`, `catalog.py`):
```python
INTENT_CLASSIFIED = "soothe.cognition.intent.classified"

class IntentClassifiedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.intent.classified"] = "soothe.cognition.intent.classified"
    intent_type: Literal["quiz", "agentic"]
    reasoning: str | None = None  # agentic only
    goal_description: str | None = None
```

**Event Emission** (`_runner_strange_loop.py`):
After `intent_classification.classify_intent()` call, if agentic:
```python
if intent_classification.intent_type == "agentic" and intent_classification.reasoning:
    yield _custom(
        IntentClassifiedEvent(
            intent_type="agentic",
            reasoning=intent_classification.reasoning,
            goal_description=intent_classification.goal_description,
        ).to_dict()
    )
```

### Part 2: Prompt Token Efficiency

**Current Prompt Analysis** (~2050 bytes, ~500 tokens):
- `<intent_instructions>`: verbose rules, repetitive "NOT quiz" examples
- JSON schema: verbose field descriptions inline
- `<current_time>`: useful context but adds tokens

**Optimizations**:

1. **Condense Classification Rules**:
```xml
intent_type: "quiz" (greeting/thanks/static trivia from training knowledge) or "agentic" (else).
NOT quiz if: needs tools/files/web/live-data, follow-ups, runtime state queries, time-sensitive.
```
~150 chars vs ~800 chars currently

2. **Inline JSON Schema** (no field descriptions):
```json
{"intent_type":"quiz|agentic","reasoning":"string|null","task_complexity":"minimal|simple|medium|complex","quiz_response":"string|null"}
```

3. **Move Examples to Retry Prompt Only**:
Primary prompt minimal; retry prompt has verbose examples for error recovery.

**Estimated Savings**: ~60% token reduction (from ~500 to ~200 tokens)

### Part 3: Field Population Logic

**In `IntentClassificationLLMResult.to_intent_classification()`**:
- Quiz: reasoning = None (not requested, not populated)
- Agentic: reasoning passed through from LLM result

**Fallback Cases**:
- Heuristic bypass (`_is_likely_agentic`): generate default reasoning "Query complexity exceeds quiz threshold"
- LLM failure fallback: reasoning = "Classification fallback to agentic"

## Files Modified

| File | Changes |
|------|---------|
| `models.py` | Add `reasoning` field to both model classes |
| `classifier.py` | Pass reasoning through; add fallback reasoning |
| `intent_classification.xml` | Condensed prompt + reasoning instruction |
| `intent_classification_retry.xml` | Keep verbose examples for retry |
| `constants.py` | Add `INTENT_CLASSIFIED` event type |
| `catalog.py` | Add `IntentClassifiedEvent` class + registration |
| `_runner_strange_loop.py` | Emit event after agentic classification |

## Testing

1. Unit tests: verify reasoning field in IntentClassificationLLMResult
2. Integration: emit IntentClassifiedEvent for agentic queries
3. Accuracy: classification accuracy unchanged (validate on test queries)
4. Token count: verify prompt token reduction via Langfuse traces

## Risks

- Reasoning quality depends on LLM; may need prompt tuning
- Token savings must not degrade accuracy - validate empirically

## Status

Draft - awaiting approval