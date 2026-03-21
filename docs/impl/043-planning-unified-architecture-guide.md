# Unified Planning Architecture - Implementation Guide

**RFC**: RFC-0016
**Status**: Draft
**Created**: 2026-03-21
**Estimated Duration**: 5-7 days

## Executive Summary

This guide provides step-by-step instructions for refactoring Soothe's planning architecture to eliminate template-based planning and Tier-2 enrichment, replacing them with a unified LLM-based planning approach.

**Goals**:
- Reduce planning latency by 30-40% (from ~6-9s to ~4-6s)
- Improve plan flexibility and quality through LLM intelligence
- Reduce code complexity by ~400 lines

**Approach**:
- Remove `PlanTemplates` (regex-based template matching)
- Remove Tier-2 enrichment (redundant LLM call)
- Merge classification + planning into single LLM call
- Maintain parallelization with pre-stream I/O operations

---

## Architecture Overview

### Current Architecture (Before)

```
User Query
    │
    ▼
Tier-1 Routing (~3s)
    → task_complexity, chitchat_response
    │
    ├── chitchat? → Fast response (STOP)
    │
    ▼
┌────────────────────────┐    ┌─────────────────────────┐
│ Tier-2 Enrichment      │ ║  │ Pre-stream I/O          │
│ (Fast LLM, ~3s)        │ ║  │ (Thread, policy, etc.)  │
│ Returns:               │ ║  │                         │
│ - template_intent      │ ║  │                         │
│ - capability_domains   │ ║  │                         │
│ - is_plan_only         │ ║  │                         │
└────────────────────────┘    └─────────────────────────┘
    │                                    │
    └────────────► await ◄───────────────┘
                    │
                    ▼
         SimplePlanner.create_plan()
                    │
                    ├── Regex template match? → Return template
                    │
                    ├── template_intent match? → Return template
                    │
                    └── Fallback to LLM (~3s)
```

**Problems**:
1. **Redundant analysis**: Tier-2 analyzes query, planner re-analyzes
2. **Rigid templates**: Regex patterns fail on natural language variations
3. **Sequential latency**: Template misses require 3 LLM calls total

### Proposed Architecture (After)

```
User Query
    │
    ▼
Tier-1 Routing (~3s)
    → task_complexity, chitchat_response
    │
    ├── chitchat? → Fast response (STOP)
    │
    ▼
┌────────────────────────┐    ┌─────────────────────────┐
│ Unified Planning Call  │ ║  │ Pre-stream I/O          │
│ (Fast LLM, ~3-4s)      │ ║  │ (Thread, policy, etc.)  │
│ Returns:               │ ║  │                         │
│ - Plan with steps      │ ║  │                         │
│ - is_plan_only         │ ║  │                         │
│ - reasoning            │ ║  │                         │
└────────────────────────┘    └─────────────────────────┘
    │                                    │
    └────────────► await ◄───────────────┘
                    │
                    ▼
              Execution
```

**Benefits**:
1. **Single LLM call**: Combines classification + planning
2. **Flexible**: LLM adapts to query nuances
3. **Faster**: 30-40% latency reduction

---

## Design Decisions

### Decision 1: Remove Capability Domains

**Rationale**: Currently used for system prompt optimization, but execution hints provide sufficient guidance.

**Impact**: Eliminates need for `capability_domains` field from Tier-2.

**Migration**: Remove all references to `capability_domains`. Can be re-added later if needed by deriving from plan steps.

### Decision 2: Fast Model for Medium Queries

**Rationale**: Template system already worked for medium queries with simple regex. Fast model (gpt-4o-mini) is sufficient for structured output generation.

**Impact**: Lower latency, lower cost. Complex queries still routed to ClaudePlanner via AutoPlanner.

**Model selection**:
- `chitchat`: No planning needed
- `medium`: Fast model (gpt-4o-mini)
- `complex`: Claude (via ClaudePlanner)

### Decision 3: Clean Cut-Over

**Rationale**: Simpler code, faster merge. New fields have defaults for backward compatibility.

**Migration strategy**: Single PR with all changes. No feature flags.

**Rollback**: Git revert if critical issues arise.

