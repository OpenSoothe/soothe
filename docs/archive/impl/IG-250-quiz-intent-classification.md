# IG-250: Quiz/Trivia Intent Classification

**Status**: Draft
**Created**: 2026-04-24
**Author**: AI Agent

---

## Overview

Add `quiz` intent type to the unified query classification system to efficiently handle quiz/trivia questions using LLM knowledge without goal-oriented agentic tools.

---

## Problem Statement

Currently, quiz and trivia questions (e.g., "What is the capital of France?", "Who wrote Romeo and Juliet?") are classified as `new_goal` and processed through the full AgentLoop with tools like file operations, web search, and code execution. This is inefficient because:

1. **LLM knowledge is sufficient**: Quiz/trivia answers are typically factual knowledge the LLM already has
2. **Tool overhead**: AgentLoop spawns tools unnecessarily for simple factual queries
3. **Latency**: Full goal creation + AgentLoop execution adds latency compared to direct LLM response
4. **Resource waste**: Spawning tools for knowledge queries wastes compute cycles

**Current flow**:
```
Quiz query → new_goal → GoalEngine → AgentLoop (with tools) → Tool spawning → LLM synthesis → Response
```

**Desired flow**:
```
Quiz query → quiz intent → Direct LLM call (no tools) → Response
```

---

## Design

### Intent Classification Model Changes

Extend `IntentClassification` model to support 4 intent types:

```python
class IntentClassification(BaseModel):
    intent_type: Literal["chitchat", "thread_continuation", "new_goal", "quiz"]
    # ... other fields
```

### Quiz Intent Characteristics

**Quiz intent detection criteria**:
- Factual knowledge questions (history, geography, science, literature, etc.)
- Trivia questions (pop culture, sports, general knowledge)
- Multiple choice questions
- Definition requests ("What is X?")
- Brief factual queries requiring no external tools

**Quiz intent handling**:
- Direct LLM call without AgentLoop
- No tool spawning (no file ops, web search, code execution)
- Fast response path similar to chitchat
- LLM generates response from internal knowledge

**Quiz vs. new_goal distinction**:
| Query | Intent | Reasoning |
|-------|--------|-----------|
| "What is the capital of France?" | `quiz` | Factual knowledge, no tools needed |
| "Count all readme files in project" | `new_goal` | Requires file system tools |
| "Who wrote Romeo and Juliet?" | `quiz` | Literature knowledge, LLM knows |
| "Analyze the codebase architecture" | `new_goal` | Requires file ops + analysis |
| "What's 15 * 23?" | `quiz` | Simple math, LLM can compute |
| "Calculate total sales from CSV" | `new_goal` | Requires file + data processing |

---

## Implementation Plan

### Phase 1: Model Extension

**File**: `packages/soothe/src/soothe/cognition/intention/models.py`

```python
class IntentClassification(BaseModel):
    intent_type: Literal["chitchat", "thread_continuation", "new_goal", "quiz"] = Field(
        description="Primary intent: chitchat (greeting), thread_continuation (follow-up), "
                    "new_goal (task requiring tools), quiz (factual knowledge query)"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct LLM response for quiz queries (piggybacked from classification)"
    )
    # ... other existing fields
```

### Phase 2: Prompt Updates

**File**: `packages/soothe/src/soothe/cognition/intention/prompts.py`

Update `INTENT_CLASSIFICATION_PROMPT`:

```python
INTENT_CLASSIFICATION_PROMPT = """\
You are {assistant_name}. Classify this query's intent.

... (existing preamble) ...

Intent classification criteria:
- chitchat: Greetings, thanks, fillers needing no action
  → chitchat_response in detected language
  → task_complexity=chitchat

- quiz: Factual knowledge questions, trivia, definitions, simple math
  Examples: "What is the capital of France?", "Who wrote Romeo and Juliet?",
           "What's quantum entanglement?", "15 * 23"
  Detection: Question asking for known facts, no tools/files/analysis needed
  → quiz_response (brief factual answer from LLM knowledge)
  → task_complexity=quiz

- thread_continuation: References prior conversation, follow-up actions
  → reuse_current_goal based on active_goal
  → task_complexity=medium

- new_goal: Tasks requiring tools (file ops, web search, analysis, coding)
  Examples: "count readme files", "analyze codebase", "build auth system"
  → goal_description required
  → task_complexity=medium or complex

Intent precedence:
1. Prior conversation reference → thread_continuation
2. Conversational filler → chitchat
3. Factual knowledge question → quiz
4. Tool-requiring task → new_goal (DEFAULT when uncertain)

Required JSON shape:
{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "task_complexity": "chitchat"|"quiz"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null,
  "reasoning": string
}
"""
```

