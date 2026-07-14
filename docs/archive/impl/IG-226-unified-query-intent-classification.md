# IG-226: Unified Query Intent Classification System

> **Status**: ✅ Phase 1 Complete
> **Date**: 2026-04-21
> **Scope**: Query classification, GoalEngine integration, AgentLoop routing
> **Related RFCs**: RFC-201 (AgentLoop), RFC-609 (Goal Context), RFC-200 (GoalEngine)

---

## 1. Problem Statement

Current query classification conflates **thread continuation** queries with **new goal creation**:

- "translate that" → classified as "medium" → triggers new goal creation ❌
- "explain the result" → classified as "medium" → triggers new goal creation ❌
- "continue from where we stopped" → classified as "medium" → triggers new goal creation ❌

**Expected behavior**:
- Thread continuation queries should reuse current thread/goal
- Skip GoalEngine goal creation for follow-up actions
- Only create goals for truly new tasks

**Architecture gap**: `UnifiedClassifier` only distinguishes chitchat vs medium/complex, lacking intent classification for thread continuation.

---

## 2. Solution Design

### 2.1 Three-Tier Intent Classification

Replace two-tier routing with three-tier intent classification:

| Intent | Detection (LLM-driven) | Execution Path | Goal Handling |
|--------|------------------------|----------------|---------------|
| **chitchat** | Greetings, fillers, thanks | Direct LLM response | No goal |
| **thread_continuation** | Follow-up phrases with context reference | AgentLoop (continue iteration) | Reuse active goal or skip |
| **new_goal** | Standalone tasks, explicit objectives | AgentLoop (new iteration) | Create goal via GoalEngine |

### 2.2 LLM-Driven Classification

**NO keyword-based heuristics**. Use structured LLM call with:

- **Fast model** (same as routing, ~2-4s)
- **Conversation context** (recent messages for intent detection)
- **Structured output** (Pydantic model for type safety)
- **Fallback to safe defaults** (new_goal if uncertain)

### 2.3 Integration Points

1. **UnifiedClassifier** (`core/unified_classifier.py`):
   - Add `classify_intent()` method
   - Single LLM call returns `IntentClassification`
   - Routing complexity becomes secondary attribute

2. **SootheRunner** (`core/runner/__init__.py`, `_runner_phases.py`):
   - Call intent classifier before routing
   - Pass intent to AgenticMixin

3. **AgentLoop** (`cognition/agent_loop/agent_loop.py`):
   - Receive intent in `run_with_progress()`
   - Adjust iteration behavior for thread_continuation

4. **GoalEngine Integration** (`cognition/goal_engine/engine.py`):
   - Only create goal when intent == "new_goal"
   - Thread continuation reuses active goal or skips goal lifecycle

---

## 3. Implementation Architecture

### 3.1 New Pydantic Models

```python
class IntentClassification(BaseModel):
    """LLM-driven query intent classification."""
    
    intent_type: Literal["chitchat", "thread_continuation", "new_goal"] = Field(
        description="Query intent determines execution and goal handling"
    )
    
    # For thread_continuation
    reuse_current_goal: bool = Field(
        default=False,
        description="Whether to reuse active goal in current thread"
    )
    
    # For new_goal
    goal_description: str | None = Field(
        default=None,
        description="Extracted goal description for GoalEngine (normalized from query)"
    )
    
    # Routing attributes (secondary)
    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Routing complexity level"
    )
    
    # Response/Reasoning
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries"
    )
    reasoning: str = Field(
        description="LLM reasoning for classification decision"
    )
```

### 3.2 Unified Classifier Enhancement

Add to `UnifiedClassifier`:

```python
async def classify_intent(
    self,
    query: str,
    *,
    recent_messages: list[Any] | None = None,
    active_goal_id: str | None = None,
    thread_id: str | None = None,
) -> IntentClassification:
    """Unified intent classification with goal awareness.
    
    Single LLM call determines:
    1. Intent type (chitchat/thread_continuation/new_goal)
    2. Goal handling (reuse/skip/create)
    3. Routing complexity (chitchat/medium/complex)
    
    Args:
        query: User input text
        recent_messages: Conversation context for intent detection
        active_goal_id: Current active goal in thread (if any)
        thread_id: Thread context for state awareness
        
    Returns:
        IntentClassification with intent + routing attributes
    """
```