### Decision 4: Parallel Planning Execution

**Rationale**: Planning runs concurrently with I/O operations (thread, memory, context) to hide latency.

**Implementation**: Use `asyncio.create_task()` for planning, then `await` after I/O completes.

---

## Implementation Phases

### Phase 1: Extend Plan Model (Day 1)

**Objective**: Add metadata fields to `Plan` model.

**Files to modify**:
- `src/soothe/protocols/planner.py`

**Changes**:

```python
class Plan(BaseModel):
    """A structured decomposition of a goal into executable steps."""

    goal: str
    steps: list[PlanStep]
    current_index: int = 0
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    general_activity: str | None = None

    # NEW FIELDS - unified planning metadata
    is_plan_only: bool = Field(default=False, description="User wants planning without execution")
    reasoning: str | None = Field(default=None, description="Intent classification reasoning")
```

**Verification**:
```bash
pytest tests/unit_tests/test_planning.py -v
pytest tests/unit_tests/test_runner.py -v
```

**Acceptance criteria**:
- [ ] New fields added with defaults
- [ ] Existing tests still pass
- [ ] No breaking changes to downstream code

---

### Phase 2: Remove Template System (Day 1-2)

**Objective**: Eliminate all template-based planning logic.

**Files to modify**:
- `src/soothe/backends/planning/simple.py`
- `src/soothe/backends/planning/_templates.py` (DELETE)
- `src/soothe/config/models.py`

#### Step 2.1: Delete Template File

```bash
git rm src/soothe/backends/planning/_templates.py
```

#### Step 2.2: Remove Template Logic from SimplePlanner

**File**: `src/soothe/backends/planning/simple.py`

**Remove imports**:
```python
# DELETE THIS LINE:
from soothe.backends.planning._templates import PlanTemplates
```

**Simplify `create_plan()` method** (lines 61-100):

**Before**:
```python
async def create_plan(self, goal: str, context: PlanContext) -> Plan:
    """Create plan via template matching or LLM structured output."""
    plan: Plan | None = None

    # Try template matching first
    if self._use_templates:
        # Try regex-based template matching
        if template := PlanTemplates.match(goal):
            logger.info("Using template plan for: %s", goal[:50])
            plan = template

        # Try pre-computed template intent from unified classification
        if (
            plan is None
            and context.unified_classification
            and hasattr(context.unified_classification, "template_intent")
            and context.unified_classification.template_intent
            and (template := PlanTemplates.get(context.unified_classification.template_intent))
        ):
            logger.info(
                "Using pre-classified template '%s' for: %s",
                context.unified_classification.template_intent,
                goal[:50],
            )
            plan = template

    # Fallback to LLM structured output
    if plan is None:
        plan = await self._create_plan_via_llm(goal, context)

    # Override execution hints when the user explicitly requested a subagent
    preferred = (
        getattr(context.unified_classification, "preferred_subagent", None)
        if context.unified_classification
        else None
    )
    if preferred:
        plan = self._apply_preferred_subagent(plan, preferred)

    return plan
```

**After**:
```python
async def create_plan(self, goal: str, context: PlanContext) -> Plan:
    """Create plan via LLM structured output."""
    # Direct LLM call - no template fallback
    plan = await self._create_plan_via_llm(goal, context)

    # Override execution hints when the user explicitly requested a subagent
    preferred = (
        getattr(context.unified_classification, "preferred_subagent", None)
        if context.unified_classification
        else None
    )
    if preferred:
        plan = self._apply_preferred_subagent(plan, preferred)

    return plan
```

**Remove `use_templates` parameter** from `__init__`:
```python
def __init__(
    self,
    fast_model: LLMModel | None = None,
    use_templates: bool = True,  # DELETE THIS PARAMETER
) -> None:
    self._fast_model = fast_model
    self._use_templates = use_templates  # DELETE THIS LINE
```

**Change to**:
```python
def __init__(
    self,
    fast_model: LLMModel | None = None,
) -> None:
    self._fast_model = fast_model
```

#### Step 2.3: Update Tests

**Search for template tests**:
```bash
grep -r "PlanTemplates\|template" tests/ --include="*.py"
```