### Phase 3: Classifier Logic

**File**: `packages/soothe/src/soothe/cognition/intention/classifier.py`

Update `_patch_missing_fields()` to handle quiz intent:

```python
def _patch_missing_fields(
    self,
    intent: IntentClassification,
    query: str,
) -> IntentClassification:
    # Patch missing chitchat_response
    if intent.intent_type == "chitchat" and not intent.chitchat_response:
        intent.chitchat_response = self._generate_chitchat_response(query)

    # Patch missing quiz_response (fallback: use query as prompt)
    if intent.intent_type == "quiz" and not intent.quiz_response:
        intent.quiz_response = self._generate_quiz_response(query)

    # Patch missing goal_description
    if intent.intent_type == "new_goal" and not intent.goal_description:
        intent.goal_description = query

    return intent
```

Add `_generate_quiz_response()`:

```python
def _generate_quiz_response(self, query: str) -> str:
    """Generate quiz response via fast LLM call.

    Args:
        query: Quiz/trivia question.

    Returns:
        Factual answer from LLM knowledge.
    """
    # If no model available, return placeholder
    if not self._fast_model:
        return "I need to answer this question but my quiz module is disabled."

    # Fast LLM call for quiz response
    # Note: This is a fallback; primary path is piggybacked quiz_response from classification
    return f"I'll answer: {query}"
```

### Phase 4: Runner Integration

**Files**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`, `_runner_autonomous.py`

Add quiz handling path:

```python
# Handle quiz intent
if intent_classification.intent_type == "quiz":
    logger.info("[Intent] Quiz → direct LLM response")
    async for chunk in self._run_quiz(user_input, tid, intent_classification):
        yield chunk
    return
```

Add `_run_quiz()` method:

```python
async def _run_quiz(
    self,
    user_input: str,
    thread_id: str,
    classification: IntentClassification,
) -> AsyncGenerator[StreamChunk]:
    """Fast path for quiz queries -- LLM direct response without tools.

    Similar to chitchat but uses LLM to generate factual response.
    Piggybacked quiz_response from classification if available, otherwise
    spawns fast LLM call.
    """
    yield _custom(QuizStartedEvent(query=user_input[:100]).to_dict())

    # Use piggybacked response if available
    piggybacked = getattr(classification, "quiz_response", None)
    if piggybacked:
        yield _custom(QuizResponseEvent(content=piggybacked).to_dict())
        logger.debug("Quiz completed for query: %s", user_input[:50])
        return

    # Otherwise, spawn fast LLM call for quiz response
    quiz_prompt = f"""Answer this question concisely and accurately:

Question: {user_input}

Provide a brief factual answer (1-3 sentences). Do not use tools or search."""

    metadata = self._create_llm_metadata("quiz_response", "quiz.fast_path")

    try:
        response = await self._fast_model.ainvoke(quiz_prompt, config={"metadata": metadata})
        answer = response.content if hasattr(response, "content") else str(response)

        yield _custom(QuizResponseEvent(content=answer).to_dict())
        logger.debug("Quiz completed via fast LLM: %s", user_input[:50])
    except Exception:
        logger.exception("Quiz fast path failed")
        yield _custom(QuizResponseEvent(content="I couldn't answer that question.").to_dict())
```

### Phase 5: Event Definitions

**File**: `packages/soothe/src/soothe/core/event_catalog.py` or module events

Add quiz events:

```python
class QuizStartedEvent(SootheEvent):
    """Quiz query started."""
    type: str = "soothe.quiz.started"
    query: str

class QuizResponseEvent(SootheEvent):
    """Quiz response generated."""
    type: str = "soothe.quiz.response"
    content: str
