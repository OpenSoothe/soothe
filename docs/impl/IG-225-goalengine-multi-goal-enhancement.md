# GoalEngine Multi-Goal Enhancement Implementation Architecture

> Implementation guide for multi-goal support and complex goal integration in Soothe.
>
> **Crate/Module**: `packages/soothe/src/soothe/cognition/goal_engine/`
> **Source**: Derived from RFC-200 (§14-22, §205-541), RFC-609 (§95-172)
> **Related RFCs**: RFC-201, RFC-204, RFC-001
> **Language**: Python 3.11+
> **Framework**: LangChain + Pydantic

---

## 1. Overview

This implementation guide specifies the enhancement of GoalEngine (Layer 3) to support multi-goal management and complex goal integration through structured evidence flow, LLM-driven backoff reasoning, and goal similarity-based context construction.

### 1.1 Purpose

This document provides concrete implementation architecture for three critical missing components identified in the RFC-200 and RFC-609 gap analysis:

1. **EvidenceBundle Contract** - Canonical evidence structure for Layer 2 → Layer 3 integration
2. **GoalBackoffReasoner** - LLM-driven goal DAG restructuring on failure
3. **ThreadRelationshipModule** - Goal similarity computation and thread ecosystem analysis

These components enable:
- Structured evidence flow between AgentLoop (Layer 2) and GoalEngine (Layer 3)
- Intelligent failure recovery with reasoning-based backoff decisions
- Multi-goal context sharing through similarity-based thread selection
- Dependency-driven context injection during Plan phase

### 1.2 Scope

**In Scope**:
- EvidenceBundle, BackoffDecision, GoalSubDAGStatus model definitions
- GoalBackoffReasoner implementation with LLM reasoning
- ThreadRelationshipModule with goal similarity hierarchy
- GoalEngine.fail_goal signature update to receive EvidenceBundle
- AgentLoop executor EvidenceBundle construction
- Goal similarity embedding integration
- Backoff reasoning prompt template

**Out of Scope**:
- Multi-goal scheduling strategy (round-robin, load balancing)
- Goal decomposition reasoning (automatic goal splitting)
- Thread ecosystem full analysis (cross-goal pattern recognition)
- Goal execution success prediction

### 1.3 Spec Compliance

This implementation guide **supersedes** RFC-200 and RFC-609 specifications with concrete implementation details but **MUST NOT contradict** them. All invariants and requirements from source RFCs are preserved.

**Key RFC Requirements**:
- RFC-200 §14-22: EvidenceBundle canonical structure MUST be used for Layer 2 → Layer 3 handoff
- RFC-200 §205-541: GoalBackoffReasoner MUST use LLM for backoff reasoning, not hardcoded retry logic
- RFC-609 §95-172: ThreadRelationshipModule MUST implement goal similarity hierarchy (exact > semantic > dependency)
- RFC-201 §419-463: AgentLoop MUST construct EvidenceBundle from execution context

---

## 2. Architectural Position

### 2.1 System Context

GoalEngine multi-goal enhancement sits at Layer 3 of Soothe's three-layer execution model, providing goal lifecycle management services for AgentLoop (Layer 2) queries.

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Autonomous Goal Management (GoalEngine)            │
│                                                              │
│  ├─ GoalBackoffReasoner (NEW)                                │
│  │   • LLM-driven backoff reasoning                          │
│  │   • BackoffDecision model                                 │
│  │   • EvidenceBundle analysis                               │
│  │                                                            │
│  ├─ ThreadRelationshipModule (NEW)                           │
│  │   • Goal similarity computation                           │
│  │   • Embedding integration                                 │
│  │   • Thread selection strategies                           │
│  │                                                            │
│  └─ GoalEngine (Enhanced)                                    │
│      • fail_goal receives EvidenceBundle                     │
│      • Dependency-driven context construction                │
│      • GoalSubDAGStatus tracking                             │
└─────────────────────────────────────────────────────────────┘
                          ↓ Pull Architecture
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: AgentLoop (Enhanced)                                │
│                                                              │
│  • Executor constructs EvidenceBundle                        │
│  • Reports EvidenceBundle to GoalEngine.fail_goal           │
│  • Uses ThreadRelationshipModule for context                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: CoreAgent Runtime                                   │
│                                                              │
│  • Tool execution                                            │
│  • Subagent invocation                                       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Dependency Graph

