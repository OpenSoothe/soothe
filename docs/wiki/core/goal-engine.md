# GoalEngine

Autonomous goal management for long-running complex workflows.

---

## Overview

GoalEngine (`soothe.core.goal_engine`) implements Layer 3 of Soothe's three-layer execution architecture, providing autonomous goal management for long-running complex workflows. It manages goal DAGs with dependencies, priorities, and dynamic restructuring capabilities.

**RFC**: [RFC-200](../../specs/RFC-200-autonomous-goal-management.md)

---

## Architecture

### Goal DAG Management

GoalEngine manages goals as a Directed Acyclic Graph (DAG):

```
GoalEngine Architecture
├─ Goal DAG
│  ├─ Goals with dependencies
│  ├─ Priority-based scheduling
│  └─ Dynamic restructuring
│
├─ Goal Lifecycle
│  ├─ Created → Ready → Running → Completed
│  ├─ Backoff reasoning
│  └─ Failure handling
│
├─ Goal Execution
│  ├─ PERFORM delegation (StrangeLoop)
│  ├─ REFLECT evaluation
│  └─ DAG update
│
└─ Scheduled Tasks
   ├─ Wall-clock scheduling
   ├─ Webhook triggers
   └─ Dreaming (background processing)
```

---

## Core Concepts

### Goal DAG

Goals organized as a directed acyclic graph:

```python
class GoalDAG:
    """Directed Acyclic Graph of goals."""
    
    goals: dict[str, Goal]      # Goal registry
    dependencies: dict[str, list[str]]  # Dependency edges
    
    def add_goal(self, goal: Goal):
        """Add goal to DAG."""
    
    def get_ready_goals(self) -> list[Goal]:
        """Get goals ready for execution."""
    
    def update_dependencies(self, goal_id: str, deps: list[str]):
        """Update goal dependencies."""
```

### Goal

Individual goal in the DAG:

```python
class Goal:
    """Single goal in the DAG."""
    
    # Identity
    id: str                 # Goal identifier
    description: str        # Goal description
    
    # State
    status: GoalStatus      # created, ready, running, completed, failed
    priority: int           # Execution priority
    
    # Dependencies
    dependencies: list[str] # Required goals
    dependents: list[str]   # Goals that depend on this
    
    # Execution
    assigned_thread: str | None  # Assigned thread ID
    plan_result: PlanResult | None  # Execution result
    
    # Timing
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    
    # Metadata
    tags: list[str]         # Goal tags
    criticality: float      # Importance score
    directives: GoalDirectives  # Execution directives
```

### Goal Status

Lifecycle states:

```python
class GoalStatus:
    """Goal lifecycle states."""
    
    CREATED = "created"      # Initial state
    READY = "ready"          # Dependencies satisfied
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"        # Execution failed
    BACKED_OFF = "backed_off"  # Backed off after failure
```

---

## Goal Lifecycle

### 1. Goal Creation

Create goals with dependencies:

```python
# Create simple goal
goal = Goal(
    id="goal-123",
    description="Analyze codebase structure",
    priority=5
)

# Create goal with dependencies
goal = Goal(
    id="goal-456",
    description="Implement feature",
    dependencies=["goal-123"],  # Wait for analysis
    priority=10
)

# Add to DAG
goal_engine.add_goal(goal)
```

### 2. Dependency Resolution

Check and resolve dependencies:

```python
def get_ready_goals(self) -> list[Goal]:
    """Get goals ready for execution."""
    
    ready_goals = []
    for goal in self.goals.values():
        # Check status
        if goal.status != GoalStatus.CREATED:
            continue
        
        # Check dependencies
        deps_satisfied = all(
            self.goals[dep_id].status == GoalStatus.COMPLETED
            for dep_id in goal.dependencies
        )
        
        if deps_satisfied:
            goal.status = GoalStatus.READY
            ready_goals.append(goal)
    
    # Sort by priority
    return sorted(ready_goals, key=lambda g: g.priority)
```

