# PlannerProtocol & LoopPlannerProtocol

**RFC**: 404 (Planner), 604 (LoopPlanner)  
**Modules**: RFC-000 Module 3  
**Locations**:
- `packages/soothe/src/soothe/protocols/planner.py`
- `packages/soothe/src/soothe/protocols/loop_planner.py`

**Status**: Implemented  

## Overview

Soothe defines two planner protocols for goal decomposition and execution planning:

1. **PlannerProtocol**: Goal decomposition into structured plans with steps
2. **LoopPlannerProtocol**: Unified StrangeLoop Plan phase (assessment + plan generation)

Both protocols implement the plan-driven execution principle (RFC-000 Principle 6), enabling complex goals to be decomposed into executable steps with dependency tracking and concurrency management.

## PlannerProtocol

### Purpose

- **Goal decomposition**: Break complex goals into ordered steps
- **Dependency tracking**: DAG-based step dependencies
- **Concurrency management**: Parallel step execution within limits
- **Plan lifecycle**: Create, revise, complete, fail states
- **Execution hints**: Guide step execution method

### Protocol Interface

```python
@runtime_checkable
class PlannerProtocol(Protocol):
    """Protocol for goal decomposition and plan lifecycle.
    
    Creates and revises plans for complex goals. A plan is a Pydantic
    data model (goal + steps + statuses + dependency graph + concurrency policy).
    """

    async def create_plan(
        self,
        goal: str,
        context: PlanContext,
    ) -> Plan:
        """Create a new plan for the given goal.
        
        Args:
            goal: Goal description.
            context: Planning context (capabilities, workspace).
            
        Returns:
            Plan with ordered steps and execution hints.
        """
        ...

    async def revise_plan(
        self,
        plan: Plan,
        feedback: str,
        context: PlanContext,
    ) -> Plan:
        """Revise an existing plan based on execution feedback.
        
        Args:
            plan: Current plan to revise.
            feedback: Execution feedback from completed steps.
            context: Planning context.
            
        Returns:
            Revised plan with updated steps.
        """
        ...
```

### Data Models

#### Plan

```python
class Plan(BaseModel):
    """A structured decomposition of a goal into executable steps.
    
    Args:
        id: Unique plan identifier (P_1, P_2, etc.).
        goal: The original goal text.
        steps: Ordered list of plan steps.
        current_index: Index of the current/next step to execute.
        status: Overall plan status.
        concurrency: Parallel execution configuration.
        general_activity: Latest non-step activity (for TUI rendering).
        is_plan_only: User wants planning without execution.
        reasoning: Optional planner rationale or strategy summary.
    """

    id: str = ""
    goal: str
    steps: list[PlanStep]
    current_index: int = 0
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    general_activity: str | None = None
    
    # Unified planning metadata
    is_plan_only: bool = Field(default=False, description="User wants planning without execution")
    reasoning: str | None = Field(
        default=None, description="Optional planner rationale or strategy summary when populated"
    )
```

#### PlanStep

```python
class PlanStep(BaseModel):
    """A single step in a plan.
    
    Args:
        id: Unique step identifier.
        description: What this step should accomplish.
        execution_hint: Preferred execution method.
        subagent: Delegate name when routing through a subagent (legacy path).
        status: Current step status.
        result: Output from execution (set after completion).
        depends_on: IDs of steps that must complete before this one.
        current_activity: Latest activity text for this step (for TUI rendering).
    """

    id: str
    description: str
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    subagent: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    current_activity: str | None = None
```

**Execution Hints**:
- **tool**: Execute via direct tool invocation
- **subagent**: Delegate to named subagent
- **remote**: Delegate to remote agent
- **auto**: Planner selects appropriate method

#### PlanContext

```python
class PlanContext(BaseModel):
    """Context for planning decisions.
    
    Args:
        capabilities: Available tools and subagents.
        workspace: Current workspace path.
        thread_id: Current thread ID.
        completed_steps: Summary of completed step results.
    """

    capabilities: list[str] = Field(default_factory=list)
    workspace: str | None = None
    thread_id: str | None = None
    completed_steps: dict[str, str] = Field(default_factory=dict)
```