```
goal_engine/
├── engine.py
│   └── depends on: backoff_reasoner.py, thread_relationship.py
│
├── schemas.py (NEW)
│   ├── EvidenceBundle
│   ├── BackoffDecision
│   ├── GoalSubDAGStatus
│   └── ContextConstructionOptions
│
├── backoff_reasoner.py (NEW)
│   ├── GoalBackoffReasoner class
│   ├── LLM reasoning implementation
│   └── Prompt templates
│
├── thread_relationship.py (NEW)
│   ├── ThreadRelationshipModule class
│   ├── Goal similarity computation
│   └── Embedding integration
│
└── goal_context_manager.py (Enhanced)
      └── Uses ThreadRelationshipModule
```

### 2.3 Module Responsibilities

| Module | Responsibility | Dependencies |
|--------|----------------|--------------|
| `schemas.py` | EvidenceBundle, BackoffDecision, GoalSubDAGStatus definitions | Pydantic |
| `backoff_reasoner.py` | LLM-driven backoff reasoning for goal DAG restructuring | `schemas.py`, LangChain chat model |
| `thread_relationship.py` | Goal similarity computation and thread selection | `schemas.py`, LangChain embeddings |
| `engine.py` | GoalEngine integration with backoff reasoning | `backoff_reasoner.py`, `schemas.py` |
| `goal_context_manager.py` | Dependency-driven context construction using similarity | `thread_relationship.py` |

### 2.4 Dependency Constraints

**GoalEngine Multi-Goal Enhancement**:
- **MUST** use EvidenceBundle for all Layer 2 → Layer 3 evidence exchange
- **MUST** use LLM-driven reasoning for backoff decisions (no hardcoded retry limits)
- **MUST** implement goal similarity hierarchy (exact > semantic > dependency)
- **MUST NOT** invoke AgentLoop directly (pull architecture inversion)
- **MAY** cache goal similarity scores for performance
- **MAY** use embedding batch processing for similarity computation

---

## 3. Module Structure

```
packages/soothe/src/soothe/cognition/goal_engine/
├── __init__.py
├── engine.py                # GoalEngine (enhanced)
├── schemas.py               # Goal, GoalDirective (existing)
│   └── NEW: EvidenceBundle, BackoffDecision, GoalSubDAGStatus
│   └── NEW: ContextConstructionOptions
├── backoff_reasoner.py      # NEW: GoalBackoffReasoner
├── thread_relationship.py   # NEW: ThreadRelationshipModule
├── goal_context_manager.py  # Enhanced to use thread_relationship
├── writer.py                # Goal file writer
└── events.py                # Goal events
```

---

## 4. Core Types

### 4.1 EvidenceBundle (Canonical)

Canonical evidence payload exchanged across Layer 2 and Layer 3, replacing simple error strings.

```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class EvidenceBundle(BaseModel):
    """Canonical evidence payload exchanged across Layer 2 and Layer 3.
    
    RFC-200 §14-22: This is the authoritative schema for evidence exchange.
    Layer 2 AgentLoop MUST construct this structure from execution context.
    Layer 3 GoalEngine MUST receive this in fail_goal() signature.
    """
    
    structured: dict[str, Any] = Field(
        description="Machine-readable execution metrics/state for deterministic processing"
    )
    """Example: {"wave_count": 3, "step_count": 12, "subagent_calls": 5, "error_count": 2}"""
    
    narrative: str = Field(
        description="Natural language synthesis for LLM reasoning and operator visibility"
    )
    """Example: 'Goal execution failed after 3 waves with persistent authentication errors...'"""
    
    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"] = Field(
        description="Evidence producer stage"
    )
    """Identifies where evidence was generated"""
    
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Evidence emission time"
    )
    """Auto-generated unless overridden"""
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| `structured` | `dict[str, Any]` | Machine-readable metrics (wave/step counts, tool failures, iteration metrics) |
| `narrative` | `str` | Human-readable synthesis extracted from PlanResult.evidence_summary |
| `source` | `Literal` | Stage identifier (layer2_execute, layer2_plan, layer3_reflect) |
| `timestamp` | `datetime` | Evidence generation time for temporal ordering |

### 4.2 BackoffDecision

LLM-driven decision for goal DAG restructuring after failure.

```python
from typing import list
from .schemas import GoalDirective