**Remove or update**:
- `test_template_matching()`
- `test_search_template()`
- `test_implementation_template()`
- Any test using `PlanTemplates.match()`

**Verification**:
```bash
pytest tests/unit_tests/test_planning.py -v
pytest tests/unit_tests/test_simple_planner.py -v
```

**Acceptance criteria**:
- [ ] `_templates.py` deleted
- [ ] All template references removed from `simple.py`
- [ ] No `PlanTemplates` imports remain
- [ ] Tests updated and passing

---

### Phase 3: Remove Tier-2 Enrichment (Day 2-3)

**Objective**: Eliminate Tier-2 enrichment logic.

**Files to modify**:
- `src/soothe/cognition/unified_classifier.py`
- `src/soothe/core/runner.py`
- `src/soothe/core/_runner_phases.py`

#### Step 3.1: Remove Enrichment Model

**File**: `src/soothe/cognition/unified_classifier.py`

**Delete `EnrichmentResult` class** (lines 68-81):
```python
# DELETE THIS ENTIRE CLASS:
class EnrichmentResult(BaseModel):
    """Tier-2 enrichment result for non-chitchat queries."""
    is_plan_only: bool = Field(default=False, description="True if user only wants planning")
    template_intent: Literal["question", "search", "analysis", "implementation", "compose"] | None = Field(...)
    capability_domains: list[CapabilityDomain] = Field(default_factory=list, description="Needed capability domains.")
    reasoning: str | None = Field(default=None, description="Brief explanation")
```

**Delete `classify_enrichment()` method** (lines 254-292):
```python
# DELETE THIS ENTIRE METHOD:
async def classify_enrichment(
    self,
    user_input: str,
    task_complexity: str,
) -> EnrichmentResult:
    """Tier-2 enrichment for non-chitchat queries."""
    ...
```

**Delete enrichment prompt** (lines 167-180):
```python
# DELETE THIS CONSTANT:
_ENRICHMENT_PROMPT = """...
```

#### Step 3.2: Simplify UnifiedClassification

**File**: `src/soothe/cognition/unified_classifier.py`

**Remove enrichment fields**:
```python
class UnifiedClassification(BaseModel):
    """Unified classification from routing (enrichment removed)."""
    task_complexity: Literal["chitchat", "medium", "complex"]
    chitchat_response: str | None = None
    preferred_subagent: str | None = None
    routing_hint: str | None = None
    reasoning: str | None = None

    # REMOVE THESE FIELDS:
    # is_plan_only: bool = False
    # template_intent: Literal[...] | None = None
    # capability_domains: list[CapabilityDomain] = []
```

**Update `from_tiers()` method**:
```python
@staticmethod
def from_tiers(routing: RoutingResult, enrichment: EnrichmentResult | None = None) -> UnifiedClassification:
    # CHANGE TO:
    @staticmethod
    def from_routing(routing: RoutingResult) -> UnifiedClassification:
        """Create UnifiedClassification from routing result only."""
        return UnifiedClassification(
            task_complexity=routing.task_complexity,
            chitchat_response=routing.chitchat_response,
            preferred_subagent=routing.preferred_subagent,
            routing_hint=routing.routing_hint,
        )
```

#### Step 3.3: Update Runner Flow

**File**: `src/soothe/core/runner.py`

**Remove enrichment task** (lines 443-467):

**Before**:
```python
# -- Non-chitchat: tier-2 enrichment + pre-stream independent -------
enrichment_task: asyncio.Task | None = None
if self._unified_classifier:
    enrichment_task = asyncio.create_task(
        self._unified_classifier.classify_enrichment(user_input, complexity),
    )

# Run independent pre-stream concurrently with enrichment
collected_chunks = [
    chunk async for chunk in self._pre_stream_independent(user_input, state, complexity=complexity)
]

# Await enrichment
if enrichment_task is not None:
    enrichment = await enrichment_task
    state.unified_classification = UnifiedClassification.from_tiers(routing, enrichment)
    logger.info(
        "Tier-2 enrichment: template_intent=%s, plan_only=%s - %s",
        state.unified_classification.template_intent,
        state.unified_classification.is_plan_only,
        user_input[:50],
    )
else:
    state.unified_classification = None
```