### 3.3 LLM Prompt Design

```python
_INTENT_CLASSIFICATION_PROMPT = """\
You are {assistant_name}. Classify this query's intent.

Current time: {current_time}
Thread ID: {thread_id}
Active goal: {active_goal_context}

Recent conversation:
{conversation_context}

Query: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema
- "intent_type" MUST be exactly one of: "chitchat", "thread_continuation", "new_goal"
- For "chitchat": set chitchat_response (short friendly reply in user's language)
- For "thread_continuation": set reuse_current_goal=true if active_goal exists
- For "new_goal": set goal_description (normalized task description)
- "task_complexity" is secondary: chitchat | medium | complex

Classification criteria:
- chitchat: Greetings, thanks, fillers needing no action → chitchat_response required
- thread_continuation: References prior results ("that", "this", "explain result"), 
  follow-up actions, refinements → reuse_current_goal based on active_goal presence
- new_goal: Standalone tasks, new objectives, explicit requests → goal_description required

Intent precedence:
1. If query references prior conversation → thread_continuation
2. If query is conversational filler → chitchat
3. If query is new task → new_goal (DEFAULT when uncertain)

Required JSON shape:
{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "task_complexity": "chitchat"|"medium"|"complex",
  "chitchat_response": string|null,
  "reasoning": string
}
"""
```

### 3.4 Integration Flow

```
User Query
    ↓
SootheRunner._pre_stream_phase()
    ↓
UnifiedClassifier.classify_intent()  ← NEW: LLM-driven intent classification
    ↓
IntentClassification
    ├─ intent_type: chitchat → Direct response
    ├─ intent_type: thread_continuation → AgentLoop.run(intent=reuse)
    └─ intent_type: new_goal → GoalEngine.create_goal() + AgentLoop.run(intent=new)
```

### 3.5 Runner Integration

Update `_runner_phases.py`:

```python
# Phase 0: Intent Classification (NEW)
intent_result = await self._unified_classifier.classify_intent(
    query=input_text,
    recent_messages=recent_messages,
    active_goal_id=active_goal_id,  # From thread state
    thread_id=thread_id,
)

# Yield intent event for observability
yield ("intent", intent_result.model_dump())

# Branch based on intent
if intent_result.intent_type == "chitchat":
    # Direct response (no goal, no AgentLoop)
    yield ("final_response", intent_result.chitchat_response)
    return

elif intent_result.intent_type == "thread_continuation":
    # Reuse active goal or skip goal creation
    if intent_result.reuse_current_goal and active_goal_id:
        # Continue with existing goal
        goal_id = active_goal_id
    else:
        # Thread continuation without goal (pure conversation)
        goal_id = None
    # AgentLoop handles thread context continuation

elif intent_result.intent_type == "new_goal":
    # Create new goal via GoalEngine
    goal_description = intent_result.goal_description or input_text
    goal = await self._goal_engine.create_goal(
        description=goal_description,
        priority=50,
    )
    goal_id = goal.id
```

---

## 4. Implementation Steps

### Phase 1: Core Classification Logic

1. Add `IntentClassification` model to `unified_classifier.py`
2. Add `classify_intent()` method to `UnifiedClassifier`
3. Create LLM prompt with conversation context
4. Add fallback logic (default to new_goal if uncertain)
5. Add unit tests for intent classification

### Phase 2: Runner Integration

1. Update `_runner_phases.py` to call intent classifier
2. Add intent event emission for observability
3. Branch execution path based on intent_type
4. Pass intent to AgenticMixin

### Phase 3: AgentLoop Integration

1. Update `AgentLoop.run_with_progress()` signature to accept intent
2. Adjust iteration behavior for thread_continuation
3. Enhance working memory context for thread continuation
4. Skip goal lifecycle for thread_continuation queries

