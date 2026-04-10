# Implementation Guide: Performance Optimization

**Implementation**: 021
**Title**: Performance Optimization Implementation
**Status**: Draft
**Created**: 2026-03-16
**Related**: RFC-201
**Target Performance**: < 2 seconds average latency

## Overview

This guide implements the performance optimizations defined in RFC-201. The implementation is organized into three phases:

1. **Phase 1**: Foundation (query classification, conditional execution)
2. **Phase 2**: Advanced optimizations (parallel execution, caching)
3. **Phase 3**: Polish and monitoring

## Phase 1: Foundation Optimizations

**Target**: < 5 seconds average latency (3x improvement)

### Step 1: Add Query Complexity Classifier

**File**: `src/soothe/core/query_classifier.py` (new file)

```python
"""Query complexity classification for adaptive processing."""

from __future__ import annotations

import re
from typing import Literal

ComplexityLevel = Literal["trivial", "simple", "medium", "complex"]


class QueryClassifier:
    """Classify query complexity for adaptive processing.

    Uses fast heuristics to determine processing requirements.
    No LLM calls to maintain sub-millisecond latency.
    """

    _TRIVIAL_PATTERNS = [
        r'^(hi|hello|hey|thanks|thank you|ok|yes|no|got it)$',
        r'^(who|what|where|when)\s+(is|are|was|were)\s+\w+\s*\??$',
    ]

    _SIMPLE_PATTERNS = [
        r'^(read|show|list|display|cat)\s+\w+',  # Direct operations
        r'^(search|find|look up)\s+for\s+',  # Basic searches
    ]

    _COMPLEX_KEYWORDS = frozenset([
        "architect", "architecture", "design system", "migrate", "migration",
        "refactor", "redesign", "rewrite", "overhaul", "scale", "multi-phase",
        "roadmap", "strategy", "comprehensive", "end-to-end", "full-stack",
        "infrastructure", "system design",
    ])

    def __init__(
        self,
        trivial_word_threshold: int = 5,
        simple_word_threshold: int = 15,
        medium_word_threshold: int = 30,
    ):
        """Initialize the classifier with configurable thresholds.

        Args:
            trivial_word_threshold: Max words for trivial queries.
            simple_word_threshold: Max words for simple queries.
            medium_word_threshold: Max words for medium queries.
        """
        self._trivial_threshold = trivial_word_threshold
        self._simple_threshold = simple_word_threshold
        self._medium_threshold = medium_word_threshold

    def classify(self, query: str) -> ComplexityLevel:
        """Classify query complexity in < 1ms.

        Uses pattern matching and word count heuristics.
        No LLM calls to maintain sub-millisecond latency.

        Args:
            query: User input text.

        Returns:
            Complexity level: "trivial", "simple", "medium", or "complex".
        """
        if not query or not query.strip():
            return "simple"

        query_lower = query.lower().strip()
        word_count = len(query.split())

        # Check for complex keywords
        if any(kw in query_lower for kw in self._COMPLEX_KEYWORDS):
            return "complex"

        # Check for trivial patterns
        for pattern in self._TRIVIAL_PATTERNS:
            if re.match(pattern, query_lower):
                return "trivial"

        # Word count heuristics
        if word_count > self._medium_threshold:
            return "complex"
        if word_count > self._simple_threshold:
            return "medium"
        if word_count > self._trivial_threshold:
            # Check for simple patterns
            for pattern in self._SIMPLE_PATTERNS:
                if re.match(pattern, query_lower):
                    return "simple"
            return "medium"

        # Default to trivial for very short queries
        if word_count <= self._trivial_threshold:
            return "trivial"

        return "simple"
```

**Testing**: Create `tests/unit_tests/test_query_classifier.py`

