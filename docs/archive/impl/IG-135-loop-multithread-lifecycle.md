# IG-135: AgentLoop Multi-Thread Infinite Lifecycle Implementation

**IG**: 0135
**Title**: Implement AgentLoop multi-thread spanning with automatic thread switching
**RFC**: RFC-608
**Status**: Draft
**Created**: 2026-04-16

## Overview

This guide implements RFC-608: AgentLoop multi-thread infinite lifecycle with automatic thread switching. The implementation extends AgentLoopCheckpoint to span multiple threads, adds extensible thread switching policy with semantic goal-thread relevance analysis, and implements auto /recall knowledge transfer on thread switches.

## Implementation Scope

**Core Changes**:
1. AgentLoopCheckpoint v2.0 schema (loop_id, thread_ids, goal_history across threads)
2. ThreadSwitchPolicy with 5 triggers + goal-thread relevance analysis
3. Automatic thread switching logic (policy evaluation, thread creation, knowledge transfer)
4. Goal-thread relevance LLM analysis (semantic hindering detection)
5. Auto /recall on thread switch (vector search, knowledge injection)
6. Thread health monitoring (metrics collection, policy integration)
7. Cross-thread /recall command

**Files Modified/Created**:
- checkpoint.py (schema changes)
- state_manager.py (thread switch logic)
- thread_switch_policy.py (new)
- goal_thread_relevance.py (new)
- agent_loop.py (multi-thread execution)
- thread_registry.py (create_thread_for_loop)
- query_engine.py (/recall command)

## Phase 1: Schema & State Manager

### Task 1.1: Add New Models to checkpoint.py

**Goal**: Add ThreadHealthMetrics, ThreadSwitchPolicy, GoalThreadRelevanceAnalysis, CustomSwitchTrigger models

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class ThreadHealthMetrics(BaseModel):
    """Current thread health state for switching policy evaluation."""
    
    thread_id: str
    last_updated: datetime
    
    # Message history metrics
    message_count: int = 0
    estimated_tokens: int = 0
    message_history_size_mb: float = 0.0
    
    # Execution health
    consecutive_goal_failures: int = 0
    last_goal_status: Literal["completed", "failed", "cancelled"] | None = None
    
    # Checkpoint health
    checkpoint_errors: int = 0
    last_checkpoint_error: str | None = None
    checkpoint_corruption_detected: bool = False
    
    # Subagent health
    subagent_timeout_count: int = 0
    subagent_crash_count: int = 0
    last_subagent_error: str | None = None
    
    # Extensible custom metrics
    custom_metrics: dict[str, Any] = Field(default_factory=dict)


class CustomSwitchTrigger(BaseModel):
    """Custom thread switching trigger (extensible)."""
    
    trigger_name: str
    trigger_condition: str
    trigger_threshold: float
    trigger_action: Literal["switch_thread", "alert_user", "log_warning"]


class ThreadSwitchPolicy(BaseModel):
    """Extensible policy for automatic thread switching triggers."""
    
    # Quantitative triggers
    message_history_token_threshold: int | None = 100000
    consecutive_goal_failure_threshold: int | None = 3
    checkpoint_error_threshold: int | None = 2
    subagent_timeout_threshold: int | None = 2
    
    # Semantic trigger
    goal_thread_relevance_check_enabled: bool = True
    relevance_analysis_model: str | None = None
    relevance_confidence_threshold: float = 0.7
    
    # Behavior
    auto_switch_enabled: bool = True
    max_thread_switches_per_loop: int | None = None
    knowledge_transfer_limit: int = 10
    
    # Custom triggers
    custom_triggers: list[CustomSwitchTrigger] = Field(default_factory=list)
    
    # Metadata
    policy_name: str = "default"
    policy_version: str = "1.0"


class GoalThreadRelevanceAnalysis(BaseModel):
    """LLM-based analysis of goal-thread relevance."""
    
    thread_summary: str
    next_goal: str
    
    # LLM response
    is_relevant: bool
    hindering_reasons: list[str] = Field(default_factory=list)
    confidence: float
    reasoning: str
    
    # Decision
    should_switch_thread: bool