class BackoffDecision(BaseModel):
    """LLM-driven backoff decision for goal DAG restructuring.
    
    RFC-200 §205-541: GoalBackoffReasoner output structure.
    Determines WHERE to backoff in goal DAG and what directives to apply.
    """
    
    backoff_to_goal_id: str = Field(
        description="Target goal to backoff to (where to resume in DAG)"
    )
    """Valid goal ID from current GoalDAG"""
    
    reason: str = Field(
        description="Natural language reasoning for backoff decision"
    )
    """LLM-generated reasoning explaining why this backoff point was chosen"""
    
    new_directives: list[GoalDirective] = Field(
        default_factory=list,
        description="Additional directives to apply after backoff"
    )
    """GoalDirective actions to restructure DAG (create goals, adjust priorities, add dependencies)"""
    
    evidence_summary: str = Field(
        description="Summary of why current goal path failed"
    )
    """Condensed failure analysis for GoalEngine tracking"""
```

### 4.3 GoalSubDAGStatus

Canonical DAG execution status for backoff and reflection tracking.

```python
class GoalSubDAGStatus(BaseModel):
    """Canonical DAG execution status for backoff and reflection.
    
    RFC-200 §14-22: Tracks goal execution states and backoff boundaries.
    Used by GoalEngine for DAG state management.
    """
    
    execution_states: dict[str, Literal["pending", "running", "success", "failed", "backoff_pending"]] = Field(
        description="Per-goal execution state"
    )
    """Map of goal_id to execution status"""
    
    backoff_points: list[str] = Field(
        default_factory=list,
        description="Goal IDs selected as backoff boundaries"
    )
    """Goals that have been backoff targets"""
    
    evidence_annotations: dict[str, EvidenceBundle] = Field(
        default_factory=dict,
        description="Per-goal evidence mapping"
    )
    """EvidenceBundle associated with each goal execution"""
```

### 4.4 ContextConstructionOptions

Configuration for goal context construction with thread relationship analysis.

```python
class ContextConstructionOptions(BaseModel):
    """Options for goal context construction.
    
    RFC-609 §95-172: Thread selection and similarity filtering configuration.
    Used by ThreadRelationshipModule and GoalContextManager.
    """
    
    include_same_goal_threads: bool = Field(
        default=True,
        description="Include multiple threads for same goal_id"
    )
    """When True, retrieves all execution threads for current goal"""
    
    include_similar_goals: bool = Field(
        default=True,
        description="Include threads with semantically similar goals"
    )
    """When True, uses embedding similarity to find related goal threads"""
    
    thread_selection_strategy: Literal["latest", "all", "best_performing"] = Field(
        default="latest",
        description="Strategy for selecting relevant threads"
    )
    """latest: most recent thread; all: all matching threads; best_performing: highest success rate"""
    
    similarity_threshold: float = Field(
        default=0.7,
        description="Embedding similarity threshold for goal matching",
        ge=0.0,
        le=1.0
    )
    """Minimum similarity score for thread inclusion"""
```

---

## 5. Key Interfaces

### 5.1 GoalBackoffReasoner

LLM-driven backoff reasoning for goal DAG restructuring on failure.

```python
from langchain_core.language_models import BaseChatModel
from ..config import SootheConfig
from .schemas import GoalContext, BackoffDecision, EvidenceBundle

