# RFC-213: AgentLoop Reasoning Quality & Robustness

**RFC**: 213
**Title**: AgentLoop Reasoning Quality & Robustness
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Last Updated**: 2026-05-05 (IG-399: progressive planning removed; pre-generate evidence probe added)
**Dependencies**: RFC-200, RFC-203
**Related**: RFC-207 (Thread), RFC-214 (plan-context human), RFC-603, RFC-604, IG-376

---

## Abstract

This RFC defines AgentLoop reasoning quality enhancements through two-phase Plan architecture. Current runtime behavior removes progressive-planning requirements and instead grounds `plan-generate` with a bounded pre-generate evidence probe before generation. `PlanGeneration` now emits flattened decision fields rather than a nested `decision` object.

---

## Reasoning Quality Progressive Actions (Historical)

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

**Phase 1: StatusAssessment** (Low token cost; IG-372 assess-only prompt):
- Evaluate current progress (`goal_progress`, `confidence`)
- Set `status` to `continue`, `replan`, or `done`
- Set `require_goal_completion` when `status="done"` and a synthesis pass is still required
- Output: `StatusAssessment` only (no `next_action` / `brief_reasoning` on this schema)

**Phase 2: PlanGeneration** (Conditional, higher token cost; IG-329 plan-generate prompt):
- Runs when `status != "done"` (not only on “replan” wording—both `continue` and `replan` may need refreshed steps)
- Output: `PlanGeneration` with `plan_action`, `decision` (when `plan_action="new"`), `next_action` only
- Merged with phase 1 in `LLMPlanner._combine_results` into `PlanResult` (RFC-604 §7.2)

### Implementation

Normative field lists and merge behavior: **RFC-604** and `soothe.core.agent_loop.state.schemas` (`StatusAssessment`, `PlanGeneration`, `PlanResult`). Code entry point: `soothe.core.agent_loop.core.planner.LLMPlanner.plan()` (assess then conditional generate; IG-372 prompt split, IG-329 trimmed plan-generate schema).

### Token Efficiency

**Traditional approach**: Single large structured plan+assess payload every iteration (high token cost, truncation risk).

**Two-phase approach**:
- Phase 1: compact `StatusAssessment` call (~tens to low hundreds of tokens; assess-only instructions)
- Phase 2: `PlanGeneration` only when execution must continue (~hundreds of tokens; policies + `plan_generate` instructions)
- When `status="done"` after phase 1, phase 2 is skipped entirely

### LLMPlanner Integration

At a high level: `plan()` builds `plan_phase="assess"` messages, invokes structured `StatusAssessment`, then—if not done—builds `plan_phase="generate"` messages, appends assess summary as an extra `SystemMessage`, invokes structured `PlanGeneration`, and returns `_combine_results(assessment, plan_result)`. See RFC-604 and `planner.py` for retries and evidence adjustments.

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
  │   │   ├─ Phase 2: PlanGeneration (if status != done; IG-329 schema)
  │   │   │   ├─ Structured PlanGeneration (plan_action, decision, next_action)
  │   │   │   └─ Merge with assess → PlanResult
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
- RFC-603: Reasoning Quality Progressive Actions (original source); **§3.2** documents `goal_progress` as assess-model output only (IG-376)
- RFC-604: Plan Phase Robustness (original source); abstract notes `goal_progress` / `confidence` post-processing split
- RFC-214: Loop message surface — plan-context `Goal` + `Execute iteration` header for assess

---

## Changelog

### 2026-05-04
- Documented alignment with IG-376 / RFC-603 §3.2 / RFC-604 / RFC-214 for StatusAssessment `goal_progress` and plan human formatting.
- IG-329: two-phase section updated for assess-only `StatusAssessment`, trimmed `PlanGeneration`, and plan-generate instructions (`plan_generate_instructions.xml`).

### 2026-04-17
- Consolidated RFC-213 (Progressive Actions) and RFC-213 (Two-Phase Plan) into unified reasoning quality architecture
- Combined evidence-driven progressive action strategy with two-phase Plan architecture
- Unified reasoning flow integration with token efficiency optimization
- Maintained implementation status and configuration details

---

*AgentLoop reasoning quality through progressive evidence-driven strategy refinement and two-phase Plan architecture for token efficiency.*