### 3. Goal Execution

Delegate execution to StrangeLoop:

```python
async def perform_goal(self, goal: Goal):
    """Delegate goal execution to StrangeLoop."""
    
    # Update status
    goal.status = GoalStatus.RUNNING
    goal.started_at = datetime.now()
    
    # Create thread
    thread_id = f"{base_tid}__goal_{goal.id}"
    goal.assigned_thread = thread_id
    
    # Delegate to StrangeLoop (via daemon dispatch in RFC-222)
    # StrangeLoop executes Plan → Execute loop
    plan_result = await self.dispatch_to_sloop(goal)
    
    return plan_result
```

### 4. Goal Completion

Handle goal completion:

```python
def complete_goal(self, goal_id: str, plan_result: PlanResult):
    """Mark goal as completed."""
    
    goal = self.goals[goal_id]
    goal.status = GoalStatus.COMPLETED
    goal.plan_result = plan_result
    goal.completed_at = datetime.now()
    
    # Update dependents
    self.update_dependent_goals(goal_id)
```

### 5. Goal Failure

Handle goal failure with backoff:

```python
async def fail_goal(self, goal_id: str, evidence: EvidenceBundle):
    """Handle goal failure."""
    
    goal = self.goals[goal_id]
    
    # Apply backoff reasoning
    backoff_result = await self.apply_backoff_reasoning(goal, evidence)
    
    if backoff_result.should_retry:
        # Backoff and retry
        goal.status = GoalStatus.BACKED_OFF
        await self.schedule_retry(goal, backoff_result)
    else:
        # Permanent failure
        goal.status = GoalStatus.FAILED
        goal.evidence = evidence
```

---

## Backoff Reasoning

### Backoff Architecture

Sophisticated failure handling with reasoning:

```python
class BackoffReasoner:
    """Reasoning-based backoff system."""
    
    async def analyze_failure(
        self,
        goal: Goal,
        evidence: EvidenceBundle
    ) -> BackoffResult:
        """Analyze failure and decide backoff strategy."""
        
        # Failure classification
        failure_type = self.classify_failure(evidence)
        
        # Retry decision
        should_retry = self.decide_retry(goal, failure_type)
        
        # Backoff strategy
        strategy = self.select_strategy(failure_type)
        
        return BackoffResult(
            should_retry=should_retry,
            strategy=strategy,
            reasoning=self.generate_reasoning(failure_type)
        )
```

### Backoff Strategies

```python
class BackoffStrategy:
    """Backoff strategies."""
    
    EXPONENTIAL = "exponential"  # Exponential backoff
    LINEAR = "linear"            # Linear backoff
    FIXED = "fixed"              # Fixed delay
    ADAPTIVE = "adaptive"        # Adaptive based on failure type
```

### Failure Classification

```python
def classify_failure(self, evidence: EvidenceBundle) -> FailureType:
    """Classify failure type from evidence."""
    
    # Analyze evidence
    analysis = self.analyze_evidence(evidence)
    
    # Classify failure
    if analysis.tool_failure:
        return FailureType.TOOL_ERROR
    elif analysis.resource_exhausted:
        return FailureType.RESOURCE_LIMIT
    elif analysis.goal_unclear:
        return FailureType.GOAL_AMBIGUOUS
    elif analysis.strategy_failed:
        return FailureType.STRATEGY_MISMATCH
    else:
        return FailureType.UNKNOWN
```

---

## Dynamic Goal Restructuring

### Goal Mutation

Modify goals during execution:

```python
async def mutate_goal(self, goal_id: str, mutation: GoalMutation):
    """Mutate goal based on execution learning."""
    
    goal = self.goals[goal_id]
    
    # Apply mutation
    if mutation.update_description:
        goal.description = mutation.new_description
    
    if mutation.add_dependencies:
        goal.dependencies.extend(mutation.new_deps)
    
    if mutation.update_priority:
        goal.priority = mutation.new_priority
    
    # Validate DAG
    self.validate_dag_integrity()
```

