# RFC-213: AgentLoop Reasoning Quality & Robustness

**RFC**: 213
**Title**: AgentLoop Reasoning Quality & Robustness
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-200, RFC-203
**Related**: RFC-207 (Thread)

---

## Abstract

This RFC defines AgentLoop reasoning quality enhancements through progressive action strategies and two-phase Plan architecture. Progressive actions enable evidence-driven strategy refinement while two-phase Plan architecture (StatusAssessment + PlanGeneration) improves token efficiency and robustness. This consolidation unifies reasoning quality patterns previously fragmented across separate RFCs.

---

## Reasoning Quality Progressive Actions

### Progressive Plan Decisions

Evidence-driven strategy refinement through progressive decision-making:

**Progressive Decision Pattern**:
- Initial Plan: Broad strategy, coarse steps
- Mid-execution: Strategy refinement based on evidence
- Final Plan: Fine-grained steps based on learned context

### Evidence-Driven Strategy

**Evidence collection patterns**:
- Tool results: Success/failure, output length, error patterns
- Subagent results: Completion status, iteration count, evidence summaries
- Metrics: Wave metrics (tool call count, subagent tasks, errors)

**Strategy refinement triggers**:
- Evidence contradicts plan assumptions → replan
- Evidence confirms plan validity → continue
- Evidence indicates goal completion → done

### Progressive Action Implementation

```python
class ProgressiveActionStrategy(BaseModel):
    """Evidence-driven progressive action strategy."""

    evidence_threshold: float = 0.7
    """Threshold for strategy refinement decision."""

    replan_on_failure_count: int = 2
    """Failure count threshold triggering replan."""

    continue_on_success_rate: float = 0.8
    """Success rate threshold for continue decision."""

    evidence_weights: dict[str, float] = {
        "tool_success": 0.4,
        "output_quality": 0.3,
        "error_rate": 0.2,
        "iteration_progress": 0.1,
    }
    """Weighted evidence factors for decision."""
```

**Decision Logic**:
```python
def evaluate_progressive_decision(
    evidence: WaveEvidence,
    strategy: ProgressiveActionStrategy,
) -> Literal["continue", "replan", "done"]:
    # Calculate evidence score
    score = sum(
        evidence.factors[factor] * strategy.evidence_weights[factor]
        for factor in strategy.evidence_weights
    )

    # Progressive decision thresholds
    if score >= strategy.evidence_threshold:
        return "done" if evidence.goal_achieved else "continue"
    elif evidence.failure_count >= strategy.replan_on_failure_count:
        return "replan"
    else:
        return "continue"  # Default: maintain strategy
```

---

## Two-Phase Plan Architecture

### StatusAssessment + PlanGeneration

Two-phase Plan architecture improves token efficiency by separating status assessment from plan generation:

**Phase 1: StatusAssessment** (Low token cost):
- Evaluate current progress
- Assess goal distance
- Determine if replan needed
- Output: Brief status + decision

**Phase 2: PlanGeneration** (Conditional, high token cost):
- Only if replan needed
- Generate full PlanResult
- Create AgentDecision steps
- Output: Complete plan

### Implementation

```python
class TwoPhasePlanResult(BaseModel):
    """Two-phase Plan architecture output."""

    # Phase 1: StatusAssessment
    status_assessment: StatusAssessmentResult
    """Brief status + decision from Phase 1."""

    # Phase 2: PlanGeneration (conditional)
    plan_generation: PlanResult | None
    """Full plan if replan needed from Phase 2."""

class StatusAssessmentResult(BaseModel):
    """Phase 1 status assessment (low token cost)."""
    current_progress: str
    """Brief progress summary."""
    goal_distance: float
    """Estimated distance to goal (0.0-1.0)."""
    should_replan: bool
    """Whether replan is needed."""
    reasoning: str
    """Brief reasoning for assessment."""
```

### Token Efficiency

**Traditional approach**: Generate full PlanResult every iteration (high token cost)

**Two-phase approach**:
- Phase 1: StatusAssessment (~100 tokens)
- Phase 2: PlanGeneration only when needed (~500 tokens)
- Average token cost: ~200 tokens (60% reduction)

### LLMPlanner Integration

```python
class LLMPlanner:
    """Two-phase Plan implementation."""

    async def plan_two_phase(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> TwoPhasePlanResult:
        # Phase 1: StatusAssessment (always)
        status = await self._assess_status(goal, state, context)

        # Phase 2: PlanGeneration (conditional)
        if status.should_replan:
            plan = await self._generate_plan(goal, state, context, status)
        else:
            plan = None  # Reuse previous plan

        return TwoPhasePlanResult(
            status_assessment=status,
            plan_generation=plan,
        )
```

---

## Reasoning Flow Integration

### Combined Reasoning Process

```
AgentLoop Iteration:
  ├─ PLAN Phase:
  │   ├─ Two-Phase Plan Architecture:
  │   │   ├─ Phase 1: StatusAssessment
  │   │   │   ├─ Evaluate progress
  │   │   │   ├─ Assess goal distance
  │   │   │   └─ Determine replan need
  │   │   │
  │   │   ├─ Phase 2: PlanGeneration (if needed)
  │   │   │   ├─ Generate PlanResult
  │   │   │   └─ Create AgentDecision
  │   │   │
  │   │   └─ Progressive Action Strategy:
  │   │       ├─ Evidence-driven decision
  │   │       ├─ Strategy refinement
  │   │       └─ Action progression
  │   │
  │   └─ Output: PlanResult
  │
  ├─ EXECUTE Phase:
  │   ├─ Execute steps
  │   ├─ Collect evidence
  │   └─ Metrics aggregation
  │
  └─ Decision:
      ├─ Progressive decision logic:
      │   ├─ Evidence evaluation
      │   ├─ Threshold comparison
      │   └─ Strategy refinement decision
      │
      └─ "done", "continue", "replan"
```

---

## Configuration

```yaml
agentic:
  reasoning:
    progressive_actions:
      evidence_threshold: 0.7
      replan_on_failure_count: 2
      continue_on_success_rate: 0.8
      evidence_weights:
        tool_success: 0.4
        output_quality: 0.3
        error_rate: 0.2
        iteration_progress: 0.1

    two_phase_plan:
      enabled: true
      phase1_max_tokens: 150
      phase2_max_tokens: 500
```

---

## Implementation Status

- ✅ Progressive action strategy model
- ✅ Evidence-driven decision logic
- ✅ Two-phase Plan architecture (StatusAssessment + PlanGeneration)
- ✅ Token efficiency optimization
- ✅ LLMPlanner integration
- ✅ Combined reasoning flow
- ⚠️ Evidence weight tuning (ongoing)

---

## References

- RFC-200: AgentLoop Plan-Execute Loop Architecture
- RFC-203: AgentLoop State & Memory Architecture
- RFC-603: Reasoning Quality Progressive Actions (original source)
- RFC-604: Reason Phase Robustness (original source)

---

## Changelog

### 2026-04-17
- Consolidated RFC-213 (Progressive Actions) and RFC-213 (Two-Phase Plan) into unified reasoning quality architecture
- Combined evidence-driven progressive action strategy with two-phase Plan architecture
- Unified reasoning flow integration with token efficiency optimization
- Maintained implementation status and configuration details

---

*AgentLoop reasoning quality through progressive evidence-driven strategy refinement and two-phase Plan architecture for token efficiency.*