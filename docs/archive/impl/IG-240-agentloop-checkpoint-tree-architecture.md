# AgentLoop Checkpoint Tree Architecture Implementation

> Implementation guide for branch-based checkpoint synchronization and smart retry with learning (RFC-611).
>
> **Crate/Module**: `packages/soothe/src/soothe/cognition/agent_loop/`, `packages/soothe/src/soothe/core/checkpoint_tree/`
> **Source**: Derived from RFC-611 (Checkpoint Tree Architecture)
> **Related RFCs**: RFC-608, RFC-409, IG-239
> **Language**: Python 3.11+
> **Framework**: LangGraph, Pydantic

---

## 1. Overview

This implementation guide specifies checkpoint synchronization via **iteration checkpoint anchors** and **failed branch management** for smart retry with learning. The implementation builds on IG-239 persistence backend to enable precise rewinding to CoreAgent checkpoints, failure analysis, and learning-based retry.

### 1.1 Purpose

Implement checkpoint tree architecture that enables:
- Iteration checkpoint anchor capture at Plan → Execute boundaries
- Failed branch creation on iteration failure detection
- LLM-based failure analysis → avoid patterns + suggested adjustments
- Smart retry: rewind to root checkpoint, inject learning, retry execution
- Checkpoint tree persistence and recovery

### 1.2 Scope

**In Scope**:
- Checkpoint anchor workflow (iteration start/end capture)
- Failed branch workflow (failure detection, branch creation)
- Failure analysis workflow (LLM analysis, learning insights)
- Smart retry workflow (rewind, inject learning, retry)
- Checkpoint tree management (main_line + failed_branches coordination)
- Integration with AgentLoop execution phases

**Out of Scope**:
- Event stream replay (RFC-411, Phase 4)
- Loop UX transformation (RFC-503, Phase 3)
- Checkpoint tree visualization CLI (RFC-504, Phase 3)

---

## 2. Checkpoint Anchor Workflow

### 2.1 Iteration Start Anchor Capture

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/anchor_manager.py`

```python
from datetime import datetime, UTC
from soothe.core.persistence.manager import AgentLoopCheckpointPersistenceManager
from soothe.cognition.agent_loop.checkpoint import CheckpointAnchor

class CheckpointAnchorManager:
    """Manager for iteration checkpoint anchor capture."""
    
    def __init__(self, loop_id: str):
        """Initialize anchor manager.
        
        Args:
            loop_id: AgentLoop identifier.
        """
        self.loop_id = loop_id
        self.persistence_manager = AgentLoopCheckpointPersistenceManager()
    
    async def capture_iteration_start_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpointer: BaseCheckpointSaver,
    ) -> CheckpointAnchor:
        """Capture iteration start anchor before Plan phase.
        
        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance.
        
        Returns:
            Captured checkpoint anchor.
        """
        # Get current CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        
        if not checkpoint_tuple:
            raise ValueError(f"No checkpoint found for thread {thread_id}")
        
        checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
        checkpoint_ns = checkpoint_tuple.config["configurable"].get("checkpoint_ns", "")
        
        # Create anchor
        anchor = CheckpointAnchor(
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            checkpoint_ns=checkpoint_ns,
            anchor_type="iteration_start",
            timestamp=datetime.now(UTC),
        )
        
        # Save anchor to persistence
        await self.persistence_manager.save_checkpoint_anchor(
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            anchor_type="iteration_start",
        )
        
        # Update main_line_checkpoints
        checkpoint = await self.load_checkpoint()
        checkpoint.checkpoint_tree_ref.main_line_checkpoints[iteration] = checkpoint_id
        checkpoint.updated_at = datetime.now(UTC)
        await self.save_checkpoint(checkpoint)
        
        return anchor
    
    async def capture_iteration_end_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpointer: BaseCheckpointSaver,
        execution_summary: dict[str, Any],
    ) -> CheckpointAnchor:
        """Capture iteration end anchor after successful Execute phase.
        
        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance.
            execution_summary: Execution summary (status, tools, reasoning).
        
        Returns:
            Captured checkpoint anchor.
        """
        # Get latest CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        
        checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
        
        # Create anchor with execution summary
        anchor = CheckpointAnchor(
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            checkpoint_ns=checkpoint_tuple.config["configurable"].get("checkpoint_ns", ""),
            anchor_type="iteration_end",
            timestamp=datetime.now(UTC),
            iteration_status="success",
            next_action_summary=execution_summary.get("next_action"),
            tools_executed=execution_summary.get("tools_executed", []),
            reasoning_decision=execution_summary.get("reasoning_decision"),
        )
        
        # Save anchor with execution summary
        await self.persistence_manager.save_checkpoint_anchor(
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            anchor_type="iteration_end",
            execution_summary=execution_summary,
        )
        
        # Update main_line_checkpoints (replace start with end)
        checkpoint = await self.load_checkpoint()
        checkpoint.checkpoint_tree_ref.main_line_checkpoints[iteration] = checkpoint_id
        checkpoint.updated_at = datetime.now(UTC)
        await self.save_checkpoint(checkpoint)
        
        return anchor
