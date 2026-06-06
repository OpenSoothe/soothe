# AgentLoop

Plan-Execute loop for single-goal agentic execution.

---

## Overview

AgentLoop (`soothe.core.loop`) implements Layer 2 of Soothe's three-layer execution architecture, providing agentic goal execution through iterative refinement. It uses a Plan → Execute loop where the LLM performs planning, progress assessment, and goal-distance estimation in a single structured response (PlanResult), then executes steps via Layer 1 CoreAgent.

**RFC**: [RFC-201](../../specs/RFC-201-agentloop-plan-execute-loop.md)

---

## Architecture

### Plan-Execute Loop

AgentLoop operates through iterative Plan → Execute cycles:

```
AgentLoop.run_with_progress(goal)
    ↓
┌─ Loop Iteration (max ~8) ────────────────────────────┐
│                                                       │
│  PLAN Phase                                          │
│  ├─ Goal context assembly                            │
│  ├─ LLM planning (structured PlanResult)             │
│  ├─ Evidence accumulation                            │
│  ├─ Progress assessment                              │
│  └─ Goal-distance estimation                         │
│                                                       │
│  EXECUTE Phase                                       │
│  ├─ Step decomposition                               │
│  ├─ CoreAgent execution (per step)                   │
│  ├─ Result collection                                │
│  └─ Evidence update                                  │
│                                                       │
│  REFLECT Phase                                       │
│  ├─ Evaluate progress                                │
│  ├─ Update strategy                                  │
│  ├─ Decide continue/stop                             │
│  └─ Progressive checkpoint                           │
│                                                       │
└───────────────────────────────────────────────────────┘
    ↓
    Return PlanResult
```

---

## Core Concepts

### PlanResult

Structured response from LLM planning phase:

```python
class PlanResult:
    """Structured planning response from LLM."""
    
    # Status
    status: Literal["plan", "done", "failed", "need_info"]
    
    # Plan components
    reasoning: str          # Reasoning about current state
    strategy: str           # Execution strategy
    steps: list[PlanStep]   # Planned steps
    
    # Progress tracking
    progress: float         # Progress percentage (0-1)
    goal_distance: float    # Distance to goal (0-1)
    
    # Evidence
    evidence: EvidenceBundle  # Accumulated evidence
    
    # Iteration tracking
    iteration: int          # Current iteration number
    max_iterations: int     # Maximum allowed iterations
```

### PlanStep

Individual step to execute:

```python
class PlanStep:
    """Single execution step in plan."""
    
    id: str                 # Step identifier
    description: str        # Step description
    tool: str | None        # Tool to use (optional)
    prompt: str             # Prompt for execution
    expected_outcome: str   # Expected outcome
    priority: int           # Execution priority
```

### EvidenceBundle

Accumulated evidence from execution:

```python
class EvidenceBundle:
    """Accumulated evidence from execution."""
    
    entries: list[EvidenceEntry]
    summary: str
    confidence: float
    
    def add_entry(self, entry: EvidenceEntry):
        """Add new evidence entry."""
    
    def build_summary(self) -> str:
        """Build evidence summary."""
```

---

## Execution Phases

### 1. PLAN Phase

LLM-driven planning with structured output:

```python
async def plan_phase(self, state: LoopState) -> PlanResult:
    """Execute planning phase."""
    
    # Assemble goal context
    goal_context = await self.assemble_goal_context(state)
    
    # Retrieve relevant history
    history = await self.retrieve_history(state)
    
    # LLM planning call
    plan_result = await self.llm.plan(
        goal=state.goal_text,
        context=goal_context,
        history=history,
        iteration=state.iteration
    )
    
    # Validate plan
    if not self.validate_plan(plan_result):
        raise InvalidPlanError(plan_result)
    
    return plan_result
```

### 2. EXECUTE Phase

Execute planned steps via CoreAgent:

```python
async def execute_phase(self, plan_result: PlanResult) -> ExecuteResult:
    """Execute planned steps."""
    
    results = []
    for step in plan_result.steps:
        # Execute step via CoreAgent
        step_result = await self.execute_step(step)
        
        # Collect evidence
        evidence = self.extract_evidence(step_result)
        
        # Update progress
        results.append(step_result)
    
    return ExecuteResult(
        steps=results,
        evidence=self.evidence_builder.build()
    )
```

### 3. REFLECT Phase

Evaluate progress and decide continuation:

```python
async def reflect_phase(
    self,
    plan_result: PlanResult,
    execute_result: ExecuteResult
) -> ReflectionResult:
    """Reflect on execution results."""
    
    # Evaluate progress
    progress = self.evaluate_progress(execute_result)
    
    # Update evidence
    self.evidence_builder.add_entries(execute_result.evidence)
    
    # Decide continuation
    should_continue = self.decide_continuation(
        plan_result,
        progress
    )
    
    return ReflectionResult(
        should_continue=should_continue,
        progress=progress,
        updated_strategy=self.update_strategy(execute_result)
    )
```

