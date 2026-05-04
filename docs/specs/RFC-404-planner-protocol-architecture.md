# RFC-404: PlannerProtocol Architecture

**RFC**: 404
**Title**: PlannerProtocol: Plan Creation & Two-Phase Implementation Pattern
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-400
**Related**: `RFC-201-agentloop-plan-execute-loop.md` (AgentLoop)

---

## Abstract

This RFC defines PlannerProtocol, Soothe's plan creation and revision interface for complex goal decomposition. PlannerProtocol provides plan creation, revision, and reflection methods with LLMPlanner default implementation using two-phase architecture (`StatusAssessment` then conditional `PlanGeneration`, merged into `PlanResult`; RFC-604, IG-372/IG-329) for token efficiency. This protocol serves AgentLoop and autonomous goal management planning needs.

---

## Protocol Interface

```python
class PlannerProtocol(Protocol):
    """Plan creation and revision protocol."""

    async def create_plan(
        self,
        goal: str,
        context: PlanContext,
    ) -> Plan:
        """Create initial plan for goal."""
        ...

    async def revise_plan(
        self,
        plan: Plan,
        reflection: str,
    ) -> Plan:
        """Revise plan based on reflection."""
        ...

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
        layer2_reason: PlanResult | None = None,
    ) -> Reflection:
        """Reflect on plan execution for revision decision."""
        ...
```

---

## Data Models

### Plan

```python
class Plan(BaseModel):
    """Structured plan decomposition."""
    goal: str
    """Goal description."""
    steps: list[PlanStep]
    """Ordered execution steps."""
    current_index: int = 0
    """Current step index."""
    status: Literal["pending", "active", "completed", "failed"]
    """Plan status."""
    concurrency: ConcurrencyPolicy
    """Concurrency configuration."""
```

### PlanStep

```python
class PlanStep(BaseModel):
    """Single step in plan."""
    id: str
    """Step identifier."""
    description: str
    """Human-readable step description."""
    execution_hint: str | None
    """Hint for execution (tool, subagent, remote)."""
    status: Literal["pending", "in_progress", "completed", "failed"]
    """Step status."""
    result: str | None
    """Step execution result."""
    depends_on: list[str] = []
    """Dependencies for DAG scheduling."""
```

### PlanContext

```python
class PlanContext(BaseModel):
    """Context for plan creation."""
    recent_messages: list[str]
    """Recent conversation excerpts."""
    available_capabilities: list[str]
    """Available tools, subagents, skills."""
    completed_steps: list[str]
    """Already completed step descriptions."""
```

### Reflection

```python
class Reflection(BaseModel):
    """Reflection on plan execution."""
    assessment: str
    """Overall progress assessment."""
    should_revise: bool
    """Whether plan needs revision."""
    feedback: str
    """Guidance for revision."""
    goal_directives: list[GoalDirective] = []
    """DAG restructuring actions (Layer 3 only)."""
```

---

## LLMPlanner Implementation

### Two-Phase Architecture Pattern

**Note**: Two-phase Plan execution is Layer 2 implementation detail, not protocol requirement. LLMPlanner uses this pattern for efficiency.

**Phase 1: StatusAssessment** (Low token cost; assess-only system prompt per IG-372):
- Emit structured `StatusAssessment` (`status`, `goal_progress`, `confidence`, `require_goal_completion`)

**Phase 2: PlanGeneration** (Conditional, higher token cost; skipped when `status="done"`):
- Emit structured `PlanGeneration` (`plan_action`, `decision`, `next_action` only; IG-329)
- Uses execution policies plus `plan_generate_instructions`
- Merged with phase 1 in AgentLoop’s `LLMPlanner` into `PlanResult` for execution

**Implementation** (in Layer 2 AgentLoop, RFC-201):
```python
# Two-phase Plan execution is Layer 2 implementation
# PlannerProtocol interface remains protocol-level (no phases)
class LLMPlanner(PlannerProtocol):
    """Default implementation using two-phase pattern."""

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        # Full plan generation (no two-phase on initial plan)
        prompt = build_plan_prompt(goal, context)
        response = await self._model.ainvoke(prompt)
        return Plan.model_validate_json(response.content)

    # Two-phase execution happens in AgentLoop (RFC-201)
    # Not in PlannerProtocol implementation
```

**Separation**: PlannerProtocol defines interface, Layer 2 implements execution patterns (two-phase, progressive).

---

## Design Principles

### 1. Runtime-Agnostic Interface

PlannerProtocol carries no runtime dependencies:
- No LangGraph references
- No langchain model references
- Abstract Plan/Step/Reflection models
- Implementations choose runtime

### 2. Optional Protocol

Simple queries bypass planning:
- Direct CoreAgent execution
- No plan overhead
- Only complex goals use planner

### 3. Hierarchical Plan Support

Plans support hierarchical decomposition:
- Goal → Steps
- Step → Subgoals (via AgentLoop)
- Dependency DAG structure
- Concurrency policies

---

## Configuration

```yaml
# Planning is configured on SootheConfig.agentic (see packages/soothe/src/soothe/config/config.yml).
# LLMPlanner / two-phase StatusAssessment + PlanGeneration (RFC-604, IG-372, IG-329):
# packages/soothe/src/soothe/core/agent_loop/core/planner.py
agentic:
  max_iterations: 10
  reject_done_at_iteration_zero: false
  goal_completion_mode: llm_only
  # ... (full template in repo)
```

---

## Implementation Status

- ✅ PlannerProtocol interface
- ✅ Plan/PlanStep/Reflection data models
- ✅ LLMPlanner default implementation
- ✅ Plan creation from goal + context
- ✅ Plan revision from reflection
- ✅ Reflection generation
- ✅ Goal directive support (Layer 3)
- ✅ Dependency DAG structure
- ⚠️ Two-phase execution pattern (Layer 2 RFC-201 implementation)

---

## References

- RFC-000: System Conceptual Design
- RFC-201: AgentLoop Plan-Execute Loop Architecture (two-phase execution)
- RFC-200: GoalEngine Goal DAG Management
- RFC-001: Core Modules Architecture (original Module 3)

---

## Changelog

### 2026-05-04
- Abstract and two-phase bullets aligned with RFC-604 / IG-372 / IG-329 (`StatusAssessment` fields, trimmed `PlanGeneration`, plan-generate prompt fragment).

### 2026-04-17
- Consolidated RFC-001 Module 3 (PlannerProtocol) with plan architecture design
- Defined protocol interface without two-phase implementation details (stays in RFC-201)
- Clarified separation: Protocol interface vs Layer 2 execution patterns
- Maintained hierarchical plan support and goal directive integration
- Preserved runtime-agnostic design principle

---

*PlannerProtocol plan creation and revision interface with LLMPlanner default implementation. Two-phase execution pattern implemented in Layer 2 (RFC-201), not in protocol.*