```

---

## 3. Failed Branch Workflow

### 3.1 Failure Detection & Branch Creation

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/branch_manager.py`

```python
import uuid
from datetime import datetime, UTC
from soothe.core.persistence.manager import AgentLoopCheckpointPersistenceManager
from soothe.cognition.agent_loop.checkpoint import FailedBranchRecord

class FailedBranchManager:
    """Manager for failed branch creation and analysis."""
    
    def __init__(self, loop_id: str):
        """Initialize branch manager.
        
        Args:
            loop_id: AgentLoop identifier.
        """
        self.loop_id = loop_id
        self.persistence_manager = AgentLoopCheckpointPersistenceManager()
    
    async def detect_iteration_failure(
        self,
        iteration: int,
        thread_id: str,
        failure_reason: str,
        checkpointer: BaseCheckpointSaver,
    ) -> FailedBranchRecord:
        """Detect iteration failure and create failed branch.
        
        Args:
            iteration: Iteration where failure occurred.
            thread_id: Thread where failure occurred.
            failure_reason: High-level failure reason.
            checkpointer: LangGraph checkpointer.
        
        Returns:
            Created failed branch record.
        """
        # Get current failure checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        failure_checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
        
        # Get root checkpoint (previous iteration's end anchor)
        checkpoint = await self.load_checkpoint()
        prev_iteration = iteration - 1
        root_checkpoint_id = checkpoint.checkpoint_tree_ref.main_line_checkpoints.get(
            prev_iteration
        )
        
        if not root_checkpoint_id:
            # No previous anchor (first iteration failure)
            root_checkpoint_id = checkpoint.checkpoint_tree_ref.main_line_checkpoints.get(
                0, "initial"
            )
        
        # Extract execution path (checkpoints from root → failure)
        execution_path = await self._get_checkpoints_between(
            thread_id=thread_id,
            start_checkpoint_id=root_checkpoint_id,
            end_checkpoint_id=failure_checkpoint_id,
        )
        
        # Create failed branch
        branch_id = f"branch_{uuid.uuid4().hex[:8]}"
        failed_branch = FailedBranchRecord(
            branch_id=branch_id,
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            root_checkpoint_id=root_checkpoint_id,
            failure_checkpoint_id=failure_checkpoint_id,
            execution_path=execution_path,
            failure_reason=failure_reason,
            created_at=datetime.now(UTC),
        )
        
        # Save failed branch
        await self.persistence_manager.save_failed_branch(
            branch_id=branch_id,
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            root_checkpoint_id=root_checkpoint_id,
            failure_checkpoint_id=failure_checkpoint_id,
            failure_reason=failure_reason,
            execution_path=execution_path,
        )
        
        # Update checkpoint tree
        checkpoint.checkpoint_tree_ref.failed_branches[branch_id] = failed_branch
        checkpoint.updated_at = datetime.now(UTC)
        await self.save_checkpoint(checkpoint)
        
        return failed_branch
    
    async def _get_checkpoints_between(
        self,
        thread_id: str,
        start_checkpoint_id: str,
        end_checkpoint_id: str,
    ) -> list[str]:
        """Extract checkpoint IDs between start and end.
        
        Args:
            thread_id: Thread identifier.
            start_checkpoint_id: Start checkpoint ID.
            end_checkpoint_id: End checkpoint ID.
        
        Returns:
            List of checkpoint IDs from start → end.
        """
        # TODO: Implement checkpoint history traversal using LangGraph API
        # This requires querying checkpoint history from checkpointer
        return [start_checkpoint_id, end_checkpoint_id]  # Placeholder
```

---

## 4. Failure Analysis Workflow

### 4.1 LLM-Based Failure Analysis

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/failure_analyzer.py`

```python
from soothe.config import SootheConfig