### Goal Generation

Generate new goals dynamically:

```python
async def generate_subgoals(
    self,
    parent_goal: Goal,
    execution_result: PlanResult
) -> list[Goal]:
    """Generate subgoals from execution result."""
    
    # Analyze result
    analysis = self.analyze_execution_result(execution_result)
    
    # Identify subgoals
    subgoal_descriptions = self.identify_subgoals(analysis)
    
    # Create subgoals
    subgoals = []
    for desc in subgoal_descriptions:
        subgoal = Goal(
            id=generate_goal_id(),
            description=desc,
            dependencies=[parent_goal.id],
            priority=parent_goal.priority + 1
        )
        subgoals.append(subgoal)
    
    return subgoals
```

---

## Scheduled Tasks

### Wall-Clock Scheduling

Schedule goals at specific times:

```python
class SchedulerService:
    """Wall-clock scheduled task management."""
    
    def schedule_goal(
        self,
        goal: Goal,
        schedule_time: datetime
    ):
        """Schedule goal for execution at specific time."""
        
        task = ScheduledTask(
            goal_id=goal.id,
            schedule_time=schedule_time,
            status=ScheduledStatus.PENDING
        )
        
        self.scheduled_tasks.append(task)
    
    async def process_scheduled_tasks(self):
        """Process due scheduled tasks."""
        
        now = datetime.now()
        due_tasks = [
            t for t in self.scheduled_tasks
            if t.schedule_time <= now and t.status == ScheduledStatus.PENDING
        ]
        
        for task in due_tasks:
            await self.execute_scheduled_task(task)
```

### Webhook Triggers

Trigger goals via webhooks:

```python
class WebhookManager:
    """Webhook-triggered goal management."""
    
    async def handle_webhook(
        self,
        webhook_id: str,
        payload: dict
    ):
        """Handle webhook trigger."""
        
        webhook = self.webhooks[webhook_id]
        
        # Generate goal from webhook
        goal = self.generate_goal_from_webhook(webhook, payload)
        
        # Add to DAG
        self.goal_engine.add_goal(goal)
```

---

## Dreaming

### Background Processing

Background processing for goal optimization:

```python
class DreamingEngine:
    """Background goal processing (dreaming)."""
    
    async def process_goals_background(self):
        """Process goals in background."""
        
        # Analyze goal patterns
        patterns = await self.analyze_goal_patterns()
        
        # Optimize DAG
        optimizations = await self.identify_optimizations(patterns)
        
        # Apply optimizations
        await self.apply_dag_optimizations(optimizations)
```

---

## Goal Directives

Execution directives for goals:

```python
class GoalDirectives:
    """Execution directives for goals."""
    
    # Execution constraints
    max_iterations: int | None      # Maximum iterations
    timeout_seconds: int | None     # Timeout limit
    required_tools: list[str] | None # Required tools
    
    # Strategy hints
    preferred_strategy: str | None  # Preferred strategy
    avoid_tools: list[str] | None   # Tools to avoid
    
    # Priority modifiers
    boost_priority_on_failure: bool # Boost after failure
    deprioritize_after_n_failures: int | None # Deprioritize threshold
```

---

## Criticality Assessment

### Criticality Scoring

Score goal importance:

```python
class CriticalityAssessor:
    """Assess goal criticality."""
    
    def assess_criticality(self, goal: Goal) -> float:
        """Assess goal criticality score."""
        
        # Base criticality
        base_score = self.base_criticality(goal)
        
        # Dependency criticality
        dep_score = self.dependency_criticality(goal)
        
        # User priority
        user_score = self.user_priority_score(goal)
        
        # Combined score
        return self.combine_scores(base_score, dep_score, user_score)
```

---

## Usage Patterns

### Basic Goal Management

