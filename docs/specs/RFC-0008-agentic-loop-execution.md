# RFC-0008: Agentic Loop Execution Architecture

**RFC**: 0008
**Title**: Agentic Loop Execution Architecture
**Status**: Draft
**Created**: 2026-03-16
**Updated**: 2026-03-22
**Related**: RFC-0001, RFC-0002, RFC-0003, RFC-0007, RFC-0009, RFC-0012

## Abstract

This RFC defines Soothe's default execution architecture based on the **Agentic Loop** pattern: **Observe → Act → Verify**. This iterative refinement loop replaces the previous single-pass execution model, enabling automatic adaptation to task complexity while maintaining sub-second responses for simple queries through a chitchat fast path. The architecture uses unified classification (RFC-0012) to drive adaptive planning strategies, providing intelligent iteration without the overhead of explicit goal management required in Autonomous mode (RFC-0007).

## Motivation

### Problem Statement

Before this RFC, Soothe used a **single-pass execution model** where queries received one-shot processing:

1. **Classification** → Determine complexity
2. **Planning** → Create plan (always for medium/complex)
3. **Execution** → Run once
4. **Reflection** → Post-hoc analysis

**Limitations**:
- No iterative refinement for tasks that benefit from multiple attempts
- Users must explicitly opt into Autonomous mode (RFC-0007) for iteration
- Planning always triggered for medium/complex queries, even when unnecessary
- No feedback loop to adapt execution based on initial results

### Design Goals

1. **Default iteration**: Non-chitchat queries automatically benefit from iterative refinement
2. **Adaptive planning**: Planning triggered by complexity and context, not just classification
3. **Sub-second chitchat**: Simple queries remain fast (direct LLM, no overhead)
4. **Lighter than autonomous**: No goal engine overhead for standard tasks
5. **Intelligent adaptation**: Observe results, verify quality, iterate as needed

### Relationship to RFC-0007 (Autonomous Mode)

**Two complementary execution modes**:

| Aspect | Agentic Loop (This RFC) | Autonomous Mode (RFC-0007) |
|--------|-------------------------|----------------------------|
| **Trigger** | Default for all non-chitchat queries | Explicit `--autonomous` flag |
| **Goal Management** | Implicit (thread-scoped) | Explicit GoalEngine with DAG |
| **Iteration** | Verify-based continuation | Reflection-based goal completion |
| **Planning** | Adaptive (complexity-driven) | Always comprehensive |
| **Overhead** | Minimal (stateless) | Goal lifecycle, persistence |
| **Use Case** | Standard tasks (90%) | Complex multi-goal workflows (10%) |

**Refer to RFC-0007 for**: Goal DAG scheduling, hierarchical goals, goal directives, multi-threaded parallel execution.

## Architecture Overview

### Two Execution Modes

```mermaid
flowchart TD
    Start([User Request]) --> Classify{Unified Classification<br/>RFC-0012}

    %% Chitchat Fast Path
    Classify -->|chitchat| Fast[Chitchat Fast Path]
    Fast --> DirectLLM[Direct LLM Call<br/>< 1s]
    DirectLLM --> End1([End])

    %% Agentic Loop (Default)
    Classify -->|non-chitchat| Agentic[Agentic Loop<br/>Observe → Act → Verify]

    Agentic --> Observe[Observe Phase<br/>Gather Context]
    Observe --> Act[Act Phase<br/>Execute with Adaptive Planning]
    Act --> Verify{Verify Phase<br/>Continue?}

    Verify -->|Yes| Observe
    Verify -->|No| PostStream[Post-Stream<br/>Persist & Checkpoint]
    PostStream --> End2([End])

    %% Autonomous Mode (Explicit)
    Classify -.->|explicit --autonomous| Autonomous[Autonomous Mode<br/>RFC-0007]
    Autonomous --> GoalEngine[GoalEngine<br/>DAG Scheduling]
    GoalEngine --> End3([End])

    classDef fastPath fill:#90EE90,stroke:#333,stroke-width:3px
    classDef agentic fill:#87CEEB,stroke:#333,stroke-width:2px
    classDef autonomous fill:#DDA0DD,stroke:#333,stroke-width:2px

    class Fast,DirectLLM fastPath
    class Observe,Act,Verify,PostStream agentic
    class Autonomous,GoalEngine autonomous
```