#### StepResult

```python
class StepResult(BaseModel):
    """Result of executing a plan step (RFC-211).
    
    Args:
        step_id: The step that was executed.
        success: Whether the step succeeded.
        outcome: Structured metadata from tool execution.
        error: Error message if failed.
        duration_ms: Execution time in milliseconds.
        thread_id: Thread used for execution.
    """

    step_id: str
    success: bool
    outcome: dict = Field(default_factory=dict)  # RFC-211: outcome metadata
    error: str | None = None
    duration_ms: int | None = None
    thread_id: str | None = None
```

#### ConcurrencyPolicy

```python
@dataclass
class ConcurrencyPolicy:
    """Controls parallel execution of plan steps.
    
    Attributes:
        max_parallel_steps: Maximum concurrent steps (default 2).
        max_parallel_subagents: Maximum concurrent subagent spawns (default 1).
        max_parallel_tools: Maximum concurrent tool calls (default 3).
    """

    max_parallel_steps: int = 2
    max_parallel_subagents: int = 1
    max_parallel_tools: int = 3
```

## LoopPlannerProtocol

### Purpose

- **StrangeLoop Plan phase**: Unified assessment + plan generation
- **Status assessment**: Evaluate progress and decide next action
- **Plan generation**: Create or keep execution plan
- **Continuation routing**: Discriminate continuation vs new goal

### Protocol Interface

```python
@runtime_checkable
class LoopPlannerProtocol(Protocol):
    """Protocol for the StrangeLoop Plan step (assessment + optional plan generation).
    
    Implementations perform structured LLM calls (StatusAssessment then, 
    when needed, PlanGeneration) and return a unified PlanResult.
    """

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        """Assess progress and decide the next executable plan fragment.
        
        Args:
            goal: Goal description.
            state: Current loop state (iteration, step results, prior plan).
            context: Capabilities, completed steps summary, workspace.
            plan_manager: Optional PlanManager for DAG-aware progressive planning.
            
        Returns:
            PlanResult with status, UX fields, and plan_action ('keep' or 'new').
        """
        ...

    async def assess_status(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> StatusAssessment:
        """Run assess-only status evaluation for current iteration.
        
        Args:
            goal: Goal description.
            state: Current loop state.
            context: Planning context.
            
        Returns:
            StatusAssessment with completion status and continuation decision.
        """
        ...

    async def generate_from_assessment(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: StatusAssessment,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        """Generate or keep execution plan after assess determines work remains.
        
        Args:
            goal: Goal description.
            state: Current loop state.
            context: Planning context.
            assessment: StatusAssessment from assess_status.
            plan_manager: Optional PlanManager for progressive planning.
            
        Returns:
            PlanResult with plan_action='keep' or 'new'.
        """
        ...

    async def assess_continuation(
        self,
        *,
        current_goal: str,
        prior_goals: list[dict],
        capabilities: list[str],
        thread_id: str | None = None,
    ) -> ContinuationAssessment:
        """RFC-226: iter=0 discriminator for continuation queries.
        
        Routes follow-up query in existing loop to either terminal 
        bootstrap (single execute) or full plan_generate flow.
        
        Args:
            current_goal: Follow-up goal text.
            prior_goals: Completed goal history.
            capabilities: Available capabilities.
            thread_id: Current thread ID.
            
        Returns:
            ContinuationAssessment with routing decision.
        """
        ...
```

### Data Models

#### PlanResult

```python
class PlanResult(BaseModel):
    """Unified result from LoopPlanner.plan().
    
    Args:
        status: Goal completion status (complete/incomplete/failed).
        plan_action: 'keep' existing plan or 'new' generated plan.
        decision: Next execution decision (when plan_action='new').
        ux_preview: User-facing preview text.
        evidence_summary: Structured evidence summary.
    """

    status: Literal["complete", "incomplete", "failed"]
    plan_action: Literal["keep", "new"]
    decision: Decision | None = None  # When plan_action='new'
    ux_preview: str | None = None
    evidence_summary: str | None = None
```