```python
from soothe.core.goal_engine import GoalEngine
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
goal_engine = GoalEngine(config)

# Create goal
goal = Goal(
    id="goal-123",
    description="Analyze codebase",
    priority=5
)
goal_engine.add_goal(goal)

# Get ready goals
ready_goals = goal_engine.get_ready_goals()

# Complete goal
goal_engine.complete_goal("goal-123", plan_result)
```

### Goal DAG Management

```python
# Create goal with dependencies
goal1 = Goal(id="goal-1", description="Analysis")
goal2 = Goal(id="goal-2", description="Implementation", dependencies=["goal-1"])

goal_engine.add_goal(goal1)
goal_engine.add_goal(goal2)

# goal-2 waits for goal-1 completion
ready = goal_engine.get_ready_goals()  # Only goal-1 initially
```

### Autopilot Integration

```python
# GoalEngine works with daemon AutopilotService
# Autopilot dispatches goals to StrangeLoop workers
# GoalEngine provides goal state service
```

---

## Event Types

### Goal Events
- `soothe.goal.created` - Goal creation
- `soothe.goal.ready` - Goal ready for execution
- `soothe.goal.started` - Goal execution started
- `soothe.goal.completed` - Goal completion
- `soothe.goal.failed` - Goal failure
- `soothe.goal.backed_off` - Goal backoff

### DAG Events
- `soothe.dag.updated` - DAG structure updated
- `soothe.dag.restructured` - DAG restructuring

---

## Configuration

### GoalEngine Settings

```yaml
goal_engine:
  max_goals: 100           # Maximum goals in DAG
  backoff_strategy: adaptive  # Backoff strategy
  dreaming_enabled: true   # Enable background processing
  scheduled_tasks_enabled: true  # Enable scheduled tasks
```

### Backoff Settings

```yaml
backoff:
  max_retries: 5           # Maximum retry attempts
  initial_delay: 60        # Initial delay (seconds)
  max_delay: 3600          # Maximum delay (seconds)
```

---

## Related Documentation

- **[StrangeLoop](agent-loop.md)** - Goal execution integration
- **[SootheRunner](runner.md)** - Runner orchestration
- **[Backoff Reasoning](../architecture/backoff-reasoning.md)** - Backoff details
- **[Autopilot Service](../daemon/autopilot.md)** - Daemon integration
- **[RFC-200](../../specs/RFC-200-autonomous-goal-management.md)** - Full specification

---

## API Reference

### GoalEngine Class

```python
class GoalEngine:
    """Autonomous goal management engine."""
    
    def __init__(self, config: SootheConfig):
        """Initialize engine with configuration."""
    
    # Goal management
    def add_goal(self, goal: Goal): ...
    def remove_goal(self, goal_id: str): ...
    def get_goal(self, goal_id: str) -> Goal: ...
    
    # Goal state
    def get_ready_goals(self) -> list[Goal]: ...
    def get_running_goals(self) -> list[Goal]: ...
    def get_all_goals(self) -> list[Goal]: ...
    
    # Goal lifecycle
    def complete_goal(self, goal_id: str, plan_result: PlanResult): ...
    async def fail_goal(self, goal_id: str, evidence: EvidenceBundle): ...
    
    # Goal mutation
    async def mutate_goal(self, goal_id: str, mutation: GoalMutation): ...
    async def generate_subgoals(self, parent_goal: Goal) -> list[Goal]: ...
```

### Goal Classes

```python
class Goal:
    """Single goal in DAG."""
    id: str
    description: str
    status: GoalStatus
    priority: int
    dependencies: list[str]
    ...

class GoalDAG:
    """Directed Acyclic Graph of goals."""
    goals: dict[str, Goal]
    dependencies: dict[str, list[str]]
    ...

class GoalStatus:
    """Goal lifecycle states."""
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BACKED_OFF = "backed_off"
```

---

## See Also

- **[Autonomous Mode](../user-guide/autonomous-mode.md)** - User guide
- **[Thread Management](../user-guide/thread-management.md)** - Thread handling
- **[Daemon Architecture](../daemon/README.md)** - Daemon overview