```

Register events:

```python
register_event(QuizStartedEvent, summary_template="Quiz: {query}")
register_event(QuizResponseEvent, summary_template="Answered quiz question")
```

### Phase 6: Test Updates

**File**: `packages/soothe/tests/unit/core/test_intent_classification.py`

Add quiz intent tests:

```python
@pytest.mark.asyncio
async def test_quiz_intent_classification(self) -> None:
    """LLM correctly classifies factual questions as quiz."""
    mock_model = MagicMock()
    mock_intent_model = AsyncMock()

    mock_intent_model.ainvoke = AsyncMock(
        return_value=IntentClassification(
            intent_type="quiz",
            quiz_response="Paris is the capital of France.",
            task_complexity="quiz",
            reasoning="Factual geography question, LLM knowledge sufficient",
        )
    )

    classifier = IntentClassifier(model=mock_model)
    classifier._intent_model = mock_intent_model

    result = await classifier.classify_intent("What is the capital of France?")

    assert result.intent_type == "quiz"
    assert result.quiz_response is not None
    assert "Paris" in result.quiz_response
    assert result.task_complexity == "quiz"
    assert not result.reuse_current_goal
    assert result.goal_description is None

@pytest.mark.asyncio
async def test_quiz_vs_new_goal_distinction(self) -> None:
    """Quiz questions distinguished from tool-requiring tasks."""
    mock_model = MagicMock()
    mock_intent_model = AsyncMock()

    # Quiz question -> quiz intent
    mock_intent_model.ainvoke = AsyncMock(
        return_value=IntentClassification(
            intent_type="quiz",
            quiz_response="William Shakespeare wrote Romeo and Juliet.",
            task_complexity="quiz",
            reasoning="Literature knowledge question",
        )
    )

    classifier = IntentClassifier(model=mock_model)
    classifier._intent_model = mock_intent_model

    quiz_result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
    assert quiz_result.intent_type == "quiz"

    # Tool-requiring task -> new_goal intent
    mock_intent_model.ainvoke = AsyncMock(
        return_value=IntentClassification(
            intent_type="new_goal",
            goal_description="Count all readme files in the workspace",
            task_complexity="medium",
            reasoning="Requires file system tools",
        )
    )

    task_result = await classifier.classify_intent("count all readme files")
    assert task_result.intent_type == "new_goal"
```

---

## Implementation Steps

1. **Phase 1**: Extend `IntentClassification` model (models.py)
2. **Phase 2**: Update classification prompts (prompts.py)
3. **Phase 3**: Update classifier logic (classifier.py)
4. **Phase 4**: Add runner quiz path (_runner_agentic.py, _runner_autonomous.py)
5. **Phase 5**: Define quiz events (event_catalog.py or module events)
6. **Phase 6**: Add quiz tests (test_intent_classification.py)
7. **Phase 7**: Run verification: `./scripts/verify_finally.sh`

---

## Success Criteria

1. Quiz/trivia questions classified as `quiz` intent (not `new_goal`)
2. Quiz queries trigger direct LLM response (no AgentLoop/tools)
3. Tool-requiring tasks still classified as `new_goal`
4. Piggybacked quiz_response used when available
5. Fast LLM fallback when quiz_response missing
6. All existing tests pass
7. New quiz tests pass

---

## Testing Examples

**Quiz queries (should be quiz intent)**:
- "What is the capital of France?"
- "Who wrote Romeo and Juliet?"
- "What's quantum entanglement?"
- "What is the speed of light?"
- "Who won the 2020 Olympics?"

**Tool-requiring tasks (should remain new_goal)**:
- "Count all readme files in the project"
- "Analyze the codebase architecture"
- "Build an authentication system"
- "Search the web for recent AI papers"
- "Read the config file and extract settings"

---

## Notes

1. **Quiz vs. new_goal distinction is critical**: LLM must accurately detect when tools are needed vs. when knowledge alone suffices
2. **Prompt tuning required**: Classification prompts need clear examples distinguishing quiz from new_goal
3. **Fallback safety**: If classification fails, fall back to `new_goal` (safe default for tool-requiring tasks)
4. **Performance**: Quiz path should be significantly faster than AgentLoop path (target: <2s vs. 10s+)

---

## References

- IG-226: Unified Query Intent Classification (original intent system)
- RFC-200: Agentic Goal Execution (AgentLoop design)
- `packages/soothe/src/soothe/cognition/intention/` (intent module)