```python
"""Tests for query complexity classifier."""

import pytest
from soothe.core.query_classifier import QueryClassifier


@pytest.fixture
def classifier():
    return QueryClassifier()


class TestQueryClassifier:
    def test_trivial_greetings(self, classifier):
        assert classifier.classify("hi") == "trivial"
        assert classifier.classify("hello") == "trivial"
        assert classifier.classify("hey") == "trivial"
        assert classifier.classify("thanks") == "trivial"

    def test_trivial_questions(self, classifier):
        assert classifier.classify("who is your father?") == "trivial"
        assert classifier.classify("what time is it?") == "trivial"

    def test_simple_operations(self, classifier):
        assert classifier.classify("read the config file") == "simple"
        assert classifier.classify("list files in directory") == "simple"

    def test_medium_tasks(self, classifier):
        assert classifier.classify("implement a function to parse JSON") == "medium"
        assert classifier.classify("debug the error in my code") == "medium"

    def test_complex_keywords(self, classifier):
        assert classifier.classify("architect a new system") == "complex"
        assert classifier.classify("refactor the authentication module") == "complex"
        assert classifier.classify("comprehensive review") == "complex"

    def test_word_count_thresholds(self, classifier):
        # Very short
        assert classifier.classify("hi there") == "trivial"

        # Medium length
        query_20_words = " ".join(["word"] * 20)
        assert classifier.classify(query_20_words) == "medium"

        # Long
        query_40_words = " ".join(["word"] * 40)
        assert classifier.classify(query_40_words) == "complex"
```

---

### Step 2: Integrate Classifier into SootheRunner

**File**: `src/soothe/core/runner.py`

**Changes**:

1. Import the classifier:

```python
from soothe.core.query_classifier import QueryClassifier, ComplexityLevel
```

2. Add classifier to `__init__`:

```python
def __init__(self, config: SootheConfig | None = None) -> None:
    # ... existing code ...
    self._classifier = QueryClassifier(
        trivial_word_threshold=config.performance.thresholds.trivial_words if config and hasattr(config, 'performance') else 5,
        simple_word_threshold=config.performance.thresholds.simple_words if config and hasattr(config, 'performance') else 15,
        medium_word_threshold=config.performance.thresholds.medium_words if config and hasattr(config, 'performance') else 30,
    )
```

3. Modify `_pre_stream` to classify and conditionally execute:

```python
async def _pre_stream(
    self,
    user_input: str,
    state: RunnerState,
) -> AsyncGenerator[StreamChunk, None]:
    """Run protocol pre-processing before the LangGraph stream."""
    from soothe.protocols.durability import ThreadMetadata

    # Classify query complexity
    complexity = self._classify_query(user_input)
    logger.info("Query classified as: %s", complexity)

    # Thread management (unchanged)
    requested_thread_id = state.thread_id
    try:
        thread_info = None
        if requested_thread_id:
            thread_info = await self._durability.resume_thread(requested_thread_id)
            yield _custom({"type": "soothe.thread.resumed", "thread_id": thread_info.thread_id})
        else:
            thread_info = await self._durability.create_thread(
                ThreadMetadata(policy_profile=self._config.policy_profile),
            )
            yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
        state.thread_id = thread_info.thread_id
        self._current_thread_id = thread_info.thread_id
    except KeyError:
        # ... existing fallback code ...
    except Exception:
        logger.debug("Thread creation failed, using generated ID", exc_info=True)

    if not state.thread_id:
        state.thread_id = requested_thread_id or _generate_thread_id()
        self._current_thread_id = state.thread_id

    # Context restoration (unchanged)
    if self._context and hasattr(self._context, "restore") and requested_thread_id:
        try:
            restored = await self._context.restore(state.thread_id)
            if restored:
                logger.info("Context restored for thread %s", state.thread_id)
        except Exception:
            logger.debug("Context restore failed", exc_info=True)

    protocols = self.protocol_summary()
    yield _custom(
        {
            "type": "soothe.thread.started",
            "thread_id": state.thread_id,
            "protocols": protocols,
        }
    )

    # Policy check (unchanged)
    if self._policy:
        try:
            from soothe.protocols.policy import PermissionSet

            decision = self._policy.check(
                ActionRequest(action_type="user_request", tool_name=None, tool_args={}),
                PolicyContext(
                    active_permissions=PermissionSet(frozenset()),
                    thread_id=state.thread_id,
                ),
            )
            yield _custom(
                {
                    "type": "soothe.policy.checked",
                    "action": "user_request",
                    "verdict": decision.verdict,
                    "profile": self._config.policy_profile,
                }
            )
            if decision.verdict == "deny":
                yield _custom(
                    {
                        "type": "soothe.policy.denied",
                        "action": "user_request",
                        "reason": decision.reason,
                        "profile": self._config.policy_profile,
                    }
                )
                return
        except Exception:
            logger.debug("Policy check failed", exc_info=True)

    # Memory recall - CONDITIONAL
    if self._memory and complexity in ("medium", "complex"):
        try:
            items = await self._memory.recall(user_input, limit=5)
            state.recalled_memories = items
            if self._context and items:
                for item in items:
                    await self._context.ingest(
                        ContextEntry(
                            source="memory",
                            content=item.content[:2000],
                            tags=["recalled_memory", *item.tags],
                            importance=item.importance,
                        )
                    )
            yield _custom(
                {
                    "type": "soothe.memory.recalled",
                    "count": len(items),
                    "query": user_input[:100],
                }
            )
        except Exception:
            logger.debug("Memory recall failed", exc_info=True)

    # Context projection - CONDITIONAL
    if self._context and complexity in ("medium", "complex"):
        try:
            projection = await self._context.project(user_input, token_budget=4000)
            state.context_projection = projection
            yield _custom(
                {
                    "type": "soothe.context.projected",
                    "entries": projection.total_entries,
                    "tokens": projection.token_count,
                }
            )
        except Exception:
            logger.debug("Context projection failed", exc_info=True)

    # Plan creation - ADAPTIVE
    if self._planner:
        try:
            capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
            context = PlanContext(
                recent_messages=[user_input],
                available_capabilities=capabilities,
                completed_steps=[],
            )

            # Use template for trivial/simple
            if complexity in ("trivial", "simple"):
                plan = self._get_template_plan(user_input, complexity)
            else:
                plan = await self._planner.create_plan(user_input, context)

            state.plan = plan
            self._current_plan = plan
            yield _custom(
                {
                    "type": "soothe.plan.created",
                    "goal": plan.goal,
                    "steps": [{"id": s.id, "description": s.description, "status": s.status} for s in plan.steps],
                }
            )
            if plan.steps:
                yield _custom(
                    {
                        "type": "soothe.plan.step_started",
                        "index": 0,
                        "description": plan.steps[0].description,
                    }
                )
        except Exception:
            logger.debug("Plan creation failed", exc_info=True)

def _classify_query(self, query: str) -> ComplexityLevel:
    """Classify query complexity for adaptive processing."""
    if not hasattr(self, '_classifier'):
        # Fallback if classifier not initialized
        return "simple"
    return self._classifier.classify(query)

def _get_template_plan(self, goal: str, complexity: ComplexityLevel) -> Plan:
    """Get template plan for trivial/simple queries."""
    from soothe.protocols.planner import Plan, PlanStep

    if complexity == "trivial":
        return Plan(
            goal=goal,
            steps=[PlanStep(id="step_1", description=goal, execution_hint="auto")],
        )

    # Simple: Try to match common patterns
    import re
    goal_lower = goal.lower()

    # Search pattern
    if re.match(r'^(search|find|look up)\s+', goal_lower):
        return Plan(
            goal=goal,
            steps=[
                PlanStep(id="step_1", description="Search for information", execution_hint="tool"),
                PlanStep(id="step_2", description="Summarize findings", execution_hint="auto"),
            ],
        )

    # Analysis pattern
    if re.match(r'^(analyze|analyse|review|examine)\s+', goal_lower):
        return Plan(
            goal=goal,
            steps=[
                PlanStep(id="step_1", description="Analyze the content", execution_hint="auto"),
                PlanStep(id="step_2", description="Provide insights", execution_hint="auto"),
            ],
        )

    # Default simple plan
    return Plan(
        goal=goal,
        steps=[PlanStep(id="step_1", description=goal, execution_hint="auto")],
    )
```

---

### Step 3: Add Configuration Options

**File**: `src/soothe/config.py`

Add new configuration fields:

```python
from typing import Literal

class ComplexityThresholds(BaseModel):
    """Query complexity classification thresholds."""
    trivial_words: int = 5
    simple_words: int = 15
    medium_words: int = 30


class PerformanceConfig(BaseModel):
    """Performance optimization configuration (RFC-201)."""
    enabled: bool = True
    complexity_detection: bool = True
    skip_memory_for_simple: bool = True
    skip_context_for_simple: bool = True
    template_planning: bool = True
    parallel_pre_stream: bool = True
    cache_size: int = 100
    log_timing: bool = False
    slow_query_threshold_ms: int = 3000
    thresholds: ComplexityThresholds = Field(default_factory=ComplexityThresholds)


class SootheConfig(BaseModel):
    # ... existing fields ...

    # Performance optimization settings (RFC-201)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
```