### Agentic Loop Phases

#### Phase 1: Observe

**Purpose**: Gather context and determine execution strategy.

**Operations**:
- **Classification** (RFC-0012): Determine complexity and routing
- **Context Projection**: Retrieve relevant context entries
- **Memory Recall**: Fetch relevant memories
- **Policy Check**: Validate permissions
- **State Analysis**: Analyze cumulative iteration results

**Outputs**:
- `task_complexity`: simple | medium | complex
- `planning_strategy`: none | lightweight | comprehensive
- `context_projection`: Relevant context
- `recalled_memories`: Related memories
- `observation_summary`: Structured observation results

**Adaptive Observation Strategy**:

| Complexity | Context | Memory | Classification | Duration |
|------------|---------|--------|----------------|----------|
| Simple | ❌ Skip | ❌ Skip | ✅ Fast | < 100ms |
| Medium | ✅ Parallel | ✅ Parallel | ✅ Full | 1-2s |
| Complex | ✅ Full | ✅ Full | ✅ Full | 2-3s |

#### Phase 2: Act

**Purpose**: Execute actions with adaptive planning.

**Planning Decision Tree**:

```mermaid
flowchart TD
    Start([Need Planning?]) --> Complexity{Task Complexity?}

    Complexity -->|Simple| Simple[No Planning<br/>Direct Execution]
    Complexity -->|Medium| Medium{User Intent?}
    Complexity -->|Complex| Complex[Comprehensive Planning]

    Medium -->|"plan for..."| Complex
    Medium -->|"just do X"| Simple
    Medium -->|Default| Light[Lightweight Planning<br/>2-3 steps max]

    Simple --> Execute[Execute Directly]
    Light --> Execute
    Complex --> FullPlan[Full Planning<br/>Multi-step with dependencies]

    FullPlan --> Execute

    Execute --> Result[Action Result]

    classDef simple fill:#90EE90,stroke:#333
    classDef medium fill:#FFE4B5,stroke:#333
    classDef complex fill:#FFB6C1,stroke:#333

    class Simple simple
    class Light medium
    class Complex,FullPlan complex
```

**Planning Strategies**:

1. **None** (Simple queries):
   - Skip planning entirely
   - Direct LLM execution
   - Single-step actions
   - Examples: "read file X", "list files"

2. **Lightweight** (Medium queries):
   - 2-3 steps maximum
   - Simple sequential execution
   - No DAG analysis
   - Examples: "debug the error", "add tests for X"

3. **Comprehensive** (Complex queries):
   - Full multi-step planning
   - DAG-based step scheduling (RFC-0009)
   - Parallel execution of independent steps
   - Examples: "refactor auth system", "migrate to microservices"

**Execution Flow**:
- Single-step → Direct LangGraph stream
- Multi-step → Step scheduler (RFC-0009) with DAG execution
- Parallel execution for independent steps
- Concurrency control via `ConcurrencyController`

#### Phase 3: Verify

**Purpose**: Evaluate results and decide iteration continuation.

**Verification Process**:

1. **Reflection** (PlannerProtocol):
   - Analyze step results
   - Assess goal completion
   - Identify remaining work
   - Generate feedback

2. **Quality Check**:
   - Task completion signals in response
   - Error detection
   - Missing information
   - Quality metrics

3. **Decision**:
   - `should_continue`: Boolean decision
   - `reasoning`: Why continue or stop
   - `next_focus`: What to work on next iteration

**Verification Strictness Levels**:

| Strictness | Continue Criteria | Use Case |
|------------|-------------------|----------|
| **Lenient** | Any indication of incomplete work | Exploratory tasks |
| **Moderate** (default) | Clear need + quality check | Standard tasks |
| **Strict** | Strong evidence of incompleteness | Critical tasks |

**Continuation Signals**:
- **Positive**: "need to verify", "should test", "missing X"
- **Negative**: "task complete", "done", "finished successfully"
- **Errors**: Exception, timeout, tool failure (may require retry)

