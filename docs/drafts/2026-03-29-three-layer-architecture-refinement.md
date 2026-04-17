# Three-Layer Architecture Refinement Proposal

**Created**: 2026-03-29
**Purpose**: Establish RFC-200 and RFC-200 as foundational documents for the three-layer architecture, merge RFC-200 (merged) into RFC-200, and address documentation gaps

---

## Executive Summary

The current RFC architecture has evolved organically, resulting in:
1. **RFC-200 (merged)** should be merged into **RFC-200** (both address Layer 3 goal management)
2. **RFC-200** and **RFC-200** should be established as the foundational documents for the three-layer architecture
3. **RFC-200** has major gaps between documented "intended architecture" and actual implementation
4. **Layer relationships** are unclear across RFCs, causing architectural fragmentation

---

## Three-Layer Architecture Model (Target State)

```
Layer 3: Autonomous Loop (RFC-200)
├─ Purpose: Goal DAG management for long-running, complex workflows
├─ Loop: Goal/Goals → PLAN (goal-level) → PERFORM → REFLECT → Update → Repeat
├─ Scope: Multi-goal orchestration, goal dependencies, dynamic goal management
├─ Max iterations: Large (10-50+ for complex problems)
└─ Foundation: Delegates to Layer 2 for single-goal execution (PERFORM stage)

Layer 2: Agentic Loop (RFC-200)
├─ Purpose: Execute single goals through iterative refinement
├─ Loop: PLAN → ACT → JUDGE (max iterations: ~8)
├─ Scope: LLM-driven step planning, goal-oriented execution and evaluation
├─ Foundation: Uses Layer 1 for tool/subagent execution (ACT stage)
└─ Output: JudgeResult for Layer 3's REFLECT stage

Layer 1: Tool Loop (deepagents/langchain)
├─ Purpose: Execute specific actions via LangGraph runtime
├─ Loop: Model → Tool calls → Model turn loop
├─ Scope: Individual tool/subagent invocations
└─ Foundation: LangGraph native execution
```

---

## Current Architecture Gaps Analysis

### Gap 1: RFC-200 (merged) Should Be Part of RFC-200

**Current State**:
- RFC-200: Autonomous iteration loop (goal creation, scheduling, execution)
- RFC-200 (merged): Dynamic goal management during reflection (goal DAG mutations)

**Problem**:
- Both RFCs address Layer 3 concerns
- RFC-200 (merged) extends RFC-200's reflection mechanism
- Splitting creates unnecessary complexity and cross-references
- Goal DAG management is inherently dynamic - should be documented as one cohesive system

**Solution**: Merge RFC-200 (merged) content into RFC-200 sections:
- GoalDirective → Section in RFC-200 "Dynamic Goal Management"
- GoalContext → Section in RFC-200 "Reflection Context"
- Safety mechanisms → Section in RFC-200 "Goal DAG Safety"
- Integration → Already implemented in `_runner_autonomous.py`

### Gap 2: RFC-200 Missing Layer 3 Architecture Position

**Current State**: RFC-200 documents autonomous loop but doesn't explicitly position it as Layer 3

**Problem**:
- Unclear relationship to Layer 2 (agentic loop)
- No explicit delegation model (PERFORM → Layer 2)
- Missing integration with Layer 2's JudgeResult

**Solution**: Add "Architecture Position" section to RFC-200:
- Define Layer 3 scope explicitly
- Specify PERFORM stage delegates to RFC-200's full loop
- Detail how Layer 2 JudgeResult informs Layer 3 REFLECT
- Establish three-layer hierarchy diagram

### Gap 3: RFC-200 Documents Scaffolding, Not Active Runtime

**Current State**: RFC-200 says "transitional implementation... observe → act → verify is active"

**Problem**:
- Documents intended PLAN → ACT → JUDGE but implementation differs
- AgentDecision designed for single tool, not multi-step execution
- No iteration-scoped planning (planning happens before loop)
- JudgeResult exists but unused - uses heuristics instead
- Unclear layer positioning (Layer 2 foundation for Layer 1)