### Phase 4: GoalEngine Integration

1. Conditional goal creation based on intent
2. Thread continuation goal reuse logic
3. Update goal lifecycle logging with intent context

---

## 5. Testing Strategy

### 5.1 Unit Tests

Add to `tests/unit/core/test_unified_classifier.py`:

```python
class TestIntentClassification:
    """Test intent classification model and logic."""
    
    def test_intent_model_creation(self):
        intent = IntentClassification(
            intent_type="thread_continuation",
            reuse_current_goal=True,
            task_complexity="medium",
            reasoning="Query references prior result"
        )
        assert intent.intent_type == "thread_continuation"
        assert intent.reuse_current_goal == True
    
    def test_llm_intent_classification_chitchat(self):
        """LLM correctly classifies greetings as chitchat."""
        classifier = UnifiedClassifier(mock_fast_model)
        result = classifier.classify_intent("hello there!")
        assert result.intent_type == "chitchat"
        assert result.chitchat_response is not None
    
    def test_llm_intent_classification_thread_continuation(self):
        """LLM detects thread continuation from conversation context."""
        recent_messages = [
            HumanMessage("list all python files"),
            AIMessage("Found 42 .py files in the workspace...")
        ]
        result = classifier.classify_intent(
            "translate that to Spanish",
            recent_messages=recent_messages
        )
        assert result.intent_type == "thread_continuation"
        assert result.reuse_current_goal == True
    
    def test_llm_intent_classification_new_goal(self):
        """LLM detects new standalone task."""
        result = classifier.classify_intent("count all readme files")
        assert result.intent_type == "new_goal"
        assert result.goal_description is not None
```

### 5.2 Integration Tests

Add to `tests/integration/test_query_intent_flow.py`:

```python
async def test_thread_continuation_reuses_goal():
    """Thread continuation query reuses active goal."""
    runner = SootheRunner(config)
    
    # First query creates goal
    stream1 = runner.astream("count all readme files", thread_id="test-1")
    # ... consume stream, goal created
    
    # Second query (thread continuation) reuses goal
    stream2 = runner.astream("explain the result", thread_id="test-1")
    # ... should NOT create new goal, reuse existing
    
    # Verify no new goal created in GoalEngine
```

---

## 6. Configuration

Add to `config/config.yml`:

```yaml
performance:
  unified_classification: true
  classification_mode: "llm"
  
  # NEW: Intent classification settings
  intent_classification:
    enabled: true
    reuse_goal_threshold: 0.7  # Confidence threshold for goal reuse
    fallback_intent: "new_goal"  # Default when LLM uncertain
    provide_conversation_context: true
    max_context_messages: 8  # Recent messages for intent detection
```

---

## 7. Expected Impact

### Benefits

1. **Accurate intent detection**: Thread continuation queries no longer trigger unnecessary goal creation
2. **Goal lifecycle optimization**: Goals created only for truly new tasks
3. **Thread context awareness**: Follow-up actions properly reuse thread state
4. **LLM-driven accuracy**: No keyword heuristics, context-aware classification

### Metrics

- Goal creation rate reduction: ~30-50% (thread continuation queries)
- Classification latency: ~2-4s (same as current routing)
- Goal reuse accuracy: Target >85% for thread continuation queries

---

## 8. Migration Path

### Backward Compatibility

- Intent classification **optional** (disabled if no fast model)
- Fallback to current behavior (new_goal) if intent classification fails
- Existing routing tests remain unchanged

### Rollout

**Week 1**: Core classification logic + unit tests
**Week 2**: Runner integration + integration tests
**Week 3**: AgentLoop + GoalEngine integration
**Week 4**: Full system testing + verification

---

## 9. References

- RFC-201: AgentLoop Plan-Execute Loop
- RFC-609: Goal Context Management
- RFC-200: Autonomous Goal Management
- IG-225: GoalEngine Multi-Goal Enhancement
- UnifiedClassifier (`core/unified_classifier.py`)

---

**Implementation Status**: 🚧 Design phase complete, proceeding to Phase 1 implementation