### Iteration Control

**Maximum Iterations**:
- Default: 3 iterations
- Configurable per request
- Hard limit to prevent infinite loops

**Early Termination**:
- Task completion detected in response
- User interruption
- Error threshold exceeded
- Resource limits reached

**Iteration Record**:

```python
class IterationRecord(BaseModel):
    iteration: int
    planning_strategy: str  # none | lightweight | comprehensive
    observation_summary: str
    actions_taken: str
    verification_result: str
    should_continue: bool
    duration_ms: int
```

Stored in ContextProtocol for cross-iteration memory.

## Performance Optimization

### Chitchat Fast Path

**Preserved from original RFC-0008**: Sub-second responses for simple queries.

**Optimization**: Skip all protocols and planning, direct LLM call.

**Characteristics**:
- Token count < 30
- Greetings, simple questions, acknowledgments
- No state persistence
- No memory/context operations
- Single LLM call with minimal prompt

**Latency Target**: < 500ms (P90), < 800ms (P99)

### Adaptive Resource Loading

**Lazy loading based on complexity**:

| Resource | Chitchat | Simple | Medium | Complex |
|----------|----------|--------|--------|---------|
| Memory Recall | ❌ Skip | ❌ Skip | ✅ Parallel | ✅ Full |
| Context Projection | ❌ Skip | ❌ Skip | ✅ Parallel | ✅ Full |
| Planning | ❌ Skip | ❌ Skip | ✅ Light/Full | ✅ Full |
| Checkpoint | ❌ Skip | ✅ End | ✅ End | ✅ Per-step |

### Parallel Execution

**Pre-stream parallelization** (Medium/Complex):

```mermaid
sequenceDiagram
    participant Runner
    participant Memory
    participant Context
    participant Planner

    Note over Runner: Observe Phase (Parallel)

    par Parallel Observations
        Runner->>Memory: recall(query)
        and
        Runner->>Context: project(query)
    end

    Memory-->>Runner: MemoryItem[]
    Context-->>Runner: ContextProjection

    Note over Runner: Determine Planning Strategy

    Runner->>Runner: _determine_planning_strategy()

    alt Planning Needed
        Runner->>Planner: create_plan(goal, context)
        Planner-->>Runner: Plan
    end

    Note over Runner: Act Phase
```

**Step parallelization** (Comprehensive planning only):
- Independent steps execute concurrently via StepScheduler (RFC-0009)
- Hierarchical concurrency limits
- Dependency-aware scheduling

## Configuration

Key configuration parameters:

```yaml
agentic:
  enabled: true
  max_iterations: 3
  observation_strategy: "adaptive"      # minimal | comprehensive | adaptive
  verification_strictness: "moderate"   # lenient | moderate | strict
  planning:
    simple_max_tokens: 50
    medium_max_steps: 3
    complexity_threshold: 160
    force_keywords: ["plan for", "create a plan", "steps to"]
  early_termination:
    enabled: true
    error_threshold: 3
```

## Event System

### New Agentic Events (RFC-0015 Naming)

**Lifecycle Events**:
- `soothe.agentic.loop_started` - Agentic loop begins
- `soothe.agentic.loop_completed` - Agentic loop finishes
- `soothe.agentic.iteration_started` - Iteration begins
- `soothe.agentic.iteration_completed` - Iteration finishes

**Phase Events**:
- `soothe.agentic.observation_started` - Observe phase starts
- `soothe.agentic.observation_completed` - Observe phase ends
- `soothe.agentic.verification_started` - Verify phase starts
- `soothe.agentic.verification_completed` - Verify phase ends

**Decision Events**:
- `soothe.agentic.planning_strategy_determined` - Planning strategy chosen

### Event Flow Example

```
soothe.agentic.loop_started
  soothe.agentic.iteration_started (iteration=0)
    soothe.agentic.observation_started
    soothe.agentic.observation_completed
    soothe.agentic.planning_strategy_determined (strategy=lightweight)
    soothe.plan.created
    soothe.plan.step_started (step_1)
    soothe.plan.step_completed (step_1)
    soothe.agentic.verification_started
    soothe.agentic.verification_completed (should_continue=true)
  soothe.agentic.iteration_completed (iteration=0)
  soothe.agentic.iteration_started (iteration=1)
    ...
  soothe.agentic.iteration_completed (iteration=1)
soothe.agentic.loop_completed
```