**Solution**: Fundamental RFC-200 redesign (major revision):
- Define Layer 2 architecture position explicitly
- Redesign AgentDecision for multi-step execution decisions
- Specify iteration-scoped PLAN phase (inside loop)
- Wire structured JUDGE phase with goal-oriented evaluation
- Define clear "continue steps OR replan" iteration semantics
- Establish Layer 2 → Layer 1 delegation model

### Gap 4: RFC-200 Orthogonal to Layer 2

**Current State**: RFC-200 (DAG execution) treats steps as static predetermined plan

**Problem**:
- Layer 2 expects dynamic step selection based on judgment
- RFC-200 StepScheduler executes fixed DAG, not LLM-driven decisions
- Creates architectural tension between static and dynamic execution models

**Solution**: Clarify RFC-200 role:
- DAG execution is a **tool** for Layer 2's ACT phase
- Layer 2 LLM decides which steps to execute (dynamic selection)
- StepScheduler provides dependency-safe execution when LLM chooses steps
- Support both static DAG (simple cases) and dynamic selection (complex cases)

### Gap 5: Layer Relationships Unclear Across RFCs

**Current State**: RFCs mention relationships but don't establish hierarchy

**Problem**:
- RFC-200, RFC-200, RFC-200 all mention each other but don't define layer stack
- No clear delegation models between layers
- Implementation guides don't follow layer boundaries

**Solution**: Establish layer foundations:
- Add "Architecture Layer" metadata to RFC-200, RFC-200, RFC-200
- Update RFC-000 (System Conceptual Design) to define three-layer model
- Create cross-reference section in each foundational RFC
- Update RFC index with layer annotations

---

## Proposed RFC Refinement Plan

### Phase 1: Merge RFC-200 (merged) into RFC-200

**Actions**:
1. Add new sections to RFC-200:
   - §5.5 "Dynamic Goal Management" (from RFC-200 (merged) §3)
   - §5.6 "Goal DAG Safety" (from RFC-200 (merged) §6)
   - §5.7 "Goal Context for Reflection" (from RFC-200 (merged) §2)
2. Update RFC-200 reflection section to accept `goal_context` and return `goal_directives`
3. Add GoalDirective, GoalContext models to RFC-200 data models section
4. Merge RFC-200 (merged) examples into RFC-200 use cases
5. Deprecate RFC-200 (merged) with merge notice

### Phase 2: Establish RFC-200 as Layer 3 Foundation

**Actions**:
1. Add new §2 "Architecture Layer Position":
   - Define Layer 3 scope and responsibilities
   - Three-layer hierarchy diagram
   - Delegation model: PERFORM → Layer 2 (RFC-200)
   - Integration with Layer 2 JudgeResult
2. Update abstract to emphasize Layer 3 role
3. Update title: "Layer 3: Autonomous Goal Management Loop"
4. Add cross-reference to RFC-200 as Layer 2 foundation
5. Update RFC-000 principles section to mention three-layer architecture

### Phase 3: Redesign RFC-200 as Layer 2 Foundation

**Actions**:
1. Add new §2 "Architecture Layer Position":
   - Define Layer 2 scope and responsibilities
   - Three-layer hierarchy diagram
   - Delegation model: ACT → Layer 1 (deepagents)
   - Integration with Layer 3 PERFORM stage
2. Fundamental redesign of core schemas:
   - AgentDecision → Multi-step execution decisions
   - Add StepAction model for step-level orchestration
   - Specify iteration-scoped planning (not pre-loop)
3. Wire PLAN → ACT → JUDGE as active runtime:
   - Remove "transitional implementation" language
   - Define iteration flow with "continue OR replan" semantics
   - Specify goal-oriented judgment logic
4. Update abstract to emphasize Layer 2 role
5. Update title: "Layer 2: Agentic Goal Execution Loop"

### Phase 4: Clarify RFC-200 Role in Layer 2

**Actions**:
1. Add §2.1 "Role in Layer 2 Architecture":
   - DAG execution as tool for Layer 2 ACT phase
   - Static vs dynamic step selection models
   - When StepScheduler is appropriate