class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for goal DAG restructuring.
    
    RFC-200 §205-541: Analyzes goal context and evidence to decide
    WHERE to backoff in the goal DAG. Replaces hardcoded retry logic.
    """
    
    def __init__(self, config: SootheConfig) -> None:
        """Initialize reasoner with chat model from config.
        
        Args:
            config: SootheConfig with model provider settings
        """
        self._model: BaseChatModel = config.create_chat_model("reason")
        self._prompt_template: str = BACKOFF_REASONING_PROMPT
    
    async def reason_backoff(
        self,
        goal_id: str,
        goal_context: GoalContext,
        failed_evidence: EvidenceBundle,
    ) -> BackoffDecision:
        """LLM analyzes full goal context and decides WHERE to backoff.
        
        Args:
            goal_id: Failed goal identifier
            goal_context: Snapshot of all goals (RFC-200 GoalContext)
            failed_evidence: Evidence from Layer 2 execution
            
        Returns:
            BackoffDecision with backoff target goal ID, reasoning, and directives
            
        Process:
        1. Construct LLM prompt with goal DAG state, failure evidence, dependency context
        2. Invoke chat model with structured reasoning prompt
        3. Parse LLM response into BackoffDecision model
        4. Validate backoff target exists in DAG
        5. Return decision for GoalEngine application
        
        Raises:
            ValueError: If backoff target not in goal DAG
            LLMError: If model invocation fails
        """
```

**Method Descriptions**:

| Method | Description |
|--------|-------------|
| `__init__` | Initialize with chat model from SootheConfig ("reason" role) |
| `reason_backoff` | Analyze goal context + evidence, return BackoffDecision |

### 5.2 ThreadRelationshipModule

Thread relationship analysis for goal context construction with similarity computation.

```python
from langchain_core.embeddings import Embeddings
from .schemas import Goal, ContextConstructionOptions

class ThreadRelationshipModule:
    """Thread relationship analysis for goal context construction.
    
    RFC-609 §95-172: Computes goal similarity and constructs context
    with thread ecosystem awareness using embedding integration.
    """
    
    def __init__(self, embedding_model: Embeddings) -> None:
        """Initialize with embedding model for similarity computation.
        
        Args:
            embedding_model: LangChain Embeddings implementation
        """
        self._embedding_model: Embeddings = embedding_model
        # Cache for goal embeddings (optional performance optimization)
        self._embedding_cache: dict[str, list[float]] = {}
    
    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """Goal similarity for thread clustering.
        
        Hierarchy (exact > semantic > dependency):
        - Level 1: Exact match (same goal_id) → 1.0
        - Level 2: Semantic similarity (embedding distance) → 0.0-0.99
        - Level 3: Dependency relationship (same DAG path) → 0.0-0.8
        
        Args:
            goal_a: First goal
            goal_b: Second goal
            
        Returns:
            Similarity score in range [0.0, 1.0]
            
        Process:
        1. Check exact match (goal_a.id == goal_b.id) → return 1.0
        2. Check embedding cache for both goals
        3. Compute embeddings if not cached
        4. Calculate cosine similarity
        5. Check dependency relationship (optional: if both in same DAG path)
        6. Return highest similarity level
        """
    
    async def select_threads(
        self,
        current_goal: Goal,
        all_threads: list[ThreadRecord],
        options: ContextConstructionOptions,
    ) -> list[ThreadRecord]:
        """Select relevant threads based on goal similarity and strategy.
        
        Args:
            current_goal: Goal being executed
            all_threads: Available thread records from persistence
            options: Context construction options
            
        Returns:
            Filtered thread list based on similarity and strategy
            
        Process:
        1. Filter threads by same_goal_id if include_same_goal_threads=True
        2. Compute similarity for each thread's goal
        3. Filter by similarity_threshold if include_similar_goals=True
        4. Apply thread_selection_strategy (latest/all/best_performing)
        5. Return selected threads
        """
```

**Method Descriptions**:

| Method | Description |
|--------|-------------|
| `__init__` | Initialize with LangChain Embeddings model |
| `compute_similarity` | Compute goal similarity using hierarchy (exact > semantic > dependency) |
| `select_threads` | Select relevant threads based on similarity and strategy |

---

## 6. Implementation Details

### 6.1 GoalBackoffReasoner Implementation

LLM-driven backoff reasoning process for goal DAG restructuring.

**Process**:
1. **Prompt Construction**: Build structured prompt with goal DAG state, failure evidence, dependency context
2. **LLM Invocation**: Call chat model with reasoning prompt
3. **Response Parsing**: Extract BackoffDecision from LLM structured output
4. **Validation**: Check backoff target goal exists in current DAG
5. **Decision Return**: Return BackoffDecision for GoalEngine application

**Prompt Template Structure**:

```python
BACKOFF_REASONING_PROMPT = """
Analyze goal execution failure and determine optimal backoff point in goal DAG.