```

**Verification**: Models validate correctly, import without errors

---

### Task 1.2: Extend AgentLoopCheckpoint Schema

**Goal**: Update AgentLoopCheckpoint for multi-thread spanning (v2.0)

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py

class AgentLoopCheckpoint(BaseModel):
    """Abstract loop checkpoint spanning multiple threads with infinite lifecycle."""
    
    # Identity (NEW)
    loop_id: str  # UUID
    thread_ids: list[str] = Field(default_factory=list)  # All threads
    current_thread_id: str  # Active thread
    
    # Status (MODIFIED)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]
    
    # Goal history (MODIFIED - across all threads)
    goal_history: list[GoalExecutionRecord] = Field(default_factory=list)
    current_goal_index: int = -1  # -1 if no active goal
    
    # Working memory (unchanged)
    working_memory_state: WorkingMemoryState = Field(default_factory=WorkingMemoryState)
    
    # Thread health (NEW)
    thread_health_metrics: ThreadHealthMetrics
    
    # Metrics (MODIFIED)
    total_goals_completed: int = 0
    total_thread_switches: int = 0  # NEW
    total_duration_ms: int = 0
    total_tokens_used: int = 0
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    schema_version: str = "2.0"  # v1.0 was goal-scoped
```

**Changes**:
- Added loop_id, thread_ids, current_thread_id
- Added thread_health_metrics
- Added total_thread_switches
- Status changed to loop-scoped
- Schema version 2.0

**Verification**: Schema loads, validates, existing tests updated

---

### Task 1.3: Update GoalExecutionRecord

**Goal**: Add thread_id field to GoalExecutionRecord

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py

class GoalExecutionRecord(BaseModel):
    """Single goal execution record (on specific thread)."""
    
    # Identity (MODIFIED)
    goal_id: str  # "{loop_id}_goal_{seq}"
    goal_text: str
    thread_id: str  # NEW - which thread executed this goal
    
    # Execution state (unchanged)
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["completed", "failed", "cancelled"] = "completed"
    
    # Execution traces (unchanged)
    reason_history: list[ReasonStepRecord] = Field(default_factory=list)
    act_history: list[ActWaveRecord] = Field(default_factory=list)
    
    # Output (unchanged)
    final_report: str = ""
    evidence_summary: str = ""
    
    # Metrics (unchanged)
    duration_ms: int = 0
    tokens_used: int = 0
    
    # Timestamps (unchanged)
    started_at: datetime
    completed_at: datetime | None = None
```

**Verification**: GoalExecutionRecord includes thread_id, goal_id format validated

---

### Task 1.4: Update state_manager.py - initialize()

**Goal**: Modify initialize() to create loop with loop_id

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/state_manager.py

import uuid
from pathlib import Path

class AgentLoopStateManager:
    def __init__(self, loop_id: str, workspace: Path | None = None):
        """Initialize with loop_id (primary key), not thread_id."""
        self.loop_id = loop_id
        self.workspace = workspace
        
        sothe_home = Path(SOOTHE_HOME).expanduser()
        self.run_dir = sothe_home / "runs" / loop_id  # Index by loop_id
        self.checkpoint_path = self.run_dir / "agent_loop_checkpoint.json"
        self._checkpoint: AgentLoopCheckpoint | None = None
    
    def initialize(self, thread_id: str, max_iterations: int = 10) -> AgentLoopCheckpoint:
        """Create new loop for thread."""
        
        now = datetime.now(UTC)
        loop_id = self.loop_id or str(uuid.uuid4())
        
        checkpoint = AgentLoopCheckpoint(
            loop_id=loop_id,
            thread_ids=[thread_id],  # First thread
            current_thread_id=thread_id,
            status="ready_for_next_goal",
            goal_history=[],
            current_goal_index=-1,
            working_memory_state=WorkingMemoryState(),
            thread_health_metrics=ThreadHealthMetrics(
                thread_id=thread_id,
                last_updated=now
            ),
            total_goals_completed=0,
            total_thread_switches=0,
            created_at=now,
            updated_at=now,
            schema_version="2.0"
        )
        
        self._checkpoint = checkpoint
        self.save(checkpoint)
        
        logger.info(
            "Initialized loop %s on thread %s",
            self.loop_id,
            thread_id
        )
        
        return checkpoint
```