**File**: `config/config.yml`

Add performance section:

```yaml
# =============================================================================
# Performance Optimization
# =============================================================================

performance:
  # Enable adaptive processing based on query complexity
  adaptive_processing: true
  complexity_detection: true

  # Conditional execution (skip for trivial/simple queries)
  conditional_memory_recall: true
  conditional_context_projection: true

  # Template-based planning for simple queries
  template_planning: true

  # Monitoring
  log_timing: false
  slow_query_threshold_ms: 3000

  # Tuning (advanced)
  trivial_word_threshold: 5
  simple_word_threshold: 15
  medium_word_threshold: 30
```

---

### Step 4: Update AutoPlanner to Skip LLM Classification

**File**: `src/soothe/cognition/planning/router.py`

Modify `_route` method to remove LLM classification:

```python
async def _route(self, goal: str) -> Any:
    """Determine which planner to use - heuristics only.

    Note: LLM classification removed for performance (saves 500-1000ms).
    """
    goal_lower = goal.lower()

    # Explicit Claude request
    if any(kw in goal_lower for kw in _EXPLICIT_CLAUDE_KEYWORDS) and self._claude:
        logger.info("AutoPlanner: explicit Claude request")
        return self._claude

    # Heuristic classification (no LLM)
    level = self._heuristic_classify(goal)

    if level == "complex":
        return self._claude or self._subagent or self._direct
    if level == "medium":
        return self._subagent or self._direct

    # Default: use DirectPlanner for simple/ambiguous
    return self._direct or self._subagent
```

---

## Phase 2: Advanced Optimizations

**Target**: < 2 seconds average latency (additional 2x improvement)

### Step 5: Implement Parallel Pre-Stream Execution

**File**: `src/soothe/core/runner.py`

Add parallel execution method:

```python
async def _pre_stream_parallel_memory_context(
    self,
    user_input: str,
    complexity: ComplexityLevel,
) -> tuple[list[MemoryItem], ContextProjection | None]:
    """Run memory and context operations in parallel for medium/complex queries.

    Args:
        user_input: User query text.
        complexity: Query complexity level.

    Returns:
        Tuple of (memory_items, context_projection).
    """
    import asyncio

    if complexity not in ("medium", "complex"):
        return ([], None)

    tasks = []

    # Memory recall task
    if self._memory:
        tasks.append(self._memory.recall(user_input, limit=5))
    else:
        tasks.append(asyncio.sleep(0, result=[]))

    # Context projection task
    if self._context:
        tasks.append(self._context.project(user_input, token_budget=4000))
    else:
        tasks.append(asyncio.sleep(0, result=None))

    # Execute in parallel
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        memory_items = [] if isinstance(results[0], Exception) else results[0]
        context_projection = None if isinstance(results[1], Exception) else results[1]

        if isinstance(results[0], Exception):
            logger.debug("Memory recall failed in parallel execution", exc_info=results[0])
        if isinstance(results[1], Exception):
            logger.debug("Context projection failed in parallel execution", exc_info=results[1])

        return memory_items, context_projection
    except Exception:
        logger.debug("Parallel execution failed", exc_info=True)
        return ([], None)
```

Update `_pre_stream` to use parallel execution:

```python
# Replace memory recall and context projection sections with:

# Parallel memory recall and context projection
if complexity in ("medium", "complex") and self._config.performance_parallel_pre_stream:
    memory_items, context_projection = await self._pre_stream_parallel_memory_context(
        user_input, complexity
    )
    state.recalled_memories = memory_items
    state.context_projection = context_projection

    # Ingest memory into context
    if self._context and memory_items:
        for item in memory_items:
            try:
                await self._context.ingest(
                    ContextEntry(
                        source="memory",
                        content=item.content[:2000],
                        tags=["recalled_memory", *item.tags],
                        importance=item.importance,
                    )
                )
            except Exception:
                logger.debug("Memory ingestion failed", exc_info=True)

    # Emit events
    if memory_items:
        yield _custom(
            {
                "type": "soothe.memory.recalled",
                "count": len(memory_items),
                "query": user_input[:100],
            }
        )
    if context_projection:
        yield _custom(
            {
                "type": "soothe.context.projected",
                "entries": context_projection.total_entries,
                "tokens": context_projection.token_count,
            }
        )
else:
    # Sequential execution (existing code)
    # ... memory recall ...
    # ... context projection ...
```