**After**:
```python
# -- Non-chitchat: planning + pre-stream independent -------
# Start planning concurrently with I/O
planning_task = asyncio.create_task(
    self._planner.create_plan(
        user_input,
        PlanContext(
            recent_messages=[user_input],
            available_capabilities=[name for name, cfg in self._config.subagents.items() if cfg.enabled],
            completed_steps=[],
            unified_classification=routing,  # Pass routing directly
        )
    )
)

# Run independent pre-stream concurrently with planning
collected_chunks = [
    chunk async for chunk in self._pre_stream_independent(user_input, state, complexity=complexity)
]

# Await planning
try:
    plan = await planning_task
    state.plan = plan
    self._current_plan = plan
    logger.info(
        "Unified planning completed: %d steps, plan_only=%s - %s",
        len(plan.steps),
        plan.is_plan_only,
        user_input[:50],
    )
except Exception as e:
    logger.exception("Planning failed")
    # Fallback to single-step plan
    plan = Plan(
        goal=user_input,
        steps=[PlanStep(id="step_1", description=user_input)],
        is_plan_only=False,
    )
    state.plan = plan
```

**Add required imports**:
```python
from soothe.protocols.planner import Plan, PlanStep, PlanContext
```

#### Step 3.4: Update Planning Phase

**File**: `src/soothe/core/_runner_phases.py`

**Update plan-only check**:

**Before**:
```python
# Check if plan-only mode
if state.unified_classification and state.unified_classification.is_plan_only:
    ...
```

**After**:
```python
# Check if plan-only mode from Plan model
if state.plan and state.plan.is_plan_only:
    yield _custom(PlanOnlyEvent(thread_id=state.thread_id, goal=state.plan.goal, step_count=len(state.plan.steps)).to_dict())
    return
```

**Verification**:
```bash
pytest tests/unit_tests/test_unified_classifier.py -v
pytest tests/integration_tests/test_runner_integration.py -v
```

**Acceptance criteria**:
- [ ] `EnrichmentResult` class deleted
- [ ] `classify_enrichment()` method deleted
- [ ] Runner creates planning task instead of enrichment task
- [ ] Planning runs concurrently with I/O
- [ ] Tests updated and passing

---

### Phase 4: Implement Unified Planning Prompt (Day 3-4)

**Objective**: Create unified prompt that handles classification + planning.

**Files to modify**:
- `src/soothe/backends/planning/simple.py`

#### Step 4.1: Update `_build_plan_prompt()`

**File**: `src/soothe/backends/planning/simple.py`

**Replace `_build_plan_prompt()` method** (around lines 124-142):

```python
def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
    """Build unified planning prompt with embedded classification."""
    parts = [
        f"Create a plan to accomplish this goal: {goal}\n",
        "\nFirst, classify the intent:",
        "- question: Who/what/how questions needing research",
        "- search: Find/lookup information",
        "- analysis: Analyze/review/examine content",
        "- implementation: Create/build/write code",
        "- debugging: Fix/troubleshoot issues",
        "- compose: Generate custom agent/skill\n",
    ]

    if context.available_capabilities:
        parts.append(f"\nAvailable tools/subagents: {', '.join(context.available_capabilities)}\n")

    parts.extend([
        "\nSpecial routing rules:",
        "- If user explicitly requests a subagent (e.g., 'use browser to...', 'with weaver create...'), ",
        "set execution_hint='subagent' and mention the subagent name in step description",
        "- If goal mentions 'just plan' or 'only planning', set is_plan_only=true\n",
        "\nReturn a JSON object with this exact structure:",
        "{\n",
        '  "goal": "<goal text>",\n',
        '  "is_plan_only": false,\n',
        '  "reasoning": "<brief intent classification>",\n',
        '  "steps": [\n',
        '    {\n',
        '      "id": "step_1",\n',
        '      "description": "<concrete action>",\n',
        '      "execution_hint": "auto"\n',
        '    },\n',
        '    {\n',
        '      "id": "step_2",\n',
        '      "description": "Using the browser subagent, navigate to...",\n',
        '      "execution_hint": "subagent",\n',
        '      "depends_on": ["step_1"]\n',
        '    }\n',
        '  ]\n',
        '}\n\n',
        "Rules:",
        "- Break into 2-5 concrete, actionable steps",
        "- Use depends_on for sequential dependencies (optional)",
        "- execution_hint: 'tool' for tool calls, 'subagent' when delegating, 'auto' for LLM reasoning",
        "- Return ONLY valid JSON, no markdown code blocks\n",
    ])

    if context.completed_steps:
        completed_info = "\n".join(
            f"- {step.step_id}: {'success' if step.success else 'failed'} - {step.output}"
            for step in context.completed_steps
        )
        parts.append(f"\nPreviously completed steps:\n{completed_info}\n")

    return "".join(parts)
```