## When to Use Agentic Loop vs. Autonomous Mode

**Agentic Loop** (default): Single implicit goal, standard iteration, moderate complexity
- Examples: "Debug the failing tests", "Refine documentation", "Add error handling"

**Autonomous Mode** (RFC-0007): Multiple explicit goals, complex dependencies, hierarchical workflows
- Examples: "Set up CI/CD pipeline", "Migrate to microservices", "Optimize entire system"
- Requires explicit `--autonomous` flag

**Decision**: Use Autonomous mode for multi-goal workflows with complex dependencies.

## Migration Guide

**No API changes** - agentic loop is transparent. The same `runner.astream()` call now iterates automatically:

```python
# Same code, automatic iteration
async for chunk in runner.astream("debug the tests"):
    process(chunk)
```

For multi-goal workflows with dependencies, use Autonomous mode (RFC-0007):

```python
async for chunk in runner.astream("Set up CI/CD pipeline", autonomous=True):
    process(chunk)
```

## Performance Metrics

**Latency Targets**:

| Complexity | P50 | P90 | P99 | Notes |
|------------|-----|-----|-----|-------|
| Chitchat | 300ms | 500ms | 800ms | Direct LLM, no overhead |
| Simple | 1s | 1.5s | 2s | No planning, single iteration |
| Medium | 2s | 3s | 4s | Lightweight planning, 2-3 iterations |
| Complex | 3s | 5s | 8s | Comprehensive planning, 3+ iterations |

**Observable Metrics**:
- Per-iteration duration (observe, plan, act, verify phases)
- Total iterations per query
- Planning strategy distribution
- Early termination rate
- Chitchat fast path hit rate

## Failure Modes and Mitigation

| Failure | Mitigation | Impact |
|---------|-----------|--------|
| Classification error | Default to "medium" | Higher latency, more iterations |
| Fast model unavailable | Token-count fallback | No classification, default planning |
| Planner unavailable | Skip planning, direct execution | Single-step only |
| Memory recall timeout | Skip memory, continue | Less historical context |
| Context projection error | Skip context, continue | Less enriched input |
| Verification loop | Max iterations limit | Stop after N iterations |
| Parallel task failure | Partial results, continue | Some context missing |

## Security Considerations

- **Iteration limits**: Hard cap on iterations prevents runaway execution
- **Resource isolation**: Each iteration maintains thread isolation
- **State persistence**: Checkpoint after each iteration for crash recovery
- **Error containment**: Failed iterations don't corrupt subsequent iterations
- **Memory safety**: Context and memory respect thread boundaries

## Future Enhancements

1. **Predictive iteration**: Estimate required iterations before execution
2. **Adaptive thresholds**: Learn optimal complexity thresholds from usage
3. **Streaming verification**: Evaluate quality during execution, not just after
4. **Cost optimization**: Balance iteration count vs. quality metrics
5. **Learning from iteration history**: Improve planning accuracy over time

## References

- RFC-0001: System Conceptual Design
- RFC-0007: Autonomous Iteration Loop (explicit goal-driven mode)
- RFC-0009: DAG-Based Execution and Unified Concurrency
- RFC-0012: Unified LLM-Based Classification System
- RFC-0015: Progress Event Protocol

## Changelog

### 2026-03-22
- Rewrote RFC-0008 to focus on Agentic Loop architecture
- Replaced single-pass execution model with agentic loop as default
- Added observe → act → verify three-phase loop
- Introduced adaptive planning strategies (none/lightweight/comprehensive)
- Preserved chitchat fast path for simple queries
- Referenced RFC-0007 for Autonomous mode without duplication
- Added iteration control, verification strictness, and early termination
- Maintained core performance optimizations from original RFC-0008

### 2026-03-19 (Original RFC-0008)
- Initial draft with unified classification system
- Single-pass execution model
- Performance optimization strategies
- Parallel execution and template matching