2. Update abstract to clarify complementary role
3. Add cross-reference to RFC-200 Layer 2 positioning

### Phase 5: Update RFC-000 and Cross-References

**Actions**:
1. Update RFC-000 §"Design Principles":
   - Add Principle 11: "Three-layer execution architecture"
   - Define layer hierarchy and delegation model
2. Update RFC index:
   - Add "Layer" column to RFC tables
   - Reorder by layer (L3 → L2 → L1)
   - Mark RFC-200 (merged) as "Merged into RFC-200"
3. Update RFC cross-references across all specs

### Phase 6: Update Implementation State

**Actions**:
1. For each merged/redesigned RFC:
   - Update status from "Draft" to "Revised"
   - Add changelog entry documenting layer positioning
   - Note implementation gaps (especially RFC-200)
2. Create implementation roadmap:
   - RFC-200: ✅ Already implemented (including RFC-200 (merged) content)
   - RFC-200: ❌ Major implementation gaps (needs IG)
   - RFC-200: ✅ Implemented but needs Layer 2 integration
3. Prioritize RFC-200 implementation as critical

---

## RFC Title Updates

**RFC-200**: "Layer 3: Autonomous Goal Management Loop"
- Emphasizes Layer 3 positioning and goal management scope

**RFC-200**: "Layer 2: Agentic Goal Execution Loop"
- Emphasizes Layer 2 positioning and single-goal execution scope

**RFC-200**: "DAG-Based Step Execution and Concurrency Control"
- Clarifies role as execution infrastructure (complementary to Layer 2)

**RFC-200 (merged)**: DEPRECATED - Merged into RFC-200

---

## Expected Outcomes

1. **Clear layer architecture**: RFC-200 (L3) and RFC-200 (L2) become foundational documents
2. **Reduced complexity**: One RFC for Layer 3 (merged), one for Layer 2 (redesigned)
3. **Better implementation alignment**: RFC-200 documents actual expected runtime
4. **Clear delegation models**: Each layer explicitly delegates to lower layer
5. **RFC index clarity**: Layer annotations and logical ordering

---

## Implementation Gaps After Refinement

### RFC-200 (Layer 3): ✅ Already Implemented
- GoalEngine with DAG scheduling (RFC-200)
- Dynamic goal management (RFC-200 (merged) already in code)
- Reflection with goal directives
- Safety mechanisms and validation
- **Gap**: Missing explicit Layer 2 delegation (PERFORM → RFC-200 loop)

### RFC-200 (Layer 2): ❌ Major Implementation Required
- AgentDecision redesign for multi-step execution
- Iteration-scoped planning (PLAN inside loop)
- Structured JudgeEngine integration
- Goal-oriented evaluation logic
- "Continue steps OR replan" iteration flow
- **Requires**: New implementation guide (IG-XXX)

### RFC-200 (Execution Infrastructure): ✅ Implemented
- StepScheduler with DAG execution
- ConcurrencyController with semaphores
- Progressive recording
- **Gap**: Needs Layer 2 integration (dynamic step selection)

---

## Next Steps

1. **Review this draft** with user for alignment
2. **Execute Phase 1-6** refinement actions
3. **Run `specs-refine`** to validate all changes
4. **Create RFC-200 implementation guide** (priority)
5. **Update implementation** to match refined specs
6. **Run `review`** for compliance verification

---

## Questions for User Confirmation

1. Does the three-layer architecture model match your expectations?
2. Should we proceed with merging RFC-200 (merged) into RFC-200?
3. Should RFC-200 undergo fundamental redesign to match Layer 2 expectations?
4. Are the layer positioning and delegation models correct?
5. Should we prioritize RFC-200 implementation after refinement?

---

## References

- RFC-200: Autonomous Iteration Loop (current)
- RFC-200: Agentic Loop Execution (current)
- RFC-200 (merged): Dynamic Goal Management (to merge)
- RFC-200: DAG-Based Execution
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- User expectations discussion (2026-03-29)