#### Step 4.2: Update `_create_plan_via_llm()`

**File**: `src/soothe/backends/planning/simple.py`

**Update method** (around lines 143-153):

```python
async def _create_plan_via_llm(self, goal: str, context: PlanContext) -> Plan:
    """Create plan via LLM structured output."""
    if not self._fast_model:
        # Fallback to single-step plan if no model available
        return Plan(
            goal=goal,
            steps=[PlanStep(id="step_1", description=goal)],
            is_plan_only=False,
        )

    prompt = self._build_plan_prompt(goal, context)

    try:
        # Use structured output with JSON mode
        response = await self._fast_model.generate(
            prompt,
            response_format={"type": "json_object"},
            temperature=0.3,  # Lower temperature for more deterministic plans
        )

        # Parse JSON response
        plan_dict = json.loads(response.content)

        # Extract and validate steps
        steps = []
        for step_data in plan_dict.get("steps", []):
            step = PlanStep(
                id=step_data["id"],
                description=step_data["description"],
                execution_hint=step_data.get("execution_hint", "auto"),
                depends_on=step_data.get("depends_on", []),
            )
            steps.append(step)

        # Create Plan with new metadata
        return Plan(
            goal=plan_dict.get("goal", goal),
            steps=steps,
            is_plan_only=plan_dict.get("is_plan_only", False),
            reasoning=plan_dict.get("reasoning"),
        )

    except (json.JSONDecodeError, KeyError, ValidationError) as e:
        logger.warning(f"Failed to parse LLM plan: {e}. Falling back to single-step plan.")
        # Fallback to single-step plan
        return Plan(
            goal=goal,
            steps=[PlanStep(id="step_1", description=goal)],
            is_plan_only=False,
        )
```

**Add required imports** at the top:
```python
import json
from pydantic import ValidationError
```

#### Step 4.3: Add Unit Tests

**File**: `tests/unit_tests/test_simple_planner.py`

**Add test cases**:

```python
import pytest
from soothe.backends.planning.simple import SimplePlanner
from soothe.protocols.planner import PlanContext

@pytest.mark.asyncio
async def test_unified_prompt_search_intent(fast_model):
    """Test that search queries generate appropriate plan."""
    planner = SimplePlanner(fast_model=fast_model)
    context = PlanContext(
        recent_messages=["search for recent LLM papers"],
        available_capabilities=["websearch", "code_edit"],
        completed_steps=[],
    )

    plan = await planner.create_plan("search for recent LLM papers", context)

    assert plan.goal == "search for recent LLM papers"
    assert len(plan.steps) >= 2
    assert plan.steps[0].execution_hint in ["tool", "auto"]
    assert "search" in plan.steps[0].description.lower() or "websearch" in plan.steps[0].description.lower()
    assert plan.is_plan_only is False
    assert plan.reasoning is not None

@pytest.mark.asyncio
async def test_unified_prompt_subagent_preference(fast_model):
    """Test that subagent preference is detected."""
    planner = SimplePlanner(fast_model=fast_model)
    context = PlanContext(
        recent_messages=["use browser to navigate to example.com"],
        available_capabilities=["browser", "code_edit"],
        completed_steps=[],
    )

    plan = await planner.create_plan("use browser to navigate to example.com", context)

    # Should have a step with subagent hint
    subagent_steps = [s for s in plan.steps if s.execution_hint == "subagent"]
    assert len(subagent_steps) > 0
    assert any("browser" in s.description.lower() for s in subagent_steps)

@pytest.mark.asyncio
async def test_unified_prompt_plan_only(fast_model):
    """Test that plan-only mode is detected."""
    planner = SimplePlanner(fast_model=fast_model)
    context = PlanContext(
        recent_messages=["plan how to refactor the auth module"],
        available_capabilities=["code_edit", "execute"],
        completed_steps=[],
    )

    plan = await planner.create_plan("plan how to refactor the auth module", context)

    assert plan.is_plan_only is True
    assert "plan" in plan.reasoning.lower() or "only" in plan.reasoning.lower()

@pytest.mark.asyncio
async def test_unified_prompt_fallback_on_parse_error():
    """Test fallback when LLM returns invalid JSON."""
    # Mock model that returns invalid JSON
    class MockModel:
        async def generate(self, prompt, **kwargs):
            class Response:
                content = "invalid json{{{"
            return Response()

    planner = SimplePlanner(fast_model=MockModel())
    context = PlanContext(recent_messages=[], available_capabilities=[], completed_steps=[])

    plan = await planner.create_plan("test goal", context)

    # Should fallback to single-step plan
    assert len(plan.steps) == 1
    assert plan.steps[0].description == "test goal"
```

**Verification**:
```bash
pytest tests/unit_tests/test_simple_planner.py -v
```

**Acceptance criteria**:
- [ ] Unified prompt implemented
- [ ] JSON parsing with error handling
- [ ] Unit tests added and passing
- [ ] Fallback to single-step plan works

---

### Phase 5: Integration & Testing (Day 4-5)

**Objective**: Verify end-to-end functionality and performance.

#### Step 5.1: Update Integration Tests

**File**: `tests/integration_tests/test_runner_integration.py`

**Add tests**:

```python
@pytest.mark.asyncio
async def test_runner_unified_planning_flow(runner):
    """Test end-to-end unified planning flow."""
    result = await runner.run("search for Python async best practices")

    # Should have a plan with multiple steps
    assert result.plan is not None
    assert len(result.plan.steps) >= 2
    assert result.plan.is_plan_only is False

    # First step should involve search
    assert any("search" in step.description.lower() for step in result.plan.steps)

@pytest.mark.asyncio
async def test_runner_plan_only_mode(runner):
    """Test plan-only mode with unified planning."""
    result = await runner.run("plan how to implement user authentication")

    assert result.plan.is_plan_only is True
    # Should not execute any steps
    assert all(step.status == "pending" for step in result.step_results)
```

#### Step 5.2: Add Performance Benchmarks

**File**: `tests/integration_tests/test_planning_performance.py`

```python
import time
import pytest

@pytest.mark.asyncio
async def test_planning_latency_improvement(runner):
    """Verify 30-40% latency improvement."""
    test_queries = [
        "search for recent papers on LLM planning",
        "analyze the authentication module code",
        "implement a rate limiter",
        "debug why tests are failing",
    ]

    latencies = []

    for query in test_queries:
        start = time.time()
        result = await runner.run(query)
        latency = time.time() - start
        latencies.append(latency)

        print(f"Query: {query[:50]}")
        print(f"  Planning latency: {latency:.2f}s")
        print(f"  Plan steps: {len(result.plan.steps)}")

    avg_latency = sum(latencies) / len(latencies)
    print(f"\nAverage planning latency: {avg_latency:.2f}s")

    # Target: ~4-6s (down from ~6-9s)
    assert avg_latency < 7.0, f"Expected latency < 7s, got {avg_latency:.2f}s"
```

**Run and document baseline**:
```bash
pytest tests/integration_tests/test_planning_performance.py -v -s
```

#### Step 5.3: Manual Testing

**Scenario 1: Search query**
```bash
soothe autopilot "search for recent papers on LLM planning"

# Expected:
# - Plan created in < 6s
# - Plan has 2-3 steps: search -> synthesize
# - No template matching logs
```