Add to `SootheConfig`:

```python
performance_parallel_pre_stream: bool = True
```

---

### Step 6: Add Embedding Cache

**File**: `src/soothe/backends/memory/keyword.py` (or appropriate backend)

Add caching:

```python
from functools import lru_cache
from hashlib import sha256

class KeywordMemoryBackend:
    def __init__(self, *args, cache_size: int = 100, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_size = cache_size
        # Note: lru_cache doesn't work directly on instance methods
        # We'll use a cache dict instead
        self._embedding_cache: dict[str, list[float]] = {}
        self._cache_order: list[str] = []

    def _get_cached_embedding(self, text_hash: str) -> list[float] | None:
        """Retrieve cached embedding."""
        return self._embedding_cache.get(text_hash)

    def _cache_embedding(self, text_hash: str, embedding: list[float]) -> None:
        """Cache embedding with LRU eviction."""
        if text_hash in self._embedding_cache:
            return

        # Evict oldest if at capacity
        if len(self._embedding_cache) >= self._cache_size:
            oldest = self._cache_order.pop(0)
            self._embedding_cache.pop(oldest, None)

        # Add new
        self._embedding_cache[text_hash] = embedding
        self._cache_order.append(text_hash)

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Recall with embedding cache."""
        # If no embedding needed (keyword-only), skip cache
        if not self._use_embeddings:
            return await self._recall_keyword(query, limit)

        # Generate hash
        query_hash = sha256(query.encode()).hexdigest()

        # Try cache
        cached_embedding = self._get_cached_embedding(query_hash)
        if cached_embedding is not None:
            logger.debug("Embedding cache hit for query: %s", query[:50])
            return await self._search_with_embedding(cached_embedding, limit)

        # Generate embedding
        embedding = await self._generate_embedding(query)

        # Cache it
        self._cache_embedding(query_hash, embedding)

        # Search
        return await self._search_with_embedding(embedding, limit)
```

Add to `SootheConfig`:

```python
performance_embedding_cache_size: int = 100
```

---

### Step 7: Add Template Matching to DirectPlanner

**File**: `src/soothe/cognition/planning/direct.py`

Add template matching:

```python
class DirectPlanner:
    """PlannerProtocol implementation using a single LLM structured output call."""

    _PLAN_TEMPLATES = {
        "question": Plan(
            goal="",
            steps=[PlanStep(id="step_1", description="", execution_hint="auto")],
        ),
        "search": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Search for information", execution_hint="tool"),
                PlanStep(id="step_2", description="Summarize findings", execution_hint="auto"),
            ],
        ),
        "analysis": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Analyze the content", execution_hint="auto"),
                PlanStep(id="step_2", description="Provide insights", execution_hint="auto"),
            ],
        ),
        "implementation": Plan(
            goal="",
            steps=[
                PlanStep(id="step_1", description="Understand requirements", execution_hint="auto"),
                PlanStep(id="step_2", description="Implement the solution", execution_hint="tool"),
                PlanStep(id="step_3", description="Test and validate", execution_hint="tool"),
            ],
        ),
    }

    def __init__(self, model: Any, use_templates: bool = True) -> None:
        """Initialize the direct planner.

        Args:
            model: A langchain BaseChatModel instance supporting structured output.
            use_templates: Whether to use template matching (default: True).
        """
        self._model = model
        self._use_templates = use_templates

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan via single LLM call with structured output."""
        # Try template matching first
        if self._use_templates:
            template_plan = self._match_template(goal)
            if template_plan:
                logger.info("DirectPlanner: using template plan for: %s", goal[:50])
                return template_plan

        # Fall back to LLM
        structured_model = self._model.with_structured_output(Plan)
        prompt = self._build_plan_prompt(goal, context)
        try:
            plan: Plan = await structured_model.ainvoke(prompt)
        except Exception:
            logger.warning("Structured plan creation failed, using fallback")
            return Plan(
                goal=goal,
                steps=[PlanStep(id="step_1", description=goal)],
            )
        else:
            return plan

    def _match_template(self, goal: str) -> Plan | None:
        """Match goal to predefined template.

        Returns None if no match (will use LLM).
        """
        import re
        goal_lower = goal.lower()

        # Question patterns
        if re.match(r'^(who|what|where|when|why|how)\s+', goal_lower):
            plan = self._PLAN_TEMPLATES["question"].model_copy(deep=True)
            plan.goal = goal
            plan.steps[0].description = goal
            return plan

        # Search patterns
        if re.match(r'^(search|find|look up|google)\s+', goal_lower):
            plan = self._PLAN_TEMPLATES["search"].model_copy(deep=True)
            plan.goal = goal
            return plan

        # Analysis patterns
        if re.match(r'^(analyze|analyse|review|examine|investigate)\s+', goal_lower):
            plan = self._PLAN_TEMPLATES["analysis"].model_copy(deep=True)
            plan.goal = goal
            return plan

        # Implementation patterns
        if re.match(r'^(implement|create|build|write|develop)\s+', goal_lower):
            plan = self._PLAN_TEMPLATES["implementation"].model_copy(deep=True)
            plan.goal = goal
            return plan

        return None
```