---

## Loop State

### LoopState

State management for loop execution:

```python
class LoopState:
    """State for AgentLoop execution."""
    
    # Goal information
    current_goal_id: str
    goal_text: str
    
    # Thread information
    thread_id: str
    
    # Iteration tracking
    iteration: int
    max_iterations: int
    
    # Evidence
    evidence: EvidenceBundle
    
    # Context
    goal_context: dict
    
    # Progress
    progress: float
    goal_distance: float
    
    # Status
    status: Literal["planning", "executing", "reflecting", "completed", "failed"]
```

---

## Evidence Accumulation

### Evidence Builder

Build evidence bundle from execution:

```python
class EvidenceBundleBuilder:
    """Builder for evidence bundles."""
    
    def __init__(self):
        self.entries = []
    
    def add_tool_result(self, tool: str, result: str):
        """Add tool execution result."""
        entry = EvidenceEntry(
            type="tool_result",
            tool=tool,
            result=result,
            timestamp=now()
        )
        self.entries.append(entry)
    
    def add_observation(self, observation: str):
        """Add observation from execution."""
        entry = EvidenceEntry(
            type="observation",
            content=observation,
            timestamp=now()
        )
        self.entries.append(entry)
    
    def build(self) -> EvidenceBundle:
        """Build final evidence bundle."""
        return EvidenceBundle(
            entries=self.entries,
            summary=self.build_summary(),
            confidence=self.calculate_confidence()
        )
```

---

## Goal-Directed Evaluation

### Progress Assessment

Evaluate progress toward goal:

```python
def evaluate_progress(self, execute_result: ExecuteResult) -> float:
    """Evaluate progress toward goal."""
    
    # Evidence-based progress
    evidence_progress = self.calculate_evidence_progress()
    
    # Step completion progress
    step_progress = self.calculate_step_progress(execute_result)
    
    # Combined progress
    return min(evidence_progress, step_progress)
```

### Goal-Distance Estimation

Estimate distance to goal completion:

```python
def estimate_goal_distance(self, plan_result: PlanResult) -> float:
    """Estimate distance to goal."""
    
    # Based on remaining steps
    remaining_steps = len(plan_result.steps)
    
    # Based on evidence gaps
    evidence_gaps = self.identify_evidence_gaps()
    
    # Combined distance
    return self.calculate_distance(remaining_steps, evidence_gaps)
```

---

## Adaptive Execution

### Strategy Reuse

Reuse successful strategies:

```python
def reuse_strategy(self, similar_goals: list[GoalHistory]) -> Strategy:
    """Reuse strategy from similar goals."""
    
    # Find best matching strategy
    best_match = self.find_best_match(similar_goals)
    
    # Adapt strategy for current goal
    adapted = self.adapt_strategy(best_match, self.current_goal)
    
    return adapted
```

### Strategy Update

Update strategy based on execution:

```python
def update_strategy(self, execute_result: ExecuteResult) -> str:
    """Update strategy based on results."""
    
    # Analyze results
    analysis = self.analyze_results(execute_result)
    
    # Identify adjustments
    adjustments = self.identify_adjustments(analysis)
    
    # Generate updated strategy
    return self.generate_updated_strategy(adjustments)
```

---

## Context Isolation

### Goal Context Assembly

Assemble context for goal execution:

```python
async def assemble_goal_context(self, state: LoopState) -> dict:
    """Assemble goal-specific context."""
    
    # Context projection
    projection = await self.context.project(
        query=state.goal_text,
        token_budget=4000
    )
    
    # Memory recall
    memory = await self.memory.recall(state.goal_text)
    
    # Goal history
    history = await self.retrieve_goal_history(state.current_goal_id)
    
    return {
        "projection": projection,
        "memory": memory,
        "history": history,
        "goal": state.goal_text
    }
```

---

## Iteration Management

### Iteration Bounds

Maximum iterations (default ~8):

```python
MAX_ITERATIONS = 8  # Typical for single-goal execution

def check_iteration_limit(self, state: LoopState) -> bool:
    """Check if within iteration limit."""
    return state.iteration < state.max_iterations
```

### Convergence Detection

Detect goal convergence:

```python
def detect_convergence(self, state: LoopState) -> bool:
    """Detect if goal has converged."""
    
    # Progress threshold
    if state.progress >= 0.95:
        return True
    
    # Goal distance threshold
    if state.goal_distance <= 0.05:
        return True
    
    # Evidence completeness
    if self.evidence_complete(state.evidence):
        return True
    
    return False
```