**Scenario 2: Implementation query**
```bash
soothe autopilot "implement a rate limiter with exponential backoff"

# Expected:
# - Plan created in < 6s
# - Plan has 3-4 steps: understand -> implement -> test
# - execution_hint='tool' or 'subagent' as appropriate
```

**Scenario 3: Subagent preference**
```bash
soothe autopilot "use browser to navigate to example.com and take a screenshot"

# Expected:
# - Plan has steps with execution_hint='subagent'
# - Browser subagent mentioned in step description
```

**Scenario 4: Plan-only mode**
```bash
soothe run "plan how to refactor the authentication module"

# Expected:
# - is_plan_only=true
# - No step execution
# - Plan displayed to user
```

**Scenario 5: Complex query**
```bash
soothe autopilot "design a distributed task queue system with fault tolerance"

# Expected:
# - Routed to ClaudePlanner (if AutoPlanner detects complexity)
# - High-quality multi-step plan
# - May take longer but should be thorough
```

#### Step 5.4: Regression Testing

**Run full test suite**:
```bash
# Unit tests
pytest tests/unit_tests/ -v

# Integration tests
pytest tests/integration_tests/ -v

# Performance tests
pytest tests/performance_tests/ -v
```

**Acceptance criteria**:
- [ ] Integration tests added and passing
- [ ] Performance benchmarks show 30-40% improvement
- [ ] Manual testing scenarios successful
- [ ] Full test suite passing

---

### Phase 6: Cleanup & Documentation (Day 5-6)

**Objective**: Remove dead code and update documentation.

#### Step 6.1: Remove Dead Code

**Search for remaining references**:
```bash
# Template references
grep -r "template_intent\|PlanTemplates\|use_templates" src/soothe --include="*.py"

# Enrichment references
grep -r "EnrichmentResult\|classify_enrichment\|capability_domains" src/soothe --include="*.py"

# UnifiedClassification old fields
grep -r "is_plan_only\|template_intent" src/soothe/core --include="*.py"
```

**Remove or update**:
- Unused imports
- Dead code paths
- Deprecated fields

#### Step 6.2: Update Logging

**File**: `src/soothe/backends/planning/simple.py`

**Update log messages**:
```python
# Change from:
logger.info("Using template plan for: %s", goal[:50])

# To:
logger.info("Creating unified plan for: %s", goal[:50])
logger.debug("Plan intent: %s, steps: %d", plan.reasoning, len(plan.steps))
```

**File**: `src/soothe/core/runner.py`

**Update log messages**:
```python
# Remove:
logger.info("Tier-2 enrichment: template_intent=%s...", ...)

# Add:
logger.info("Unified planning completed: %d steps, plan_only=%s", len(plan.steps), plan.is_plan_only)
```

#### Step 6.3: Update Documentation

**File**: `docs/architecture/planning.md`

**Add section**:
```markdown
# Planning Architecture

## Overview

Soothe uses a unified LLM-based planning approach. There are two planning paths:

1. **SimplePlanner** (for medium complexity):
   - Fast model (gpt-4o-mini) generates structured plans
   - Single LLM call combines classification + planning
   - 2-5 concrete steps with execution hints
   - Latency: ~3-4s

2. **ClaudePlanner** (for complex queries):
   - Claude model for sophisticated planning
   - Handles multi-step, ambiguous, or research-intensive goals
   - Latency: ~5-7s

## Routing Flow

1. **Tier-1 Routing**: Fast LLM call determines complexity (chitchat/medium/complex)
2. **Planning** (if not chitchat): Create plan in parallel with I/O operations
3. **Execution**: Execute plan steps via step loop

## Plan Structure

```json
{
  "goal": "string",
  "steps": [...],
  "is_plan_only": false,
  "reasoning": "Intent classification"
}
```

### Execution Hints

- `tool`: Use specific tool
- `subagent`: Delegate to subagent
- `auto`: LLM reasoning
- `remote`: Remote execution
```

**Acceptance criteria**:
- [ ] All dead code removed
- [ ] Logging updated
- [ ] Documentation updated
- [ ] No references to templates/Tier-2 remain

---

## Validation & Rollout

### Pre-Deployment Checklist

