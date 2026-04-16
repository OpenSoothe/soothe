"""AgentLoop State Manager (RFC-205, RFC-608).

Manages checkpoint lifecycle: initialize, save, load, recovery.
RFC-608: Multi-thread spanning with loop_id as primary key.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.checkpoint import (
    ActWaveRecord,
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    ReasonStepRecord,
    StepExecutionRecord,
    ThreadHealthMetrics,
    ThreadSwitchPolicy,
    WorkingMemoryState,
)
from soothe.config import SOOTHE_HOME

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.schemas import (
        AgentDecision,
        LoopState,
        PlanResult,
        StepResult,
    )
    from soothe.cognition.agent_loop.working_memory import LoopWorkingMemory

logger = logging.getLogger(__name__)


class AgentLoopStateManager:
    """Manages AgentLoop checkpoint lifecycle (RFC-608: loop-scoped, multi-thread)."""

    def __init__(self, loop_id: str | None = None, workspace: Path | None = None) -> None:  # noqa: ARG002
        """Initialize with loop_id (primary key), not thread_id.

        Args:
            loop_id: Loop identifier (UUID or existing). None generates new UUID.
            workspace: Optional workspace path (not used for checkpoint storage)
        """
        self.loop_id = loop_id or str(uuid.uuid4())
        # Checkpoint is ALWAYS stored in SOOTHE_HOME, indexed by loop_id (RFC-608)
        sothe_home = Path(SOOTHE_HOME).expanduser()
        self.run_dir = sothe_home / "runs" / self.loop_id
        self.checkpoint_path = self.run_dir / "agent_loop_checkpoint.json"
        self._checkpoint: AgentLoopCheckpoint | None = None

    def initialize(self, thread_id: str, max_iterations: int = 10) -> AgentLoopCheckpoint:
        """Create new loop for thread (RFC-608: loop-scoped).

        Args:
            thread_id: First thread for this loop
            max_iterations: Maximum loop iterations per goal

        Returns:
            New AgentLoopCheckpoint instance (status=ready_for_next_goal)
        """
        now = datetime.now(UTC)

        checkpoint = AgentLoopCheckpoint(
            loop_id=self.loop_id,
            thread_ids=[thread_id],  # First thread
            current_thread_id=thread_id,
            status="ready_for_next_goal",
            goal_history=[],
            current_goal_index=-1,  # No active goal yet
            working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
            thread_health_metrics=ThreadHealthMetrics(thread_id=thread_id, last_updated=now),
            total_goals_completed=0,
            total_thread_switches=0,
            total_duration_ms=0,
            total_tokens_used=0,
            created_at=now,
            updated_at=now,
            schema_version="2.0",
        )

        self._checkpoint = checkpoint
        self.save(checkpoint)

        logger.info(
            "Initialized loop %s on thread %s (status: ready_for_next_goal)",
            self.loop_id,
            thread_id,
        )

        return checkpoint

    def load(self) -> AgentLoopCheckpoint | None:
        """Load existing loop checkpoint (RFC-608: by loop_id).

        Returns:
            AgentLoopCheckpoint if exists and valid (v2.0 schema), None otherwise
        """
        if not self.checkpoint_path.exists():
            return None

        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))

            # Validate schema version (RFC-608: require v2.0)
            if data.get("schema_version") != "2.0":
                logger.warning(
                    "Checkpoint schema %s not supported (requires v2.0 for multi-thread)",
                    data.get("schema_version"),
                )
                return None

            checkpoint = AgentLoopCheckpoint.model_validate(data)
            self._checkpoint = checkpoint

            logger.info(
                "Loaded loop %s checkpoint (status %s, %d goals, %d threads)",
                self.loop_id,
                checkpoint.status,
                len(checkpoint.goal_history),
                len(checkpoint.thread_ids),
            )

            return checkpoint

        except (json.JSONDecodeError, ValueError):
            logger.exception("Failed to load loop %s checkpoint", self.loop_id)
            return None

    def save(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Persist loop checkpoint atomically (RFC-608: indexed by loop_id).

        Args:
            checkpoint: Checkpoint to save
        """
        checkpoint.updated_at = datetime.now(UTC)

        # Ensure run directory exists
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Write atomically: temp → rename
        data = checkpoint.model_dump(mode="json")
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=self.run_dir,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp.name)

        # Atomic rename
        tmp_path.replace(self.checkpoint_path)
        self._checkpoint = checkpoint

        logger.debug("Saved loop %s checkpoint (status %s)", self.loop_id, checkpoint.status)

    def start_new_goal(self, goal: str, max_iterations: int = 10) -> GoalExecutionRecord:
        """Create new goal record and clear working memory (RFC-608).

        Args:
            goal: Goal description
            max_iterations: Maximum iterations for this goal

        Returns:
            New GoalExecutionRecord (thread_id = current_thread_id)
        """
        if self._checkpoint is None:
            raise ValueError("No checkpoint to add goal to")

        checkpoint = self._checkpoint

        # Generate goal_id (loop-scoped sequence, independent of thread)
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
            completed_at=None,
        )

        # Clear working memory for new goal
        checkpoint.working_memory_state = WorkingMemoryState(entries=[], spill_files=[])

        return goal_record

    def finalize_goal(self, goal_record: GoalExecutionRecord, final_report: str) -> None:
        """Mark goal completed, update loop metrics (RFC-608).

        Args:
            goal_record: Goal execution record to finalize
            final_report: Generated final report content
        """
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
            self.loop_id,
        )

    def execute_thread_switch(self, new_thread_id: str) -> None:
        """Execute thread switch: update checkpoint with new thread (RFC-608).

        Args:
            new_thread_id: New thread to switch to
        """
        if self._checkpoint is None:
            return

        checkpoint = self._checkpoint

        # Add new thread to thread_ids
        checkpoint.thread_ids.append(new_thread_id)
        checkpoint.current_thread_id = new_thread_id
        checkpoint.total_thread_switches += 1

        # Reset thread health metrics for new thread
        checkpoint.thread_health_metrics = ThreadHealthMetrics(
            thread_id=new_thread_id, last_updated=datetime.now(UTC)
        )

        self.save(checkpoint)

        logger.info(
            "Thread switch executed: loop %s → thread %s (switch count: %d)",
            self.loop_id,
            new_thread_id,
            checkpoint.total_thread_switches,
        )

    def inject_previous_goal_context(self, limit: int = 1) -> list[str]:
        """Inject previous goal final_report into Plan phase (RFC-608: same-thread continuation).

        Args:
            limit: Number of previous goals to inject (default: 1)

        Returns:
            List of XML-formatted previous goal context blocks
        """
        if self._checkpoint is None or not self._checkpoint.goal_history:
            return []

        # Get most recent completed goals on current thread
        previous_goals = [
            g for g in self._checkpoint.goal_history[-limit:] if g.status == "completed"
        ]

        if not previous_goals:
            return []

        context_blocks = []
        for goal in previous_goals:
            context_block = (
                f"<previous_goal>\n"
                f"Goal: {goal.goal_text}\n"
                f"Status: {goal.status}\n"
                f"Thread: {goal.thread_id}\n"
                f"Output:\n{goal.final_report}\n"
                f"</previous_goal>"
            )
            context_blocks.append(context_block)

        return context_blocks

    def auto_recall_on_thread_switch(
        self, next_goal: str | None, policy: ThreadSwitchPolicy
    ) -> list[str]:
        """Auto /recall knowledge from previous threads on thread switch (RFC-608).

        Args:
            next_goal: Next goal text (for relevance query) or None
            policy: Thread switching policy (knowledge_transfer_limit)

        Returns:
            List of XML-formatted recalled knowledge blocks
        """
        if self._checkpoint is None:
            return []

        checkpoint = self._checkpoint

        # Previous threads (exclude current new thread)
        previous_thread_ids = checkpoint.thread_ids[:-1]

        if not previous_thread_ids:
            return []  # No previous threads

        # Build searchable corpus from previous goal_history
        documents = []
        for goal_record in checkpoint.goal_history:
            if goal_record.thread_id in previous_thread_ids:
                doc_text = f"{goal_record.goal_text}\n{goal_record.final_report}"
                documents.append(
                    {
                        "thread_id": goal_record.thread_id,
                        "goal_id": goal_record.goal_id,
                        "goal_text": goal_record.goal_text,
                        "text": doc_text,
                    }
                )

        if not documents:
            return []  # No previous goals to recall

        # TODO: Integrate VectorStoreProtocol for semantic search
        # Placeholder: Return top-K recent goals
        top_k = min(policy.knowledge_transfer_limit, len(documents))

        recalled_knowledge = []
        for doc in documents[-top_k:]:
            excerpt = (
                f"<recalled_knowledge>\n"
                f"From thread {doc['thread_id']}, goal: {doc['goal_text']}\n"
                f"Output:\n{doc['text'][:500]}...\n"
                f"</recalled_knowledge>"
            )
            recalled_knowledge.append(excerpt)

        logger.info(
            "Auto /recall on thread switch: %d knowledge blocks from %d previous threads",
            len(recalled_knowledge),
            len(previous_thread_ids),
        )

        return recalled_knowledge

    def record_iteration(
        self,
        goal_record: GoalExecutionRecord,
        iteration: int,
        plan_result: PlanResult,
        decision: AgentDecision,
        step_results: list[StepResult],
        state: LoopState,
        working_memory: LoopWorkingMemory | None,
    ) -> None:
        """Update goal record after each iteration (RFC-608).

        Args:
            goal_record: Goal execution record to update
            iteration: Current iteration number
            plan_result: Plan phase result
            decision: AgentDecision that was executed
            step_results: Step execution results
            state: LoopState with metrics
            working_memory: Current working memory state (optional)
        """
        if self._checkpoint is None:
            logger.error("No checkpoint to update")
            return

        # Record Plan step
        reason_record = ReasonStepRecord(
            iteration=iteration,
            timestamp=datetime.now(UTC),
            goal_text=state.goal,
            prior_step_outputs=self._derive_prior_step_outputs(goal_record),
            reasoning=plan_result.reasoning,
            status=plan_result.status,
            goal_progress=plan_result.goal_progress,
            decision=decision.model_dump() if decision else None,
            next_action=plan_result.next_action,
        )
        goal_record.reason_history.append(reason_record)

        # Record Act wave
        act_record = self._build_act_wave_record(iteration, decision, step_results, state)
        goal_record.act_history.append(act_record)

        # Record working memory state
        if working_memory is not None:
            self._checkpoint.working_memory_state = self._serialize_working_memory(working_memory)

        # Update goal metrics
        goal_record.iteration = iteration + 1
        goal_record.duration_ms += act_record.duration_ms
        goal_record.tokens_used = state.total_tokens_used

        # Save checkpoint
        self.save(self._checkpoint)

    def derive_plan_conversation(self, limit: int = 10) -> list[str]:
        """Derive prior conversation from current goal's step outputs.

        Args:
            limit: Maximum step outputs to include

        Returns:
            List of XML-formatted assistant turns
        """
        if self._checkpoint is None or self._checkpoint.current_goal_index < 0:
            return []

        goal_record = self._checkpoint.goal_history[self._checkpoint.current_goal_index]

        conversation = [
            f"<assistant>\n{step.output}\n</assistant>"
            for act_wave in goal_record.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

        return conversation[-limit:]

    def finalize_loop(self, status: str) -> None:
        """Mark loop finalized (no more goals accepted).

        Args:
            status: Final status (finalized, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        self.save(self._checkpoint)

        logger.info("Finalized loop %s (status: %s)", self.loop_id, status)

    def _derive_prior_step_outputs(self, goal_record: GoalExecutionRecord) -> list[str]:
        """Get prior step outputs from goal's previous Act waves."""
        if not goal_record.act_history:
            return []

        return [
            step.output
            for act_wave in goal_record.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

    def _build_act_wave_record(
        self,
        iteration: int,
        decision: AgentDecision,
        step_results: list[StepResult],
        state: LoopState,  # noqa: ARG002 - Reserved for future metrics extraction
    ) -> ActWaveRecord:
        """Convert execution results to ActWaveRecord."""
        # Build step execution records
        step_records = []
        step_desc_map = {s.id: s.description for s in decision.steps}

        for result in step_results:
            step_input = step_desc_map.get(result.step_id, "")
            outcome_summary = result.to_evidence_string(truncate=False) if result.success else ""

            step_record = StepExecutionRecord(
                step_id=result.step_id,
                description=step_desc_map.get(result.step_id, ""),
                step_input=step_input,
                success=result.success,
                output=outcome_summary,
                error=result.error,
                tool_calls=[],  # Reserved for future extraction
                subagent_calls=[],  # Reserved for future extraction
            )
            step_records.append(step_record)

        # Aggregate metrics
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)
        hit_cap = any(r.hit_subagent_cap for r in step_results)
        error_count = sum(1 for r in step_results if not r.success)
        duration_ms = sum(r.duration_ms for r in step_results)

        return ActWaveRecord(
            iteration=iteration,
            timestamp=datetime.now(UTC),
            steps=step_records,
            execution_mode=decision.execution_mode,
            duration_ms=duration_ms,
            tool_call_count=total_tool_calls,
            subagent_task_count=total_subagent_tasks,
            hit_subagent_cap=hit_cap,
            error_count=error_count,
        )

    def _serialize_working_memory(self, working_memory: LoopWorkingMemory) -> WorkingMemoryState:
        """Serialize working memory state."""
        spill_files = []
        lines = working_memory._lines if hasattr(working_memory, "_lines") else []

        for line in lines:
            if "— full output in" in line and ".md`" in line:
                import re

                match = re.search(r"`([^`]+\.md)`", line)
                if match:
                    spill_files.append(match.group(1))

        return WorkingMemoryState(
            entries=[],  # Entries reconstructed from step results
            spill_files=spill_files,
        )
