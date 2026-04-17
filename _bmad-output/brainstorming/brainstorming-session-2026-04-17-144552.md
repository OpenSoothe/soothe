---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Designing unified architecture for Soothe long-running autonomous agents with GoalEngine-driven execution and AgentLoop orchestration'
session_goals: 'Novel middleware patterns, goal decomposition strategies, evidence flow architectures, unified context management model, architectural isolation between AgentLoop and CoreAgent'
selected_approach: 'AI-Recommended'
techniques_used: ['First Principles Thinking', 'Morphological Analysis', 'Cross-Pollination', 'Emergent Thinking']
ideas_generated: 35
context_file: ''
technique_execution_complete: true
---

# Brainstorming Session Results

**Facilitator:** Xiaming
**Date:** 2026-04-17-144552

## Session Overview

**Topic:** Designing unified architecture for Soothe long-running autonomous agents with GoalEngine-driven execution and AgentLoop orchestration

**Goals:** Novel middleware patterns, goal decomposition strategies, evidence flow architectures, unified context management model, architectural isolation between AgentLoop and CoreAgent

### Session Setup

**Architectural Challenge Areas Identified:**
- Context unification: Unified model for history, memory, state, and checkpoint in AgentLoop
- Dynamic goal evolution: Evidence-based feedback for goal state updates
- Thread orchestration: AgentLoop coordination of multiple CoreAgent threads
- Middleware injection: Integration without violating architectural isolation principles
- Framework alignment: Maintaining deepagents ecosystem compatibility

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** Unified architecture design with focus on multi-component integration (GoalEngine, AgentLoop, CoreAgent, context management)

**Recommended Techniques:**

1. **First Principles Thinking:** Strip away assumptions about agent architecture patterns to rebuild from fundamental truths about long-running autonomous execution. Establishes architectural bedrock.

2. **Morphological Analysis:** Systematically explore ALL parameter combinations for GoalEngine approaches × AgentLoop patterns × middleware injection strategies × context models. Maps comprehensive solution space.

3. **Cross-Pollination:** Transfer successful patterns from distributed systems, operating systems, game AI, biological homeostasis mechanisms. Injects novel architectural patterns beyond current agent frameworks.

4. **Emergent Thinking:** Allow unified architecture to emerge organically from systematic exploration and creative innovation. Creates cohesive integration rather than forced stitching.

**AI Rationale:** Multi-component architecture with interdependent variables requires foundation-setting (First Principles), systematic exploration (Morphological Analysis), creative novelty (Cross-Pollination), and organic synthesis (Emergent Thinking) to discover unified models that don't exist in current frameworks.

**Estimated Session Duration:** 60-85 minutes

## Technique Execution Results

### First Principles Thinking

**Interactive Focus:** Stripping away all assumptions about agent architecture patterns to rebuild from fundamental truths about long-running autonomous execution

**Key Breakthroughs:**