---

## Phase 3: Polish and Monitoring

### Step 8: Add Performance Metrics Logging

**File**: `src/soothe/core/runner.py`

Add timing wrapper:

```python
from time import perf_counter
from contextlib import asynccontextmanager

@asynccontextmanager
async def _timed_phase(phase_name: str, state: RunnerState):
    """Context manager to log phase timing."""
    start = perf_counter()
    try:
        yield
    finally:
        duration_ms = int((perf_counter() - start) * 1000)
        if hasattr(self._config, 'performance_log_timing') and self._config.performance_log_timing:
            logger.info(
                "Phase '%s' completed in %dms (thread=%s)",
                phase_name,
                duration_ms,
                state.thread_id,
            )

            # Emit performance event
            yield _custom({
                "type": "soothe.performance.phase_completed",
                "phase": phase_name,
                "duration_ms": duration_ms,
                "thread_id": state.thread_id,
            })
```

Use in `_pre_stream`:

```python
async def _pre_stream(self, user_input: str, state: RunnerState):
    async with _timed_phase("pre_stream", state):
        # ... existing code ...
```

---

### Step 9: Add Feature Flags

**File**: `config/config.yml`

```yaml
performance:
  # Feature flags for gradual rollout
  phase1_enabled: true   # Query classification, conditional execution
  phase2_enabled: false  # Parallel execution, caching (enable after testing)
  phase3_enabled: false  # Advanced monitoring (enable in production)
```

**File**: `src/soothe/config.py`

```python
class SootheConfig(BaseModel):
    # ... existing ...

    # Performance optimization (RFC-201)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
```

**File**: `src/soothe/core/runner.py`

Use the enabled flag:

```python
# In _pre_stream
if self._config.performance.enabled and self._config.performance.complexity_detection:
    complexity = self._classify_query(user_input)
    # Use conditional execution based on complexity
else:
    complexity = "medium"  # Default to existing behavior
```

---

## Testing Strategy

### Unit Tests

1. `tests/unit_tests/test_query_classifier.py` - Test classification accuracy
2. `tests/unit_tests/test_template_planning.py` - Test template matching
3. `tests/unit_tests/test_parallel_execution.py` - Test concurrent operations

### Integration Tests

1. `tests/integration_tests/test_performance.py`:

```python
import pytest
import asyncio
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig

@pytest.mark.asyncio
async def test_trivial_query_latency():
    """Test that trivial queries complete in < 500ms."""
    config = SootheConfig()
    runner = SootheRunner(config)

    import time
    start = time.perf_counter()

    events = []
    async for chunk in runner.astream("hello"):
        events.append(chunk)

    duration_ms = (time.perf_counter() - start) * 1000

    assert duration_ms < 500, f"Trivial query took {duration_ms}ms"
    assert len(events) > 0

@pytest.mark.asyncio
async def test_simple_query_latency():
    """Test that simple queries complete in < 1s."""
    config = SootheConfig()
    runner = SootheRunner(config)

    import time
    start = time.perf_counter()

    events = []
    async for chunk in runner.astream("read the config file"):
        events.append(chunk)

    duration_ms = (time.perf_counter() - start) * 1000

    assert duration_ms < 1000, f"Simple query took {duration_ms}ms"

@pytest.mark.asyncio
async def test_medium_query_latency():
    """Test that medium queries complete in < 2s."""
    config = SootheConfig()
    runner = SootheRunner(config)

    import time
    start = time.perf_counter()

    events = []
    async for chunk in runner.astream("implement a function to parse JSON"):
        events.append(chunk)

    duration_ms = (time.perf_counter() - start) * 1000

    assert duration_ms < 2000, f"Medium query took {duration_ms}ms"
```