---

## Usage Patterns

### Basic Execution

```python
from soothe.core.loop import AgentLoop
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
loop = AgentLoop(config)

# Run loop
result = await loop.run_with_progress(
    goal="Analyze the codebase structure"
)

print(result.status)  # "done", "failed", or "need_info"
print(result.progress)  # Progress percentage
```

### Thread-Based Execution

```python
# Run with thread
result = await loop.run_with_progress(
    goal="Implement feature",
    thread_id="thread-123"
)
```

### Goal-Based Execution

```python
# Run with goal ID (GoalEngine integration)
result = await loop.run_with_progress(
    goal="Optimize performance",
    goal_id="goal-456"
)
```

---

## Integration Points

### GoalEngine Integration

Report to GoalEngine:

```python
# GoalEngine pull architecture
goal_engine = config.resolve_goal_engine()
current_goal = goal_engine.get_next_ready_goal()

# Execute goal
result = await loop.run_with_progress(
    goal=current_goal.description,
    goal_id=current_goal.id
)

# Report to GoalEngine
if result.status == "done":
    goal_engine.complete_goal(current_goal.id, result)
elif result.status == "failed":
    await goal_engine.fail_goal(current_goal.id, result.evidence)
```

### CoreAgent Integration

Delegate execution to CoreAgent:

```python
# Execute step via CoreAgent
async def execute_step(self, step: PlanStep):
    # Delegate to CoreAgent
    agent = create_soothe_agent(self.config)
    
    async for chunk in agent.astream(
        step.prompt,
        config={"thread_id": self.state.thread_id}
    ):
        # Process chunk
        yield chunk
```

---

## Event Types

### Plan Events
- `soothe.plan.created` - Plan created
- `soothe.plan.step.started` - Step started
- `soothe.plan.step.completed` - Step completed
- `soothe.plan.iteration.complete` - Iteration complete

### Evidence Events
- `soothe.evidence.added` - Evidence added
- `soothe.evidence.bundle.updated` - Bundle updated

### Loop Events
- `soothe.loop.started` - Loop started
- `soothe.loop.iteration.started` - Iteration started
- `soothe.loop.completed` - Loop completed

---

## Configuration

### Loop Settings

```yaml
loop:
  max_iterations: 8       # Maximum iterations
  convergence_threshold: 0.95  # Progress threshold
  evidence_budget: 4000   # Token budget for evidence
```

### Planning Settings

```yaml
planning:
  model: "openai:o3-mini"  # Model for planning
  structured_output: true   # Use structured output
  temperature: 0.7          # Planning temperature
```

---

## Related Documentation

- **[GoalEngine](goal-engine.md)** - Goal management integration
- **[Agent Factory](agent-factory.md)** - CoreAgent integration
- **[SootheRunner](runner.md)** - Runner orchestration
- **[Evidence System](../architecture/evidence-system.md)** - Evidence handling
- **[RFC-201](../../specs/RFC-201-agentloop-plan-execute-loop.md)** - Full specification

---

## API Reference

### AgentLoop Class

```python
class AgentLoop:
    """Plan-Execute loop for single-goal execution."""
    
    def __init__(self, config: SootheConfig):
        """Initialize loop with configuration."""
    
    async def run_with_progress(
        self,
        goal: str,
        thread_id: str | None = None,
        goal_id: str | None = None
    ) -> PlanResult:
        """Execute goal with progress tracking."""
    
    async def run_iteration(
        self,
        state: LoopState
    ) -> PlanResult:
        """Execute single iteration."""
    
    async def plan_phase(
        self,
        state: LoopState
    ) -> PlanResult:
        """Execute planning phase."""
    
    async def execute_phase(
        self,
        plan_result: PlanResult
    ) -> ExecuteResult:
        """Execute planned steps."""
    
    async def reflect_phase(
        self,
        plan_result: PlanResult,
        execute_result: ExecuteResult
    ) -> ReflectionResult:
        """Reflect on execution results."""
```

### State Classes

```python
class LoopState:
    """State for loop execution."""
    current_goal_id: str
    goal_text: str
    thread_id: str
    iteration: int
    evidence: EvidenceBundle
    ...

class PlanResult:
    """Structured planning result."""
    status: Literal["plan", "done", "failed", "need_info"]
    reasoning: str
    strategy: str
    steps: list[PlanStep]
    progress: float
    ...

class PlanStep:
    """Single execution step."""
    id: str
    description: str
    prompt: str
    ...
```

---

## See Also

- **[Autonomous Mode](../user-guide/autonomous-mode.md)** - User guide
- **[Subagents](../modules/subagents/README.md)** - Built-in subagents
- **[Plan Subagent](../modules/subagents/plan.md)** - Plan subagent details