**Changes**:
- State manager indexed by loop_id (not thread_id)
- Checkpoint path: `SOOTHE_HOME/runs/{loop_id}/`
- initialize() accepts thread_id (creates first thread in thread_ids)

**Verification**: State manager loads/saves by loop_id, checkpoint stored correctly

---

### Task 1.5: Update state_manager.py - load() and save()

**Goal**: Load/save checkpoint by loop_id

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/state_manager.py

def load(self) -> AgentLoopCheckpoint | None:
    """Load existing loop checkpoint."""
    
    if not self.checkpoint_path.exists():
        return None
    
    try:
        data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        
        # Validate schema version
        if data.get("schema_version") != "2.0":
            logger.warning(
                "Checkpoint schema %s not supported (requires v2.0)",
                data.get("schema_version")
            )
            return None
        
        checkpoint = AgentLoopCheckpoint.model_validate(data)
        self._checkpoint = checkpoint
        
        logger.info(
            "Loaded loop %s checkpoint (status %s, %d goals, %d threads)",
            self.loop_id,
            checkpoint.status,
            len(checkpoint.goal_history),
            len(checkpoint.thread_ids)
        )
        
        return checkpoint
        
    except (json.JSONDecodeError, ValueError) as e:
        logger.exception("Failed to load loop %s checkpoint", self.loop_id)
        return None


def save(self, checkpoint: AgentLoopCheckpoint) -> None:
    """Persist loop checkpoint atomically."""
    
    checkpoint.updated_at = datetime.now(UTC)
    
    self.run_dir.mkdir(parents=True, exist_ok=True)
    
    data = checkpoint.model_dump(mode="json")
    
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=self.run_dir,
        delete=False,
        encoding="utf-8"
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp_path = Path(tmp.name)
    
    tmp_path.replace(self.checkpoint_path)
    self._checkpoint = checkpoint
    
    logger.debug("Saved loop %s checkpoint (status %s)", self.loop_id, checkpoint.status)
```

**Verification**: Load/save works, schema version validated

---

### Task 1.6: Add state_manager methods - start_new_goal(), finalize_goal()

**Goal**: Create new goal record, finalize goal execution

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/state_manager.py

def start_new_goal(self, goal: str, max_iterations: int = 10) -> GoalExecutionRecord:
    """Create new goal record and clear working memory."""
    
    if self._checkpoint is None:
        raise ValueError("No checkpoint to add goal to")
    
    checkpoint = self._checkpoint
    
    # Generate goal_id (loop-scoped sequence)
    goal_id = f"{checkpoint.loop_id}_goal_{len(checkpoint.goal_history)}"
    
    now = datetime.now(UTC)
    
    goal_record = GoalExecutionRecord(
        goal_id=goal_id,
        goal_text=goal,
        thread_id=checkpoint.current_thread_id,  # Current thread
        iteration=0,
        max_iterations=max_iterations,
        status="running",  # Implicit
        reason_history=[],
        act_history=[],
        final_report="",
        evidence_summary="",
        duration_ms=0,
        tokens_used=0,
        started_at=now,
        completed_at=None
    )
    
    # Clear working memory for new goal
    checkpoint.working_memory_state = WorkingMemoryState(entries=[], spill_files=[])
    
    return goal_record


def finalize_goal(self, goal_record: GoalExecutionRecord, final_report: str) -> None:
    """Mark goal completed, update metrics."""
    
    if self._checkpoint is None:
        return
    
    checkpoint = self._checkpoint
    
    goal_record.status = "completed"
    goal_record.final_report = final_report
    goal_record.completed_at = datetime.now(UTC)
    
    # Update loop metrics
    checkpoint.total_goals_completed += 1
    checkpoint.total_duration_ms += goal_record.duration_ms
    checkpoint.total_tokens_used += goal_record.tokens_used
    
    # Update thread health (reset consecutive failures on success)
    checkpoint.thread_health_metrics.consecutive_goal_failures = 0
    checkpoint.thread_health_metrics.last_goal_status = "completed"
    
    checkpoint.status = "ready_for_next_goal"
    
    self.save(checkpoint)
    
    logger.info(
        "Finalized goal %s on thread %s (loop %s)",
        goal_record.goal_id,
        goal_record.thread_id,
        self.loop_id
    )
```