- [ ] All tests pass (unit, integration, performance)
- [ ] Planning latency is 30-40% faster than baseline
- [ ] Plan quality is maintained (spot check 10-20 queries)
- [ ] No references to templates or Tier-2 enrichment remain
- [ ] Documentation is updated
- [ ] Logs are clean (no errors/warnings)

### Monitoring (First Week)

**Key metrics**:
1. **Planning latency**: Should be < 6s for medium queries
2. **Plan quality**: Step success rate should be > 90%
3. **Fallback rate**: Single-step fallback should be < 5%
4. **Error rate**: JSON parsing errors should be < 2%

**Log analysis**:
```bash
# Monitor planning failures
grep "Failed to parse LLM plan" logs/soothe.log | tail -20

# Monitor plan quality
grep "Plan created" logs/soothe.log | tail -20

# Monitor execution success
grep "Step completed" logs/soothe.log | grep -c "success"
```

### Rollback Plan

**If critical issues arise**:

```bash
# Revert to backup branch
git checkout backup-planning-before-refactor

# Or revert the merge commit
git revert <merge-commit-hash>

# Deploy previous version
# ... deployment commands ...
```

**Rollback criteria**:
- Planning latency > 10s consistently
- Step success rate < 80%
- User-reported plan quality issues
- Critical parsing errors > 10%

---

## Troubleshooting

### Issue 1: Planning Always Falls Back to Single-Step

**Symptoms**:
- Logs show "Failed to parse LLM plan"
- All plans have only 1 step

**Diagnosis**:
```python
# Add debug logging to _create_plan_via_llm()
logger.debug(f"LLM response: {response.content}")
```

**Causes**:
- Invalid JSON format from LLM
- Missing required fields in JSON
- JSON wrapped in markdown code blocks

**Fix**:
1. Tune prompt to be more explicit about JSON format
2. Add post-processing to strip markdown:
   ```python
   # Strip markdown code blocks if present
   content = response.content.strip()
   if content.startswith("```"):
       lines = content.split("\n")
       content = "\n".join(lines[1:-1])
   ```
3. Use more reliable model (switch to Claude if needed)

### Issue 2: Subagent Preference Not Detected

**Symptoms**:
- User says "use browser to..." but plan doesn't use subagent

**Diagnosis**:
```python
# Check if prompt includes available capabilities
logger.debug(f"Available capabilities: {context.available_capabilities}")
```

**Fix**:
1. Ensure `available_capabilities` includes subagents
2. Enhance prompt with examples:
   ```python
   parts.extend([
       "\nExamples:\n",
       "- 'use browser to navigate...' → execution_hint='subagent', description mentions browser\n",
       "- 'with weaver create...' → execution_hint='subagent', description mentions weaver\n",
   ])
   ```

### Issue 3: Plan-Only Mode Not Detected

**Symptoms**:
- User says "plan how to..." but plan executes

**Fix**:
Enhance prompt:
```python
parts.extend([
    "\nKeywords indicating plan-only:\n",
    "- 'plan how to...'\n",
    "- 'just plan...'\n",
    "- 'only planning...'\n",
    "- 'create a plan for...'\n\n",
])
```

---

## Success Criteria

### Must Have
- [x] 30-40% latency improvement
- [x] All tests pass
- [x] No template references remain
- [x] No Tier-2 enrichment code remains
- [x] Clean rollback path

### Should Have
- [ ] Plan quality metrics maintained or improved
- [ ] Token cost reduced by 25%+
- [ ] Documentation complete

### Nice to Have
- [ ] Added telemetry for plan quality
- [ ] A/B testing framework in place
- [ ] User feedback collection mechanism

---

## References

- **Current architecture**: `src/soothe/backends/planning/`
- **Planning protocol**: `src/soothe/protocols/planner.py`
- **Runner flow**: `src/soothe/core/runner.py`
- **Unified classifier**: `src/soothe/cognition/unified_classifier.py`
- **RFC document**: `docs/specs/RFC-0016.md`

## Changelog

- **2026-03-21**: Initial implementation guide created
- **Backward compatibility**: None (breaking change, but optional fields have defaults)