## Current Goal Context

Failed Goal: {goal_id}
Goal Description: {goal_description}

Goal DAG State:
{goal_dag_state}

Dependency Chain:
{dependency_chain}

## Failure Evidence

Evidence Type: {evidence_source}
Execution Metrics: {structured_metrics}
Narrative Summary: {failure_narrative}

## Decision Required

You must decide WHERE to backoff in the goal DAG. Consider:
1. Root cause analysis: Is the failure isolated to current goal or systemic?
2. Dependency validity: Are prerequisite goals still valid?
3. Recovery strategy: Should we retry current goal, backoff to parent, or create new goals?

Output JSON structure:
{
  "backoff_to_goal_id": "<goal_id>",
  "reason": "<natural language reasoning>",
  "new_directives": [],
  "evidence_summary": "<condensed failure analysis>"
}

Constraints:
- backoff_to_goal_id MUST exist in current goal DAG
- Prefer backing off to parent goal if dependency assumption failed
- Use new_directives to create corrective goals if needed
"""
```

**Diagram**:

```
EvidenceBundle from Layer 2
        ↓
GoalBackoffReasoner.reason_backoff()
        ↓
    LLM Analysis
    ├─ Root cause analysis
    ├─ Dependency validation
    ├─ Recovery strategy selection
    ↓
BackoffDecision
    ├─ backoff_to_goal_id
    ├─ reason (LLM reasoning)
    ├─ new_directives
    ↓
GoalEngine.apply_backoff_decision()
    ├─ Reset backoff target to "pending"
    ├─ Apply new_directives
    ├─ Update GoalSubDAGStatus
```

### 6.2 ThreadRelationshipModule Implementation

Goal similarity computation and thread selection process.

**Process**:
1. **Exact Match Check**: If goal IDs match, return 1.0 similarity
2. **Embedding Computation**: Compute embeddings for goal descriptions
3. **Cosine Similarity**: Calculate semantic similarity score
4. **Dependency Check**: Check if goals share DAG path (optional Level 3)
5. **Thread Selection**: Apply strategy (latest/all/best_performing)

**Similarity Hierarchy Implementation**:

```python
def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
    # Level 1: Exact match
    if goal_a.id == goal_b.id:
        return 1.0
    
    # Level 2: Semantic similarity
    emb_a = self._get_or_compute_embedding(goal_a.description)
    emb_b = self._get_or_compute_embedding(goal_b.description)
    
    semantic_sim = self._cosine_similarity(emb_a, emb_b)
    
    # Level 3: Dependency relationship (optional)
    # Check if both goals in same dependency chain
    # dependency_sim = self._check_dependency_relationship(goal_a, goal_b)
    
    # Return highest level (exact already handled)
    return semantic_sim

def _get_or_compute_embedding(self, text: str) -> list[float]:
    """Cache-enabled embedding retrieval."""
    if text in self._embedding_cache:
        return self._embedding_cache[text]
    
    embedding = self._embedding_model.embed_query(text)
    self._embedding_cache[text] = embedding
    return embedding

def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a ** 2 for a in vec_a) ** 0.5
    norm_b = sum(b ** 2 for b in vec_b) ** 0.5
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return dot_product / (norm_a * norm_b)
```

**Thread Selection Strategy Implementation**:

```python
async def select_threads(
    self,
    current_goal: Goal,
    all_threads: list[ThreadRecord],
    options: ContextConstructionOptions,
) -> list[ThreadRecord]:
    """Select threads based on goal similarity and strategy."""
    
    # Filter by same goal ID
    same_goal_threads = [
        t for t in all_threads
        if t.goal_id == current_goal.id
    ]
    
    # Filter by similar goals
    similar_threads = []
    if options.include_similar_goals:
        for thread in all_threads:
            if thread.goal_id == current_goal.id:
                continue  # Already in same_goal_threads
            
            # Get thread's goal from GoalEngine
            thread_goal = goal_engine.get_goal(thread.goal_id)
            if not thread_goal:
                continue
            
            similarity = self.compute_similarity(current_goal, thread_goal)
            if similarity >= options.similarity_threshold:
                similar_threads.append(thread)
    
    # Combine threads
    candidate_threads = same_goal_threads if options.include_same_goal_threads else []
    candidate_threads.extend(similar_threads)
    
    # Apply selection strategy
    if options.thread_selection_strategy == "latest":
        # Return most recent thread
        if candidate_threads:
            return [max(candidate_threads, key=lambda t: t.created_at)]
        return []
    
    elif options.thread_selection_strategy == "all":
        # Return all matching threads
        return candidate_threads
    
    elif options.thread_selection_strategy == "best_performing":
        # Return thread with highest success rate
        if candidate_threads:
            return [max(candidate_threads, key=lambda t: t.success_rate)]
        return []
    
    return []
```

### 6.3 EvidenceBundle Construction in AgentLoop

AgentLoop executor constructs EvidenceBundle from execution context.

**Implementation Location**: `packages/soothe/src/soothe/cognition/agent_loop/executor.py`

**Process**:
1. Extract wave/step metrics from LoopState
2. Extract PlanResult.evidence_summary for narrative
3. Build EvidenceBundle.structured dictionary
4. Set EvidenceBundle.source to "layer2_execute"
5. Pass to GoalEngine.fail_goal()

```python
# In executor.py

from soothe.cognition.goal_engine.schemas import EvidenceBundle

async def handle_execution_failure(
    self,
    state: LoopState,
    plan_result: PlanResult,
    goal_engine: GoalEngine,
) -> None:
    """Handle execution failure with EvidenceBundle construction."""
    
    # Construct EvidenceBundle from execution context
    evidence = EvidenceBundle(
        structured={
            "wave_count": state.wave_count,
            "step_count": state.total_steps,
            "subagent_calls": state.subagent_invocations,
            "tool_calls": state.tool_call_count,
            "error_count": state.error_count,
            "iteration_number": state.current_iteration,
            "last_wave_metrics": state.wave_metrics[-1] if state.wave_metrics else {},
        },
        narrative=plan_result.evidence_summary,
        source="layer2_execute",
        timestamp=datetime.now(),
    )
    
    # Pass EvidenceBundle to GoalEngine (NEW signature)
    backoff_decision = await goal_engine.fail_goal(
        goal_id=state.current_goal_id,
        evidence=evidence,  # NEW: EvidenceBundle instead of error string
        allow_retry=True,
    )
    
    if backoff_decision:
        logger.info(f"Backoff decision: {backoff_decision.reason}")
```

---

## 7. Error Handling

### 7.1 Error Types

```python
from pydantic import ValidationError

class BackoffReasoningError(Exception):
    """Error during LLM backoff reasoning."""
    
    def __init__(self, message: str, goal_id: str, evidence: EvidenceBundle):
        self.goal_id = goal_id
        self.evidence = evidence
        super().__init__(message)

class InvalidBackoffTargetError(ValueError):
    """Backoff target goal not in current DAG."""
    
    def __init__(self, target_goal_id: str, current_dag: GoalDAG):
        self.target_goal_id = target_goal_id
        self.current_dag = current_dag
        super().__init__(f"Goal {target_goal_id} not found in DAG")

class SimilarityComputationError(Exception):
    """Error during goal similarity computation."""
    
    def __init__(self, message: str, goal_a_id: str, goal_b_id: str):
        self.goal_a_id = goal_a_id
        self.goal_b_id = goal_b_id
        super().__init__(message)
```

### 7.2 Error Handling Strategy

| Error Category | Handling Approach |
|----------------|-------------------|
| **LLM invocation failure** | Retry with exponential backoff (max 3 retries), fallback to parent goal backoff |
| **Backoff target validation** | Raise InvalidBackoffTargetError, GoalEngine handles by selecting root goal |
| **EvidenceBundle parsing** | Raise ValidationError, GoalEngine logs and uses fallback retry logic |
| **Embedding computation** | Cache timeout errors, retry with fresh embedding, fallback to dependency similarity |
| **Thread selection** | Return empty list if no threads match, GoalEngine proceeds without thread context |

---

## 8. Configuration

### 8.1 Configuration Options

Add to `config/config.yml` under `cognition.goal_engine`:

```yaml
cognition:
  goal_engine:
    # Existing settings
    max_retry_count: 3
    goal_discovery_enabled: true
    
    # NEW: Backoff reasoning settings
    backoff_reasoning:
      enabled: true
      model_role: "reason"  # Uses SootheConfig.create_chat_model("reason")
      max_backoff_depth: 5  # Maximum backoff chain depth
      fallback_on_llm_error: true  # Fallback to parent goal on LLM error
    
    # NEW: Goal similarity settings
    thread_relationship:
      enabled: true
      embedding_model_role: "embed"  # Uses SootheConfig.create_embedding_model()
      similarity_threshold: 0.7  # Default threshold
      default_strategy: "latest"  # Default thread selection strategy
      cache_embeddings: true  # Enable embedding caching
      cache_ttl_seconds: 3600  # Embedding cache TTL
```

### 8.2 Defaults

| Option | Default | Description |
|--------|---------|-------------|
| `backoff_reasoning.enabled` | `true` | Enable LLM-driven backoff reasoning |
| `backoff_reasoning.model_role` | `"reason"` | Chat model role for reasoning |
| `backoff_reasoning.max_backoff_depth` | `5` | Maximum backoff chain depth |
| `backoff_reasoning.fallback_on_llm_error` | `true` | Fallback to parent goal on LLM error |
| `thread_relationship.enabled` | `true` | Enable goal similarity computation |
| `thread_relationship.embedding_model_role` | `"embed"` | Embedding model role |
| `thread_relationship.similarity_threshold` | `0.7` | Default similarity threshold |
| `thread_relationship.default_strategy` | `"latest"` | Default thread selection strategy |
| `thread_relationship.cache_embeddings` | `true` | Enable embedding caching |
| `thread_relationship.cache_ttl_seconds` | `3600` | Embedding cache TTL (1 hour) |

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| `EvidenceBundle` | Validation, field types, serialization, timestamp defaults |
| `BackoffDecision` | Validation, directive parsing, goal ID validation |
| `GoalBackoffReasoner.reason_backoff` | LLM prompt construction, response parsing, backoff target validation |
| `ThreadRelationshipModule.compute_similarity` | Exact match, semantic similarity, embedding caching, cosine calculation |
| `ThreadRelationshipModule.select_threads` | Thread filtering, strategy application, threshold filtering |
| `GoalEngine.fail_goal` | EvidenceBundle handling, backoff application, DAG restructuring |

### 9.2 Integration Tests

**EvidenceBundle Flow Integration**:
- AgentLoop executor constructs EvidenceBundle
- GoalEngine.fail_goal receives EvidenceBundle
- GoalBackoffReasoner analyzes EvidenceBundle
- BackoffDecision applied to GoalDAG

**Goal Similarity Integration**:
- ThreadRelationshipModule computes similarity
- GoalContextManager uses similarity for thread selection
- Context injection includes similar goal threads
- Plan phase receives dependency-driven context

**Multi-Goal DAG Integration**:
- Multiple concurrent goals with dependencies
- Goal failure triggers backoff reasoning
- Backoff restructuring affects dependent goals
- GoalSubDAGStatus tracking across multiple goals

### 9.3 Test Utilities

```python
# tests/cognition/goal_engine/test_backoff_reasoner.py

from unittest.mock import AsyncMock, MagicMock
from soothe.cognition.goal_engine.schemas import EvidenceBundle, GoalContext
from soothe.cognition.goal_engine.backoff_reasoner import GoalBackoffReasoner

def create_mock_evidence_bundle() -> EvidenceBundle:
    """Create test EvidenceBundle."""
    return EvidenceBundle(
        structured={"wave_count": 3, "step_count": 12, "error_count": 2},
        narrative="Goal execution failed after 3 waves with authentication errors",
        source="layer2_execute",
    )

def create_mock_goal_context() -> GoalContext:
    """Create test GoalContext with mock DAG."""
    # Implementation...
    pass

async def test_backoff_reasoner_llm_invocation():
    """Test LLM invocation and response parsing."""
    config = create_mock_config()
    reasoner = GoalBackoffReasoner(config)
    
    # Mock chat model
    reasoner._model = AsyncMock()
    reasoner._model.ainvoke.return_value = MagicMock(
        content=json.dumps({
            "backoff_to_goal_id": "goal_001",
            "reason": "Authentication failure suggests dependency goal needs re-execution",
            "new_directives": [],
            "evidence_summary": "Auth dependency failed"
        })
    )
    
    evidence = create_mock_evidence_bundle()
    goal_context = create_mock_goal_context()
    
    decision = await reasoner.reason_backoff("goal_002", goal_context, evidence)
    
    assert decision.backoff_to_goal_id == "goal_001"
    assert "Authentication" in decision.reason
```

Gate test-only code behind feature flags (not needed for this module, tests use mock fixtures).

---

## 10. Migration / Compatibility

### 10.1 Breaking Changes

**GoalEngine.fail_goal Signature Change**:

```python
# OLD signature (current implementation)
async def fail_goal(
    self,
    goal_id: str,
    error: str,  # Simple error string
    allow_retry: bool = True,
) -> None:

# NEW signature (RFC-200 compliant)
async def fail_goal(
    self,
    goal_id: str,
    evidence: EvidenceBundle,  # EvidenceBundle object
    allow_retry: bool = True,
) -> BackoffDecision | None:  # Returns backoff decision
```

**Migration Required**:
- All callers of `GoalEngine.fail_goal` MUST update to pass `EvidenceBundle`
- Return value now includes `BackoffDecision` (was `None`)
- AgentLoop executor MUST construct EvidenceBundle before calling fail_goal

### 10.2 Migration Path

**Phase 1: Add EvidenceBundle Construction**:
1. Update AgentLoop executor to construct EvidenceBundle
2. Create EvidenceBundle from LoopState metrics
3. Extract narrative from PlanResult.evidence_summary

**Phase 2: Update GoalEngine.fail_goal**:
1. Change signature to receive `EvidenceBundle`
2. Implement GoalBackoffReasoner integration
3. Return `BackoffDecision` instead of `None`
4. Add fallback logic for backward compatibility (temporary)

**Phase 3: Remove Backward Compatibility**:
1. Remove fallback error string handling
2. All callers MUST use EvidenceBundle
3. Remove temporary compatibility shims

**Migration Timeline**: Single PR with backward compatibility shim for 1 week, then full migration.

---

## Appendix A: RFC Requirement Mapping

| RFC Requirement | Guide Section | Implementation |
|-----------------|---------------|----------------|
| RFC-200 §14-22 EvidenceBundle canonical structure | Section 4.1 | `schemas.py:EvidenceBundle` |
| RFC-200 §205-541 GoalBackoffReasoner | Section 5.1, 6.1 | `backoff_reasoner.py:GoalBackoffReasoner` |
| RFC-200 §14-22 GoalSubDAGStatus | Section 4.3 | `schemas.py:GoalSubDAGStatus` |
| RFC-200 §14-22 BackoffDecision | Section 4.2 | `schemas.py:BackoffDecision` |
| RFC-201 §419-463 EvidenceBundle handoff | Section 6.3 | `executor.py:handle_execution_failure` |
| RFC-609 §95-172 ThreadRelationshipModule | Section 5.2, 6.2 | `thread_relationship.py:ThreadRelationshipModule` |
| RFC-609 §95-172 Goal similarity hierarchy | Section 6.2 | `compute_similarity` implementation |
| RFC-609 §95-172 ContextConstructionOptions | Section 4.4 | `schemas.py:ContextConstructionOptions` |

---

## Appendix B: Revision History

| Date | RFC Version | Changes |
|------|-------------|---------|
| 2026-04-21 | RFC-200, RFC-609 | Initial implementation guide for multi-goal enhancement |

---

**Next Steps**: After guide approval, proceed to coding phase with:
1. Implement `schemas.py` additions (EvidenceBundle, BackoffDecision, GoalSubDAGStatus)
2. Implement `backoff_reasoner.py` with LLM reasoning
3. Implement `thread_relationship.py` with goal similarity
4. Update `engine.py` fail_goal signature
5. Update AgentLoop executor for EvidenceBundle construction
6. Add unit and integration tests
7. Run `./scripts/verify_finally.sh` before commit