**Verification**: Goal creation/finalization works, metrics updated

---

## Phase 2: Thread Switching Policy

### Task 2.1: Create thread_switch_policy.py

**Goal**: Implement policy evaluation logic

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/thread_switch_policy.py

import logging
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.checkpoint import (
    AgentLoopCheckpoint,
    ThreadHealthMetrics,
    ThreadSwitchPolicy,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class ThreadSwitchPolicyManager:
    """Manages thread switching policy evaluation."""
    
    def __init__(self, policy: ThreadSwitchPolicy):
        self.policy = policy
    
    def evaluate(
        self,
        checkpoint: AgentLoopCheckpoint,
        next_goal: str | None = None,
        model: "BaseChatModel | None" = None
    ) -> tuple[bool, str]:
        """Evaluate all triggers. Returns (should_switch, reason)."""
        
        if not self.policy.auto_switch_enabled:
            return False, "Auto-switch disabled"
        
        if self.policy.max_thread_switches_per_loop:
            if checkpoint.total_thread_switches >= self.policy.max_thread_switches_per_loop:
                return False, "Thread switch limit reached"
        
        metrics = checkpoint.thread_health_metrics
        reasons = []
        
        # Quantitative triggers
        if self.policy.message_history_token_threshold:
            if metrics.estimated_tokens > self.policy.message_history_token_threshold:
                reasons.append(
                    f"Message history tokens ({metrics.estimated_tokens}) > threshold ({self.policy.message_history_token_threshold})"
                )
        
        if self.policy.consecutive_goal_failure_threshold:
            if metrics.consecutive_goal_failures >= self.policy.consecutive_goal_failure_threshold:
                reasons.append(
                    f"Consecutive failures ({metrics.consecutive_goal_failures}) >= threshold ({self.policy.consecutive_goal_failure_threshold})"
                )
        
        if self.policy.checkpoint_error_threshold:
            if metrics.checkpoint_errors >= self.policy.checkpoint_error_threshold:
                reasons.append(
                    f"Checkpoint errors ({metrics.checkpoint_errors}) >= threshold ({self.policy.checkpoint_error_threshold})"
                )
        
        if self.policy.subagent_timeout_threshold:
            if metrics.subagent_timeout_count >= self.policy.subagent_timeout_threshold:
                reasons.append(
                    f"Subagent timeouts ({metrics.subagent_timeout_count}) >= threshold ({self.policy.subagent_timeout_threshold})"
                )
        
        if metrics.checkpoint_corruption_detected:
            reasons.append("Checkpoint corruption detected")
        
        # Semantic trigger (goal-thread relevance) - defer to Phase 3
        # Will call goal_thread_relevance.analyze_goal_thread_relevance()
        
        # Custom triggers (extensible)
        for custom_trigger in self.policy.custom_triggers:
            if self._evaluate_custom_trigger(metrics, custom_trigger):
                reasons.append(f"Custom trigger: {custom_trigger.trigger_name}")
        
        should_switch = len(reasons) > 0
        reason_str = "; ".join(reasons) if reasons else "No trigger met"
        
        return should_switch, reason_str
    
    def _evaluate_custom_trigger(
        self,
        metrics: ThreadHealthMetrics,
        trigger: CustomSwitchTrigger
    ) -> bool:
        """Evaluate custom trigger condition (extensible)."""
        
        # Placeholder for custom trigger evaluation
        # Could use predefined operators or safe expression parser
        logger.debug("Custom trigger %s evaluation (placeholder)", trigger.trigger_name)
        return False
```

**Verification**: Policy evaluation works, quantitative triggers tested

---

## Phase 3: Goal-Thread Relevance Analysis

### Task 3.1: Create goal_thread_relevance.py

**Goal**: Implement LLM-based semantic analysis

**Implementation**:

```python
# In packages/soothe/src/soothe/cognition/agent_loop/goal_thread_relevance.py

import json
import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from soothe.cognition.agent_loop.checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    GoalThreadRelevanceAnalysis,
    ThreadSwitchPolicy,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

RELEVANCE_PROMPT_TEMPLATE = """Analyze whether the current thread context is relevant to the next goal execution or may hinder goal completion.

**Current Thread Context Summary**:
{thread_summary}

**Thread Goal History**:
{goal_history_text}

**Next Goal**: {next_goal}

**Analysis Criteria**:
Evaluate if the current thread context has any of these hindering factors:

1. **Goal Independence**: Does the next goal have NO connection to the thread's previous work?
   - No dependency on thread's outputs or findings
   - No need to reference or build upon previous context
   - Completely independent task

2. **Context Domain Mismatch**: Does the thread's focus/domain contradict the next goal's needs?
   - Thread focused on different domain (e.g., backend vs frontend)
   - Thread's problem-solving approach inappropriate for next goal
   - Context themes conflict with next goal's requirements

3. **Message History Pollution**: Does the thread contain irrelevant/distracting content?
   - Off-topic tangents unrelated to next goal
   - Clutter that doesn't contribute to next goal
   - Distractions that might mislead execution

**Response Format**:
Provide your analysis as structured JSON:

```json
{
  "is_relevant": true/false,
  "hindering_reasons": ["reason1", "reason2", ...],
  "confidence": 0.0-1.0,
  "reasoning": "detailed explanation of analysis",
  "should_switch_thread": true/false
}
```

**Note**: Failed execution attempts are NOT hindering - they provide valuable learning context. Only switch thread if clear hindering factors detected with confidence >= {confidence_threshold}.
"""


async def analyze_goal_thread_relevance(
    checkpoint: AgentLoopCheckpoint,
    next_goal: str,
    policy: ThreadSwitchPolicy,
    model: "BaseChatModel"
) -> GoalThreadRelevanceAnalysis:
    """LLM-based analysis of goal-thread relevance."""
    
    thread_summary = build_thread_summary(checkpoint)
    goal_history_text = format_goal_history(checkpoint.goal_history[-5:])  # Last 5 goals
    
    analysis_prompt = RELEVANCE_PROMPT_TEMPLATE.format(
        thread_summary=thread_summary,
        goal_history_text=goal_history_text,
        next_goal=next_goal,
        confidence_threshold=policy.relevance_confidence_threshold
    )
    
    response = await model.ainvoke([HumanMessage(content=analysis_prompt)])
    
    analysis_result = parse_llm_analysis_response(response.content)
    
    # Determine should_switch_thread
    analysis_result.should_switch_thread = (
        not analysis_result.is_relevant
        and analysis_result.confidence >= policy.relevance_confidence_threshold
    )
    
    logger.info(
        "Goal-thread relevance analysis: is_relevant=%s, confidence=%.2f, switch=%s",
        analysis_result.is_relevant,
        analysis_result.confidence,
        analysis_result.should_switch_thread
    )
    
    return analysis_result


def build_thread_summary(checkpoint: AgentLoopCheckpoint) -> str:
    """Build summary of thread context."""
    
    if not checkpoint.goal_history:
        return "No previous goals on this thread"
    
    goal_summaries = [
        f"Goal: {g.goal_text}\nOutcome: {g.status}\nThread: {g.thread_id}"
        for g in checkpoint.goal_history[-5:]
    ]
    
    thread_domains = extract_thread_domains(checkpoint.goal_history)
    
    summary = f"Thread Domain Focus: {', '.join(thread_domains)}\n\n" + "\n".join(goal_summaries)
    
    return summary


def format_goal_history(goal_history: list[GoalExecutionRecord]) -> str:
    """Format goal history for LLM prompt."""
    
    formatted = []
    for idx, goal in enumerate(goal_history):
        formatted.append(
            f"- Goal {idx}: {goal.goal_text} → Status: {goal.status}, Thread: {goal.thread_id}"
        )
    
    return "\n".join(formatted)


def extract_thread_domains(goal_history: list[GoalExecutionRecord]) -> list[str]:
    """Extract domain keywords from goal_history (placeholder)."""
    
    # Placeholder: keyword extraction from goal_text
    # Could use NLP or keyword matching
    domains = []
    for goal in goal_history:
        # Simple keyword extraction
        if "backend" in goal.goal_text.lower():
            domains.append("backend")
        elif "frontend" in goal.goal_text.lower():
            domains.append("frontend")
        elif "database" in goal.goal_text.lower():
            domains.append("database")
    
    return domains[:3] if domains else ["general"]


def parse_llm_analysis_response(response_content: str) -> GoalThreadRelevanceAnalysis:
    """Parse LLM JSON response."""
    
    # Extract JSON from response
    json_match = extract_json_from_response(response_content)
    
    if json_match:
        try:
            data = json.loads(json_match)
            return GoalThreadRelevanceAnalysis(
                thread_summary="",  # Not needed in response
                next_goal="",  # Not needed
                is_relevant=data.get("is_relevant", True),
                hindering_reasons=data.get("hindering_reasons", []),
                confidence=float(data.get("confidence", 0.0)),
                reasoning=data.get("reasoning", ""),
                should_switch_thread=data.get("should_switch_thread", False)
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse LLM JSON response: %s", e)
    
    # Fallback: parse text response
    return parse_text_response_fallback(response_content)


def extract_json_from_response(content: str) -> str | None:
    """Extract JSON block from response."""
    
    # Try to find JSON code block
    json_pattern = r'```json\s*(.*?)\s*```'
    match = re.search(json_pattern, content, re.DOTALL)
    
    if match:
        return match.group(1)
    
    # Try to find raw JSON
    json_pattern = r'\{[^{}]*"is_relevant"[^{}]*\}'
    match = re.search(json_pattern, content, re.DOTALL)
    
    if match:
        return match.group(0)
    
    return None


def parse_text_response_fallback(content: str) -> GoalThreadRelevanceAnalysis:
    """Fallback text parsing if JSON not found."""
    
    # Simple heuristics
    is_relevant = "relevant" in content.lower() and "not" not in content.lower()
    hindering = []
    
    if "goal independence" in content.lower():
        hindering.append("Goal independence")
    if "domain mismatch" in content.lower():
        hindering.append("Context domain mismatch")
    if "pollution" in content.lower():
        hindering.append("Message history pollution")
    
    return GoalThreadRelevanceAnalysis(
        thread_summary="",
        next_goal="",
        is_relevant=is_relevant,
        hindering_reasons=hindering,
        confidence=0.5,  # Low confidence for fallback
        reasoning=content[:200],  # Truncate
        should_switch_thread=len(hindering) > 0
    )
```

**Verification**: LLM analysis works, JSON parsing validated, fallback tested

---

## Verification Summary

After completing all phases, run:

```bash
./scripts/verify_finally.sh
```

Expected results:
- All models validate correctly
- State manager loads/saves by loop_id
- Thread switching policy evaluates triggers
- Goal-thread relevance analysis integrates with policy
- All tests pass (900+)

## Next Steps

After Phase 3 completion, proceed to:
- Phase 4: AgentLoop integration (thread health monitoring, policy evaluation in run_with_progress)
- Phase 5: Auto /recall on thread switch
- Phase 6: /recall command implementation
- Phase 7: Testing (unit tests, integration tests)

This guide covers Phase 1-3 (schema, state manager, policy, goal-thread relevance). Subsequent phases will be detailed in follow-up guides or direct implementation.