class FailureAnalyzer:
    """LLM-based failure analysis for learning insights."""
    
    def __init__(self, config: SootheConfig):
        """Initialize failure analyzer.
        
        Args:
            config: Soothe configuration.
        """
        self.config = config
    
    async def analyze_failure(
        self,
        branch: FailedBranchRecord,
        failure_context: str,
    ) -> FailedBranchRecord:
        """Analyze failure and compute learning insights.
        
        Args:
            branch: Failed branch record.
            failure_context: Failure context from CoreAgent checkpoints.
        
        Returns:
            Updated branch with learning insights.
        """
        # Create LLM analysis prompt
        analysis_prompt = f"""
Analyze this execution failure and provide structured insights:

Failure Reason: {branch.failure_reason}

Execution Context:
{failure_context}

Provide analysis in JSON format:
{
  "root_cause": "<string>",
  "context": "<string>",
  "patterns": ["<pattern1>", "<pattern2>"],
  "suggestions": ["<suggestion1>", "<suggestion2>"]
}
"""
        
        # Call LLM for analysis
        model = self.config.create_chat_model("default")
        response = await model.ainvoke(analysis_prompt)
        
        # Parse LLM response
        insights = self._parse_llm_response(response.content)
        
        # Update branch with learning
        branch.failure_insights = {
            "root_cause": insights.get("root_cause"),
            "context": insights.get("context"),
        }
        branch.avoid_patterns = insights.get("patterns", [])
        branch.suggested_adjustments = insights.get("suggestions", [])
        branch.analyzed_at = datetime.now(UTC)
        
        # Save updated branch
        persistence_manager = AgentLoopCheckpointPersistenceManager()
        await persistence_manager.update_branch_analysis(
            branch_id=branch.branch_id,
            loop_id=branch.loop_id,
            failure_insights=branch.failure_insights,
            avoid_patterns=branch.avoid_patterns,
            suggested_adjustments=branch.suggested_adjustments,
        )
        
        # Update checkpoint tree
        checkpoint = await self.load_checkpoint(branch.loop_id)
        checkpoint.checkpoint_tree_ref.failed_branches[branch.branch_id] = branch
        checkpoint.updated_at = datetime.now(UTC)
        await self.save_checkpoint(checkpoint)
        
        return branch
    
    def _parse_llm_response(self, response_content: str) -> dict[str, Any]:
        """Parse LLM JSON response.
        
        Args:
            response_content: LLM response content.
        
        Returns:
            Parsed insights dictionary.
        """
        # Extract JSON from response (handle markdown code blocks)
        import json
        import re
        
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*(.*?)\s*```', response_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Assume response is plain JSON
            json_str = response_content
        
        return json.loads(json_str)
```

---

## 5. Smart Retry Workflow