#### StatusAssessment

```python
class StatusAssessment(BaseModel):
    """Assessment of goal progress and continuation decision.
    
    Args:
        completion_status: Is goal complete, incomplete, or failed?
        continuation_decision: Should we continue, retry, or abort?
        progress_summary: Human-readable progress summary.
        blockers: List of blocking issues.
    """

    completion_status: Literal["complete", "incomplete", "failed"]
    continuation_decision: Literal["continue", "retry", "abort"]
    progress_summary: str
    blockers: list[str] = Field(default_factory=list)
```

#### ContinuationAssessment

```python
class ContinuationAssessment(BaseModel):
    """RFC-226: Routing decision for continuation queries.
    
    Args:
        route: 'bootstrap' (single execute) or 'plan_generate' (full flow).
        reasoning: Explanation for routing decision.
        confidence: Confidence in routing decision.
    """

    route: Literal["bootstrap", "plan_generate"]
    reasoning: str
    confidence: float = 0.0
```

## Backend Implementations

### LLMPlanner

**Status**: Unified planner implementation  
**Location**: `packages/soothe/src/soothe/cognition/planning/llm_planner.py`  
**Features**:
- Two-phase architecture (RFC-604): StatusAssessment → conditional PlanGeneration
- Model-agnostic (works with any LangChain chat model)
- Progressive planning with PlanManager
- Continuation routing (RFC-226)
- Token-efficient schema trimming (IG-329)

**Implementation Pattern**:
```python
class LLMPlanner(LoopPlannerProtocol):
    """LLM-based planner with two-phase architecture."""
    
    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        # Phase 1: StatusAssessment
        assessment = await self.assess_status(goal, state, context)
        
        if assessment.completion_status == "complete":
            return PlanResult(
                status="complete",
                plan_action="keep",
                ux_preview="Goal achieved successfully"
            )
        
        # Phase 2: PlanGeneration (if incomplete)
        return await self.generate_from_assessment(
            goal, state, context, assessment, plan_manager=plan_manager
        )
```

### Historical Implementations

**Note**: Earlier versions had multiple planner tiers (AutoPlanner, ClaudePlanner, SubagentPlanner). IG-150 consolidated to unified LLMPlanner.

## Usage Patterns

### Goal Planning

```python
from soothe.protocols import PlanContext, Plan, PlannerProtocol

planner: PlannerProtocol = resolve_planner(config)

context = PlanContext(
    capabilities=["explore", "plan", "research", "file_ops"],
    workspace="/project/workspace",
    thread_id="thread_abc123"
)

plan = await planner.create_plan(
    goal="Implement user authentication system",
    context=context
)

print(f"Plan created: {plan.id}")
for step in plan.steps:
    print(f"  [{step.status}] {step.description}")
```

### Plan Execution

```python
# Execute plan steps respecting dependencies
for step in plan.steps:
    if step.status == "pending":
        # Check dependencies completed
        deps_complete = all(
            plan.get_step(dep_id).status == "completed"
            for dep_id in step.depends_on
        )
        
        if deps_complete:
            # Execute step
            result = await execute_step(step)
            
            # Update step status
            step.status = "completed" if result.success else "failed"
            step.result = result.outcome.get("preview")
```

### Plan Revision

```python
# Revise plan after failure
feedback = "Step 3 failed: Database connection timeout"

revised_plan = await planner.revise_plan(
    plan=current_plan,
    feedback=feedback,
    context=context
)

print(f"Plan revised: {revised_plan.status}")
```

### LoopPlanner Usage

```python
from soothe.core.loop.state.schemas import LoopState
from soothe.protocols import LoopPlannerProtocol

loop_planner: LoopPlannerProtocol = resolve_loop_planner(config)

state = LoopState(
    iteration=3,
    step_results=[...],
    prior_plan=current_plan
)

result = await loop_planner.plan(
    goal="Optimize database queries",
    state=state,
    context=context
)

if result.plan_action == "new":
    # Execute new decision
    await execute_decision(result.decision)
elif result.status == "complete":
    # Goal achieved
    complete_goal()
```