### Performance Benchmarks

Create `scripts/benchmark_performance.py`:

```python
"""Performance benchmarking script."""

import asyncio
import time
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig

QUERIES = {
    "trivial": [
        "hello",
        "thanks",
        "who are you?",
    ],
    "simple": [
        "read config.yml",
        "list files",
        "search for python",
    ],
    "medium": [
        "implement a function to parse JSON",
        "debug the error in my code",
        "write tests for auth",
    ],
    "complex": [
        "refactor the authentication system",
        "design a microservices architecture",
        "comprehensive security review",
    ],
}

async def benchmark_query(runner: SootheRunner, query: str) -> float:
    """Benchmark a single query."""
    start = time.perf_counter()
    async for _ in runner.astream(query):
        pass
    return (time.perf_counter() - start) * 1000

async def main():
    config = SootheConfig()
    runner = SootheRunner(config)

    results = {}

    for complexity, queries in QUERIES.items():
        latencies = []
        for query in queries:
            latency = await benchmark_query(runner, query)
            latencies.append(latency)
            print(f"{complexity:10s} | {latency:6.0f}ms | {query}")

        avg = sum(latencies) / len(latencies)
        results[complexity] = {
            "avg_ms": avg,
            "min_ms": min(latencies),
            "max_ms": max(latencies),
        }

    print("\n=== Summary ===")
    for complexity, stats in results.items():
        print(f"{complexity:10s}: avg={stats['avg_ms']:.0f}ms, min={stats['min_ms']:.0f}ms, max={stats['max_ms']:.0f}ms")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Rollout Plan

### Week 1: Phase 1 Testing
1. Enable Phase 1 optimizations in dev environment
2. Run unit tests and integration tests
3. Monitor performance metrics
4. Fix any issues

### Week 2: Phase 1 Staging
1. Enable Phase 1 in staging environment
2. User acceptance testing
3. Performance benchmarking
4. Quality validation

### Week 3: Phase 1 Production
1. Enable Phase 1 in production with feature flag
2. Monitor performance and quality metrics
3. Collect user feedback

### Week 4-5: Phase 2 Development
1. Implement parallel execution
2. Add caching
3. Add template matching
4. Unit and integration testing

### Week 6: Phase 2 Staging
1. Enable Phase 2 in staging
2. Performance validation
3. Quality testing

### Week 7: Phase 2 Production
1. Enable Phase 2 in production
2. Monitor and optimize

---

## Success Criteria

### Performance Targets

- ✅ Trivial queries: < 500ms (P90)
- ✅ Simple queries: < 1s (P90)
- ✅ Medium queries: < 2s (P90)
- ✅ Complex queries: < 3s (P90)
- ✅ No quality regression for complex queries

### Quality Targets

- ✅ Classification accuracy > 90%
- ✅ Template acceptance rate > 95%
- ✅ Cache hit rate > 30% (after warm-up)

### Monitoring

- ✅ Performance metrics logged
- ✅ Slow query alerts configured
- ✅ Dashboard created (Grafana optional)

---

## Rollback Procedure

If issues arise:

1. **Immediate**: Disable feature flag
   ```yaml
   performance:
     phase1_enabled: false
     phase2_enabled: false
   ```

2. **Verify**: Restart daemon/TUI

3. **Monitor**: Check logs for errors

4. **Investigate**: Analyze performance metrics

5. **Fix**: Implement fix, test, re-enable

---

## Future Enhancements

1. **ML-based classifier**: Train lightweight model for better accuracy
2. **Predictive caching**: Pre-load resources for predicted next queries
3. **Adaptive thresholds**: Dynamically adjust based on usage patterns
4. **A/B testing**: Compare optimization strategies

---

## References

- RFC-201: Request Processing Workflow and Performance Optimization
- RFC-500: CLI TUI Architecture Design
- Performance benchmarks: `scripts/benchmark_performance.py`
- Monitoring dashboard: `scripts/performance_dashboard.py` (optional)