**[Category #1]**: Goal Evolution Ontology
_Concept_: Complex goals are ontologically unknowable upfront - they exist as evolving entities that transform through solving. GoalEngine isn't just "updating" goals, it's participating in goal becoming.
_Novelty_: Shifts from "dynamic goal management" (a feature) to "goal ontology is evolutionary by nature" (a fundamental truth about complex problem-solving itself)

**[Category #2]**: Unbounded Context Access Principle
_Concept_: AgentLoop requires access to history threads, results, and memory without temporal boundary - not just "infinite loop" but unbounded retrieval authority. The loop determines what info to retrieve for specific goal solving, making it the context arbiter.
_Novelty_: Moves beyond "AgentLoop has context" to "AgentLoop has unbounded retrieval authority over all execution history" - temporal boundary removal is the fundamental requirement

**[Category #3]**: Integrated Goal-Step-Evidence Architecture
_Concept_: Goal-step-evidence is integrated, not complementary - they form a unified execution fabric rather than separate layers. This integration is fundamental, not optional.
_Novelty_: Rejects the "complementary info" assumption - the integration itself is the architectural truth

**[Category #4]**: AgentLoop Consciousness Principle
_Concept_: AgentLoop is the core "consciousness" of the autonomous system - the persistent observer that maintains identity across all execution threads. It's not just orchestration, it's the system's self-awareness of its own execution history.
_Novelty_: Elevates AgentLoop from "orchestrator" to "consciousness" - fundamentally different architectural requirement (identity persistence vs just coordination)

**[Category #5]**: GoalEngine Hypothesis-Backoff Cycle
_Concept_: GoalEngine hypothesizes goal structures based on current knowledge. When goal DAG paths fail, GoalEngine BACKOFFs to decision points and replans with new evidence - not just "update goals" but systematic backtracking and restructuring.
_Novelty_: Goal DAG failure triggers BACKOFF (not just marking failed) - reveals GoalEngine as active hypothesis-test-replan system, not static goal manager

**[Category #6]**: Middleware as Integration Technique (Not Fundamental)
_Concept_: Middleware is a TECHNIQUE and OPTIONAL design to integrate AgentLoop knowledge into thread execution - it's not a fundamental architectural requirement, it's one possible implementation approach for achieving integration.
_Novelty_: Middleware demoted from "architectural layer" to "optional technique" - opens possibility for alternative integration mechanisms

**[Category #7]**: Consciousness as Knowledge Unification
_Concept_: AgentLoop consciousness means unified memory/perspective - a full knowledge of past success and failure experience. Consciousness is not vague awareness but concrete: having ALL execution history, knowing what worked/failed across all threads.
_Novelty_: Defines consciousness operationally - it's the complete success/failure knowledge base, not just "persistence" or "orchestration"

**[Category #8]**: GoalEngine LLM-Driven Backoff Reasoning
_Concept_: GoalEngine backoff determined by LLM dynamically based on full picture of current knowledge - not algorithmic backtracking but reasoning-based decision about WHERE to backoff. LLM considers entire execution history to decide optimal backoff point.
_Novelty_: GoalEngine backoff is reasoning process (LLM) not rule process - fundamentally different from traditional DAG rollback algorithms

**[Category #9]**: Direct Task Provisioning Technique
_Concept_: Alternative to middleware: AgentLoop Plan-Execute fetches reasoning info and target task then sends task to CoreAgent directly - no middleware needed. AgentLoop directly provisions task with context instead of middleware injecting context.
_Novelty_: AgentLoop as direct context provider (not middleware as intermediary) - removes middleware layer entirely for one integration technique

**[Category #10]**: Observation vs Report-Back Knowledge Collection
_Concept_: Two techniques for AgentLoop consciousness acquisition: (A) AgentLoop observes thread execution + sends final report query, (B) CoreAgent threads report back to AgentLoop. Both achieve complete knowledge, different responsibility placement.
_Novelty_: Reveals knowledge collection as implementation choice (not fundamental requirement) - either AgentLoop observes or CoreAgent reports, both valid

**[Category #11]**: GoalEngine-CoreAgent LLM Unity
_Concept_: GoalEngine uses LLM with reasoning mode like CoreAgent - not separate LLM instance, same LLM type/role. GoalEngine and CoreAgent share LLM architecture, just different usage contexts (backoff reasoning vs execution).
_Novelty_: GoalEngine and CoreAgent are NOT architecturally separate LLM systems - they're unified LLM usage with different operational contexts

**[Category #12]**: Direct Provisioning Task Package Content
_Concept_: AgentLoop direct provisioning task package includes: current goal context, relevant execution history, evidence from GoalEngine backoff decision - comprehensive context package sent directly to CoreAgent without middleware injection.
_Novelty_: Task package is complete execution context bundle - proves middleware unnecessary because all context is packaged at provisioning, not injected during execution

**[Category #13]**: Self-Contained Retrieval Module Architecture
_Concept_: AgentLoop has retrieval algorithm module that's self-contained with stable APIs - can enhance algorithm in future without breaking integration. Retrieval is architectural component, not just function. Stable APIs ensure module evolution capability.
_Novelty_: Retrieval as first-class architectural module (not utility function) - stable API boundary enables algorithm evolution while preserving integration contracts

**[Category #14]**: GoalEngine Backoff Evidence Dual Structure
_Concept_: GoalEngine backoff evidence has two parts: (1) Structured goal subDAG execution status, (2) Natural language info (fail reason + gap analysis of subDAG execution from upstream goals). Evidence is hybrid structured-unstructured.
_Novelty_: Evidence structure is fundamentally dual (structured state + unstructured reasoning) - reveals GoalEngine backoff produces both machine-readable status and human/LLM-readable analysis

**[Category #15]**: Goal Context as Superset Concept
_Concept_: Goal context is superset of goal execution memory and related threads - not just current goal definition but complete context including execution memory and thread relationships. Superset means goal context > goal execution memory alone.
_Novelty_: Goal context fundamentally includes thread relationships - goal execution doesn't happen in isolation, goal context captures the thread ecosystem around goal

**[Category #16]**: Retrieval Module API Contract
_Concept_: Retrieval module stable API: `retrieve_by_goal_relevance(goal_id, execution_context, options)` - goal-centric retrieval that determines relevant history based on goal relationship, not just keyword similarity. API signature establishes goal-centricity as fundamental.
_Novelty_: Goal-centric retrieval (not query-centric) - relevance determined by goal relationship to history, establishing goal as primary retrieval dimension

**[Category #17]**: Goal Context Construction Module Architecture
_Concept_: Self-contained module for goal context construction with stable APIs, handles complex scenarios: (1) Same goal multiple threads, (2) Similar goal execution history. Module extends algorithm for context construction beyond simple retrieval.
_Novelty_: Goal context requires CONSTRUCTION (not just retrieval) - reveals context as assembled/constructed entity, not just fetched entity

**[Category #18]**: Hierarchical Status DAG Structure
_Concept_: Goal subDAG execution status as hierarchical DAG with node-level annotations:
```
GoalSubDAGStatus:
  - dag_structure: DAG<GoalNode>
  - execution_states: Map<GoalNodeID, ExecutionState>
  - backoff_points: Set<GoalNodeID>
  - evidence_annotations: Map<GoalNodeID, EvidenceBundle>

ExecutionState: {status: pending|running|success|failed|backoff_pending, thread_ids: List<ThreadID>, timestamps: {...}}

EvidenceBundle: {structured: SubDAGExecutionMetrics, unstructured: {fail_reason: str, gap_analysis: str}}
```
_Novelty_: Hierarchical structure separates DAG topology from execution state + evidence annotations - enables GoalEngine to read topology while CoreAgent reads execution state, unified structure serves both needs

**[Category #19]**: Context Construction Module API Contract
_Concept_: Goal context construction module stable API: `construct_goal_context(goal_id, options)` where options specify:
- `include_same_goal_threads: bool` (same goal multiple threads)
- `include_similar_goals: bool` (similar goal execution history)
- `thread_selection_strategy: Strategy` (latest, all, best-performing)
- Returns: GoalContext object containing execution memory + thread ecosystem
_Novelty_: Context construction as explicit API operation with configurable strategies - context is assembled based on policy, not just retrieved based on query

**[Category #20]**: Goal Similarity Threading Algorithm
_Concept_: Thread relationship determined by goal similarity metrics:
- Exact match: Same goal_id, multiple execution threads
- Semantic similarity: Goals with similar intent/pattern (detected by embedding)
- Dependency relationship: Goals in same DAG path
- Thread clustering by goal relationship strength
_Novelty_: Thread relationship fundamentally based on goal similarity hierarchy (exact > semantic > dependency) - goal-centric thread clustering

**[Category #21]**: GoalEngine Ownership Principle
_Concept_: GoalEngine maintains GoalSubDAGStatus structure, AgentLoop gets it from GoalEngine through API/query. GoalEngine owns the goal execution state, AgentLoop has read access for consciousness construction. Clear ownership boundary: GoalEngine = status owner/writer, AgentLoop = status reader.
_Novelty_: GoalEngine as authoritative source for goal execution state - AgentLoop consciousness builds on GoalEngine state, doesn't maintain separate goal state

**[Category #22]**: Configurable Context Construction Strategy
_Concept_: Context construction strategies are configurable (not hardcoded) and dynamically used by AgentLoop based on situation. Configuration-driven strategy selection allows adaptation without code changes. AgentLoop reads configuration to determine which strategy to apply.
_Novelty_: Strategy as configuration dimension - reveals context construction as policy-driven operation, not algorithm-driven

**[Category #23]**: Embedding-Based Goal Similarity
_Concept_: Goal semantic similarity computed using embeddings (for now) - embedding distance determines goal similarity for thread relationship and context construction. Embeddings as fundamental similarity mechanism.
_Novelty_: Embeddings as architectural primitive - similarity computation isn't LLM reasoning, it's embedding math, different computational paradigm

**[Category #24]**: AgentLoop Control Flow Hierarchy
_Concept_: AgentLoop is central coordinator in control flow hierarchy: AgentLoop calls GoalEngine (synchronous pull), AgentLoop coordinates CoreAgent threads. GoalEngine does NOT talk to CoreAgent directly - AgentLoop mediates all component interactions. Hierarchical control flow: AgentLoop at center, GoalEngine and CoreAgent as satellites.
_Novelty_: Reveals AgentLoop as integration mediator (not just consciousness) - all inter-component communication flows through AgentLoop, establishing it as architectural hub

**[Category #25]**: Durability Architecture Requirement
_Concept_: Long-running autonomous agents require durability mechanism for consciousness persistence - execution history must survive system restarts. Durability is non-negotiable requirement for 24/7 autonomous operation. Fundamental architectural dimension alongside consciousness.
_Novelty_: Durability elevated to first-class architectural requirement - consciousness isn't just unified knowledge, it's durable unified knowledge that persists across system lifecycle

**[Category #26]**: Dual Persistence Architecture
_Concept_: Durability has dual persistence architecture: (1) AgentLoop persistence layer records AgentLoop execution + Goal status, (2) CoreAgent checkpoints managed separately by langchain checkpointer. Two separate persistence systems with clear ownership boundary - AgentLoop doesn't manage CoreAgent persistence, langchain does.
_Novelty_: Separates persistence concerns - AgentLoop and CoreAgent have independent durability mechanisms, reveals langchain checkpointer as architectural component

**[Category #27]**: AgentLoop Thread Coordination Responsibilities
_Concept_: AgentLoop thread coordination has three fundamental responsibilities: (1) Assign threads to specific subgoals, (2) Monitor thread execution, (3) Monitor thread status. Coordination is active management (not passive observation), includes assignment, monitoring, and status tracking.
_Novelty_: Coordination as active thread lifecycle management - AgentLoop is thread manager (not just thread observer), assigning and monitoring are explicit responsibilities

**[Category #28]**: Consciousness-Based Coordination Submodule Architecture
_Concept_: AgentLoop has clear submodule separation: Coordination submodule and Consciousness submodule are separate implementations. Coordination fundamentally based on consciousness - consciousness provides knowledge foundation, coordination makes decisions using consciousness data. Architectural separation with dependency relationship.
_Novelty_: Submodule architecture with dependency - coordination submodule queries consciousness submodule, reveals consciousness as foundational layer that coordination builds upon

**[Category #29]**: Knowledge-Based Thread Assignment Principle
_Concept_: Thread assignment based on thread execution topic (knowledge) - subgoal assigned to thread that has relevant knowledge/expertise for the topic. Knowledge-matching assignment (not performance-based or complexity-based). Thread capabilities determined by knowledge domain.
_Novelty_: Topic/knowledge as primary assignment dimension - reveals thread specialization architecture where threads have knowledge domains

**[Category #30]**: Event-Driven Thread Monitoring Architecture
_Concept_: CoreAgent threads emit execution events, Coordination submodule subscribes to events for monitoring - event-driven observation pattern. Threads push events (progress, status), Coordination receives events passively.
_Novelty_: Event-driven monitoring confirmed as architectural pattern (not polling) - threads actively emit, Coordination passively receives

**[Category #31]**: Dual Trigger Synchronization Mechanism
_Concept_: AgentLoop-GoalEngine synchronization triggered by: (1) Thread completion events (when thread finishes, AgentLoop calls GoalEngine for status update), (2) Coordination needs goal information for thread assignment (need-based pull). Dual trigger: event-driven + need-based.
_Novelty_: Hybrid trigger mechanism - not purely event-driven or purely polling, but combination of reactive (event) and proactive (need) synchronization

**User Creative Strengths:** Distinguishing fundamental architecture from implementation decisions, clear component ownership definition, precise submodule boundary specification

**Energy Level:** High engagement, precise architectural thinking, rapid fundamental truth identification

**Overall Creative Journey:** Systematic stripping of assumptions revealed 31 fundamental architectural truths. User demonstrated exceptional ability to identify non-negotiable requirements vs optional techniques, distinguish ownership boundaries, and define clear architectural layers. First Principles Thinking successfully established bedrock for unified architecture.

### Morphological Analysis (Partial Exploration)

**Interactive Focus:** Systematically exploring architectural dimension combinations to discover novel unified models

**Key Breakthroughs:**

**[Category #32]**: Decomposition Manageability-Naturalness Trade-off
_Concept_: Hierarchical DAG decomposition offers easy management (clear structure, predictable evolution) while fluid goal emergence aligns with natural problem-solving (goals evolve organically as execution unfolds). Architectural tension: structured manageability vs natural problem-solving alignment.
_Novelty_: Reveals design philosophy choice - favor engineering control (DAG) or favor problem-solving authenticity (fluid emergence)

**[Category #33]**: Problem-Adaptive Decomposition Strategy (Hypothesis)
_Concept_: GoalEngine analyzes problem type at start and selects decomposition strategy: Well-defined problems → Hierarchical DAG (manageability), Ill-defined problems → Fluid emergence (naturalness), Mixed problems → Hybrid crystallizing DAG. Decomposition strategy itself is adaptive based on problem ontology.
_Novelty_: Meta-adaptive decomposition - GoalEngine doesn't just decompose goals, it decides HOW to decompose based on problem nature

**[Category #34]**: Emergent DAG Crystallization (Hypothesis)
_Concept_: Goals start as fluid hypothesis network, but execution evidence causes structure to crystallize incrementally. Early execution: fluid emergence. Later execution: crystallized DAG emerges from evidence patterns. Natural fluidity transitions to manageable structure through execution.
_Novelty_: Temporal evolution of decomposition strategy - fluid-to-structured transition solves manageability-naturalness trade-off

**Partial Technique Completion:** Identified critical design tension (manageability vs naturalness) and proposed hybrid solutions (problem-adaptive, emergent crystallization). Systematic parameter exploration initiated but not completed across all dimensions.

**User Creative Strengths:** Identifying core architectural tensions, proposing hybrid solutions that reconcile trade-offs, grounding theoretical concepts in practical problem characteristics

**Energy Level:** Focused on core architectural philosophy, efficient identification of key design dimensions

### Cross-Pollination (Partial Exploration)

**Interactive Focus:** Transferring successful patterns from other domains to discover novel integration mechanisms and architectural patterns not found in current agent frameworks

**Domain Connection Initiated:** Kubernetes comparison for AgentLoop consciousness + coordination dual role - identifying architectural patterns from cluster orchestration systems

**Partial Technique Completion:** Cross-domain pattern exploration initiated but not completed. Framework established for extracting architectural principles from distributed systems, operating systems, biological systems, and game AI domains.

**Energy Level:** Efficient transition to synthesis phase, preference for emergent integration approach

### Emergent Thinking - Architecture Refinement Proposal

**Interactive Focus:** Refining existing RFC architecture based on brainstorming discoveries while maintaining architectural alignment

**Key Breakthrough: Architecture Grounded in RFC Reality**

After reading RFC-000, RFC-001, RFC-200, RFC-201, RFC-202, RFC-203, RFC-609, discovered existing architecture already implements most brainstorming goals through:

1. **AgentLoop = Layer 2 Plan → Execute Loop** (NOT consciousness + coordinator)
   - RFC-201: AgentLoop runs Plan → Execute iterations for single goals
   - AgentLoop.executor coordinates CoreAgent threads via Layer 1 integration
   - Not the "consciousness" concept from brainstorming

2. **GoalEngine = Layer 3 Goal Lifecycle Manager** (already maintains goal status)
   - RFC-200: GoalEngine owns Goal DAG and status
   - GoalEngine.ready_goals() returns dependency-satisfied goals
   - GoalDirective enables dynamic goal restructuring (backoff equivalent)

3. **ContextProtocol = "Consciousness" Equivalent** (unbounded knowledge accumulator)
   - RFC-001: ContextProtocol is unbounded, append-only knowledge ledger
   - Persists across threads via DurabilityProtocol
   - Projects bounded views for LLM (matches brainstorming "consciousness" concept)

4. **GoalContextManager = Goal Context Integration** (RFC-609 NEW)
   - get_plan_context(): Previous goal summaries for Plan phase
   - get_execute_briefing(): Goal briefing on thread switch
   - Already implements goal context injection brainstormed

**Refinement Proposals Based on Brainstorming + RFC Reality:**

**[Proposal #1]**: Enhance GoalEngine Backoff with LLM-Driven Reasoning

RFC-200 has GoalDirective for restructuring, but lacks explicit "backoff" reasoning. Add:

```python
class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for GoalEngine (per brainstorming Category #8, #16)."""
    
    async def reason_backoff(self, goal_id: str, goal_context: GoalContext) -> BackoffDecision:
        """
        LLM analyzes full goal context (all goals + dependencies + evidence)
        and decides WHERE to backoff in goal DAG.
        
        Returns:
            BackoffDecision(backoff_to: str, reason: str, new_directives: list[GoalDirective])
        """
```

Integration: GoalEngine calls BackoffReasoner when goal fails (replaces hardcoded retry logic).

**[Proposal #2]**: Extend ContextProtocol with Retrieval Module

RFC-001 ContextProtocol has ingest/project, but lacks brainstorming's "self-contained retrieval module with stable API" (Category #13, #15, #16). Add:

```python
class ContextRetrievalModule:
    """Self-contained retrieval module for ContextProtocol (per brainstorming Category #13-16)."""
    
    def retrieve_by_goal_relevance(self, goal_id: str, execution_context: dict, limit: int) -> list[ContextEntry]:
        """
        Goal-centric retrieval (not query-centric).
        Stable API enables algorithm evolution.
        """
```

Integration: ContextProtocol delegates retrieval to RetrievalModule, preserving ingest/project interface.

**[Proposal #3]**: Extend GoalContextManager with Thread Relationship Module

RFC-609 GoalContextManager exists, but brainstorming identified need for thread relationship module (Category #20, #23). Add:

```python
class ThreadRelationshipModule:
    """Thread relationship analysis for goal context (per brainstorming Category #20)."""
    
    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """
        Goal similarity for thread clustering:
        - Exact match: same goal_id
        - Semantic: embedding similarity
        - Dependency: same DAG path
        """
    
    def construct_goal_context(self, goal_id: str, options: ContextConstructionOptions) -> GoalContext:
        """
        Context construction module (per brainstorming Category #17, #19).
        Handles: same goal multiple threads, similar goals.
        """
```

Integration: GoalContextManager uses ThreadRelationshipModule for context construction.

**[Proposal #4]**: Dual Persistence Architecture Confirmed

RFC-001 + RFC-202 already implement brainstorming's dual persistence (Category #26):
- AgentLoop: DurabilityProtocol + ContextProtocol persistence
- CoreAgent: langchain checkpointer (RFC-100)

**NO CHANGE NEEDED** - Architecture already matches brainstorming discovery.

**[Proposal #5]**: Direct Task Provisioning Alternative to Middleware

RFC-201 Executor uses config injection for CoreAgent (execution hints). Brainstorming identified "direct provisioning" as alternative (Category #9, #12). Refine:

```python
# executor.py current approach (config injection)
config = {
    "configurable": {
        "thread_id": tid,
        "soothe_step_tools": step.tools,  # Middleware injection pattern
        "soothe_step_subagent": step.subagent,
        "soothe_step_expected_output": step.expected_output,
    }
}

# Brainstorming proposal: Direct task packaging (alternative)
task_package = TaskPackage(
    goal_context=goal_context_manager.get_execute_briefing(),
    execution_history=retrieval_module.retrieve_by_goal_relevance(goal_id),
    backoff_evidence=goal_engine.get_backoff_evidence(goal_id),
    step=step,
)
# Direct send to CoreAgent without middleware
```

**Decision**: Keep current config injection (it's working, matches RFC-201), but add GoalContextManager integration (RFC-609 implements brainstorming's goal context injection).

**[Proposal #6]**: AgentLoop Submodule Architecture Clarification

Brainstorming proposed Consciousness + Coordination submodules (Category #28). RFC reality:
- AgentLoop is Layer 2 loop runner (Plan → Execute)
- ContextProtocol is "consciousness" (knowledge ledger)
- Executor handles coordination (thread management)

**Refinement**: Don't split AgentLoop into submodules. AgentLoop stays as loop runner. Consciousness = ContextProtocol (separate protocol). Coordination = Executor (component of AgentLoop).

**Architectural Principle**: Keep protocols separate (ContextProtocol as protocol), AgentLoop as Layer 2 runner, don't merge consciousness into AgentLoop.

**Overall Creative Journey:** Brainstorming generated 35 categories of architectural insights. Reading RFCs revealed existing architecture already implements most concepts through different naming/composition. Refinement proposals enhance existing RFCs rather than replacing architecture. Key insight: ContextProtocol is the "consciousness", GoalEngine is goal manager with backoff enhancement, AgentLoop is Layer 2 executor, GoalContextManager (RFC-609) is the goal context integration mechanism.

**Next Action**: Document refinement proposals in implementation guide format for RFC enhancement.