### 5.1 Rewind and Retry with Learning

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/smart_retry_manager.py`

```python
class SmartRetryManager:
    """Manager for smart retry with learning injection."""
    
    async def execute_smart_retry(
        self,
        branch: FailedBranchRecord,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        """Rewind to root checkpoint and retry with learning.
        
        Args:
            branch: Failed branch with learning insights.
            checkpointer: LangGraph checkpointer.
        """
        # Step 1: Rewind CoreAgent to root checkpoint
        await self._restore_coreagent_checkpoint(
            thread_id=branch.thread_id,
            checkpoint_id=branch.root_checkpoint_id,
            checkpointer=checkpointer,
        )
        
        # Step 2: Inject learning into Plan phase
        retry_context = {
            "previous_failure": {
                "reason": branch.failure_reason,
                "avoid_patterns": branch.avoid_patterns,
                "suggested_adjustments": branch.suggested_adjustments,
            },
            "retry_mode": True,
            "learning_applied": branch.suggested_adjustments,
        }
        
        # Step 3: Emit branch retry event
        from soothe.core.event_catalog import custom_event, BRANCH_RETRY_STARTED
        yield custom_event({
            "type": BRANCH_RETRY_STARTED,
            "branch_id": branch.branch_id,
            "retry_iteration": self.current_iteration + 1,
            "learning_applied": branch.suggested_adjustments,
        })
        
        # Step 4: Execute retry with learning context
        await self.execute_plan_phase_with_context(retry_context)
    
    async def _restore_coreagent_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        """Restore CoreAgent to specific checkpoint.
        
        Args:
            thread_id: Thread identifier.
            checkpoint_id: Target checkpoint ID.
            checkpointer: LangGraph checkpointer.
        """
        # LangGraph checkpoint restoration via aput()
        # This requires loading checkpoint tuple and calling aput()
        
        config = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
        
        # Load checkpoint data
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        
        if not checkpoint_tuple:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for thread {thread_id}")
        
        # Restore checkpoint using aput() (this creates new checkpoint from old state)
        await checkpointer.aput(
            config=config,
            checkpoint=checkpoint_tuple.checkpoint,
            metadata=checkpoint_tuple.metadata,
            new_versions={},  # No new versions (restoring existing)
        )
```

---

## 6. Integration with AgentLoop Execution

### 6.1 Integrate into Plan → Execute Loop

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

```python
class AgentLoop:
    """AgentLoop execution with checkpoint tree integration."""
    
    async def run_with_progress(self, core_agent, query: str, thread_id: str):
        """Run AgentLoop with checkpoint tree management.
        
        Args:
            core_agent: CoreAgent instance.
            query: User query.
            thread_id: Current thread ID.
        """
        iteration = 0
        
        # Capture iteration start anchor
        anchor_manager = CheckpointAnchorManager(self.loop_id)
        await anchor_manager.capture_iteration_start_anchor(
            iteration=iteration,
            thread_id=thread_id,
            checkpointer=core_agent.checkpointer,
        )
        
        # Execute Plan → Execute
        try:
            # Plan phase
            plan_result = await self.execute_plan_phase(query)
            
            # Execute phase
            execute_result = await self.execute_act_phase(plan_result)
            
            # Capture iteration end anchor (success)
            execution_summary = {
                "status": "success",
                "next_action": execute_result.get("next_action"),
                "tools_executed": execute_result.get("tools_executed", []),
                "reasoning_decision": plan_result.get("decision"),
            }
            
            await anchor_manager.capture_iteration_end_anchor(
                iteration=iteration,
                thread_id=thread_id,
                checkpointer=core_agent.checkpointer,
                execution_summary=execution_summary,
            )
            
        except Exception as e:
            # Failure detected - create failed branch
            branch_manager = FailedBranchManager(self.loop_id)
            failed_branch = await branch_manager.detect_iteration_failure(
                iteration=iteration,
                thread_id=thread_id,
                failure_reason=str(e),
                checkpointer=core_agent.checkpointer,
            )
            
            # Analyze failure
            analyzer = FailureAnalyzer(self.config)
            failed_branch = await analyzer.analyze_failure(
                branch=failed_branch,
                failure_context=extract_failure_context(e),
            )
            
            # Execute smart retry
            retry_manager = SmartRetryManager(self.loop_id)
            await retry_manager.execute_smart_retry(
                branch=failed_branch,
                checkpointer=core_agent.checkpointer,
            )
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
@pytest.mark.asyncio
async def test_iteration_anchor_capture():
    """Test iteration anchor capture workflow."""
    
    anchor_manager = CheckpointAnchorManager("test_loop")
    
    # Mock checkpointer
    mock_checkpointer = MockCheckpointer()
    
    anchor = await anchor_manager.capture_iteration_start_anchor(
        iteration=0,
        thread_id="test_thread",
        checkpointer=mock_checkpointer,
    )
    
    assert anchor.iteration == 0
    assert anchor.anchor_type == "iteration_start"


@pytest.mark.asyncio
async def test_failed_branch_creation():
    """Test failed branch creation on failure."""
    
    branch_manager = FailedBranchManager("test_loop")
    
    failed_branch = await branch_manager.detect_iteration_failure(
        iteration=3,
        thread_id="test_thread",
        failure_reason="Tool execution timeout",
        checkpointer=mock_checkpointer,
    )
    
    assert failed_branch.iteration == 3
    assert failed_branch.failure_reason == "Tool execution timeout"
```

---

## 8. Verification Procedure

```bash
# Run unit tests
make test-unit

# Manual verification
soothe doctor --check checkpoint-tree

# Test smart retry workflow
soothe "query that triggers timeout" --loop test_loop
soothe loop tree test_loop  # Verify branch creation
```

---

## 9. Critical Files

### 9.1 Files to Create

- `packages/soothe/src/soothe/cognition/agent_loop/anchor_manager.py`
- `packages/soothe/src/soothe/cognition/agent_loop/branch_manager.py`
- `packages/soothe/src/soothe/cognition/agent_loop/failure_analyzer.py`
- `packages/soothe/src/soothe/cognition/agent_loop/smart_retry_manager.py`
- `tests/unit/cognition/agent_loop/test_checkpoint_tree.py`

### 9.2 Files to Modify

- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py` (integrate checkpoint tree workflows)
- `packages/soothe/src/soothe/cognition/agent_loop/checkpoint.py` (add CheckpointAnchor, FailedBranchRecord models)
- `packages/soothe/src/soothe/core/event_catalog.py` (add BRANCH_CREATED, BRANCH_ANALYZED, BRANCH_RETRY_STARTED events)

---

**End of Phase 2 Implementation Guide (IG-240)**