## Concurrency Management

### DAG-Based Execution

```python
# Steps form DAG via depends_on
plan.steps = [
    PlanStep(id="S1", description="Research database options", depends_on=[]),
    PlanStep(id="S2", description="Design schema", depends_on=["S1"]),
    PlanStep(id="S3", description="Write migration script", depends_on=["S2"]),
    PlanStep(id="S4", description="Write tests", depends_on=["S2"]),  # Parallel with S3
    PlanStep(id="S5", description="Run integration tests", depends_on=["S3", "S4"]),
]

# Execution respects DAG
# S1 → S2 → (S3 parallel S4) → S5
```

### Concurrency Limits

```python
from soothe.protocols import ConcurrencyPolicy

# Configure parallel execution
concurrency = ConcurrencyPolicy(
    max_parallel_steps=2,      # Max 2 concurrent steps
    max_parallel_subagents=1,  # Max 1 concurrent subagent
    max_parallel_tools=3       # Max 3 concurrent tool calls
)

plan.concurrency = concurrency
```

## Integration with Other Protocols

### Planner ↔ StrangeLoop Integration

```
StrangeLoop Plan → Execute cycle:

Plan Phase (LoopPlanner):
  1. assess_status() → StatusAssessment
  2. generate_from_assessment() → PlanResult
  3. Return decision (keep/new)
  
Execute Phase (CoreAgent):
  1. Execute decision via tools/subagents
  2. Collect results into StepResult
  3. Update plan status
  
Loop:
  → Next iteration → Plan phase again
```

### Planner ↔ Context Integration

Planner receives context summary:

```python
context = PlanContext(
    completed_steps={
        "S1": "Found PostgreSQL best practices",
        "S2": "Designed schema with indexes"
    }
)

# Planner uses completed step results for decision-making
```

## Configuration

### Planner Settings

```yaml
# config/config.template.yml
agent:
  protocols:
    planner:
      enabled: true
      llm_role: planner  # Model role for planning
      max_iterations: 8  # Maximum StrangeLoop iterations
      concurrency:
        max_parallel_steps: 2
        max_parallel_subagents: 1
        max_parallel_tools: 3
```

### Resolution

```python
from soothe.core.resolver import resolve_planner, resolve_loop_planner

# Resolve planner protocols
planner = resolve_planner(config)  # PlannerProtocol
loop_planner = resolve_loop_planner(config)  # LoopPlannerProtocol

# Returns: LLMPlanner implementations
```

## Testing

### Unit Tests

**Locations**:
- `packages/soothe/tests/unit/cognition/planning/`
- `packages/soothe/tests/unit/protocols/`

Tests verify:
- Plan creation and step ordering
- DAG dependency tracking
- Plan revision logic
- StatusAssessment accuracy
- Continuation routing decisions
- Concurrency limit enforcement

## Design Rationale

### Why Two-Phase Architecture?

Token efficiency (RFC-604):
- **Phase 1** (StatusAssessment): Lightweight check for completion
- **Phase 2** (PlanGeneration): Expensive planning only when needed
- Avoids generating full plans when goal already complete

### Why DAG Dependencies?

Complex goals require ordered execution:
- Some steps depend on others (design → implementation)
- DAG enables parallel execution where possible
- Prevents invalid execution ordering

### Why Concurrency Limits?

Controlled concurrency (RFC-000 Principle 8):
- Prevents rate-limit exhaustion
- Avoids resource contention
- Configurable per deployment

## Specification Reference

- **RFC-304**: Planner Protocol Architecture
- **RFC-604**: Reason Phase Robustness (two-phase architecture)
- **RFC-211**: Layer2 Tool Result Optimization
- **RFC-226**: Continuation-Aware Plan Assess
- **RFC-200**: Autonomous Goal Management

## Related Documentation

- [StrangeLoop Architecture](../sloop.md)
- [LoopRunner Protocol](loop-runner.md)
- [LoopWorkingMemory Protocol](working-memory.md)