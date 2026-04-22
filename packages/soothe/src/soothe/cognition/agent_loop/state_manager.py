"""AgentLoop State Manager (RFC-205, RFC-608).

Manages checkpoint lifecycle: initialize, save, load, recovery.
RFC-608: Multi-thread spanning with loop_id as primary key.
RFC-409: Unified global SQLite persistence backend (loop_checkpoints.db).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

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
from soothe.cognition.agent_loop.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.cognition.agent_loop.persistence.sqlite_backend import (
    SQLitePersistenceBackend,
)

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
    """Manages AgentLoop checkpoint lifecycle (RFC-608: loop-scoped, multi-thread).

    Uses unified global SQLite backend (loop_checkpoints.db) per RFC-409.
    """

    def __init__(self, loop_id: str | None = None, workspace: Path | None = None) -> None:  # noqa: ARG002
        """Initialize with loop_id (primary key), not thread_id.

        Args:
            loop_id: Loop identifier (UUID or existing). None generates new UUID.
            workspace: Optional workspace path (not used for checkpoint storage)
        """
        self.loop_id = loop_id or str(uuid.uuid4())
        # Checkpoint stored in global loop_checkpoints.db (loop_id as partition key)
        self.db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
        self.run_dir = PersistenceDirectoryManager.get_loop_directory(
            self.loop_id
        )  # For reports/working_memory
        self._checkpoint: AgentLoopCheckpoint | None = None

    async def initialize(self, thread_id: str, max_iterations: int = 10) -> AgentLoopCheckpoint:
        """Create new loop for thread (RFC-608: loop-scoped).

        Args:
            thread_id: First thread for this loop
            max_iterations: Maximum loop iterations per goal

        Returns:
            New AgentLoopCheckpoint instance (status=ready_for_next_goal)
        """
        # Initialize global database schema
        SQLitePersistenceBackend.initialize_database_sync(self.db_path)

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
        await self._save_checkpoint_to_db(checkpoint)

        logger.info(
            "Initialized loop %s on thread %s (status: ready_for_next_goal)",
            self.loop_id,
            thread_id,
        )

        return checkpoint

    async def load(self) -> AgentLoopCheckpoint | None:
        """Load existing loop checkpoint (RFC-608: by loop_id).

        Returns:
            AgentLoopCheckpoint if exists and valid (v2.0 schema), None otherwise
        """
        if not self.db_path.exists():
            return None

        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Load loop metadata
                cursor = await db.execute(
                    """
                    SELECT thread_ids, current_thread_id, status, current_goal_index,
                           working_memory_state, thread_health_metrics,
                           total_goals_completed, total_thread_switches,
                           total_duration_ms, total_tokens_used,
                           thread_switch_pending, created_at, updated_at, schema_version
                    FROM agentloop_loops WHERE loop_id = ?
                    """,
                    (self.loop_id,),
                )
                row = await cursor.fetchone()

                if not row:
                    return None

                # Deserialize row
                thread_ids = json.loads(row[0])
                current_thread_id = row[1]
                status = row[2]
                current_goal_index = row[3]
                working_memory_state = (
                    WorkingMemoryState.model_validate_json(row[4])
                    if row[4]
                    else WorkingMemoryState(entries=[], spill_files=[])
                )
                thread_health_metrics = (
                    ThreadHealthMetrics.model_validate_json(row[5])
                    if row[5]
                    else ThreadHealthMetrics(
                        thread_id=current_thread_id, last_updated=datetime.now(UTC)
                    )
                )
                total_goals_completed = row[6]
                total_thread_switches = row[7]
                total_duration_ms = row[8]
                total_tokens_used = row[9]
                thread_switch_pending = bool(row[10])
                created_at = datetime.fromisoformat(row[11])
                updated_at = datetime.fromisoformat(row[12])
                schema_version = row[13]

                # Load goal_history from goal_records table
                cursor = await db.execute(
                    """
                    SELECT goal_id, loop_id, goal_text, thread_id, iteration, status,
                           reason_history, act_history, final_report, evidence_summary,
                           duration_ms, tokens_used, started_at, completed_at
                    FROM goal_records WHERE loop_id = ?
                    ORDER BY started_at
                    """,
                    (self.loop_id,),
                )
                goal_rows = await cursor.fetchall()

                goal_history = []
                for goal_row in goal_rows:
                    goal_record = GoalExecutionRecord(
                        goal_id=goal_row[0],
                        goal_text=goal_row[2],
                        thread_id=goal_row[3],
                        iteration=goal_row[4],
                        max_iterations=10,  # Default
                        status=goal_row[5],
                        reason_history=json.loads(goal_row[6]) if goal_row[6] else [],
                        act_history=json.loads(goal_row[7]) if goal_row[7] else [],
                        final_report=goal_row[8] or "",
                        evidence_summary=goal_row[9] or "",
                        duration_ms=goal_row[10],
                        tokens_used=goal_row[11],
                        started_at=datetime.fromisoformat(goal_row[12]),
                        completed_at=datetime.fromisoformat(goal_row[13]) if goal_row[13] else None,
                    )
                    goal_history.append(goal_record)

                checkpoint = AgentLoopCheckpoint(
                    loop_id=self.loop_id,
                    thread_ids=thread_ids,
                    current_thread_id=current_thread_id,
                    status=status,
                    goal_history=goal_history,
                    current_goal_index=current_goal_index,
                    working_memory_state=working_memory_state,
                    thread_health_metrics=thread_health_metrics,
                    total_goals_completed=total_goals_completed,
                    total_thread_switches=total_thread_switches,
                    total_duration_ms=total_duration_ms,
                    total_tokens_used=total_tokens_used,
                    thread_switch_pending=thread_switch_pending,
                    created_at=created_at,
                    updated_at=updated_at,
                    schema_version=schema_version,
                )

                self._checkpoint = checkpoint

                logger.info(
                    "Loaded loop %s checkpoint (status %s, %d goals, %d threads)",
                    self.loop_id,
                    checkpoint.status,
                    len(checkpoint.goal_history),
                    len(checkpoint.thread_ids),
                )

                return checkpoint

        except Exception:
            logger.exception("Failed to load loop %s checkpoint", self.loop_id)
            return None

    async def save(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Persist loop checkpoint to SQLite (RFC-608: indexed by loop_id).

        Args:
            checkpoint: Checkpoint to save
        """
        await self._save_checkpoint_to_db(checkpoint)

    async def _save_checkpoint_to_db(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Save checkpoint to SQLite database."""
        checkpoint.updated_at = datetime.now(UTC)

        # Database already initialized globally
        async with aiosqlite.connect(self.db_path) as db:
            # Update agentloop_loops table
            await db.execute(
                """
                INSERT OR REPLACE INTO agentloop_loops
                (loop_id, thread_ids, current_thread_id, status, current_goal_index,
                 working_memory_state, thread_health_metrics,
                 total_goals_completed, total_thread_switches,
                 total_duration_ms, total_tokens_used, thread_switch_pending,
                 created_at, updated_at, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.loop_id,
                    json.dumps(checkpoint.thread_ids),
                    checkpoint.current_thread_id,
                    checkpoint.status,
                    checkpoint.current_goal_index,
                    checkpoint.working_memory_state.model_dump_json(),
                    checkpoint.thread_health_metrics.model_dump_json(),
                    checkpoint.total_goals_completed,
                    checkpoint.total_thread_switches,
                    checkpoint.total_duration_ms,
                    checkpoint.total_tokens_used,
                    int(checkpoint.thread_switch_pending),
                    checkpoint.created_at.isoformat(),
                    checkpoint.updated_at.isoformat(),
                    checkpoint.schema_version,
                ),
            )

            # Save goal_history to goal_records table
            for goal_record in checkpoint.goal_history:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO goal_records
                    (goal_id, loop_id, goal_text, thread_id, iteration, status,
                     reason_history, act_history, final_report, evidence_summary,
                     duration_ms, tokens_used, started_at, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        goal_record.goal_id,
                        checkpoint.loop_id,
                        goal_record.goal_text,
                        goal_record.thread_id,
                        goal_record.iteration,
                        goal_record.status,
                        json.dumps([r.model_dump(mode="json") for r in goal_record.reason_history]),
                        json.dumps([a.model_dump(mode="json") for a in goal_record.act_history]),
                        goal_record.final_report,
                        goal_record.evidence_summary,
                        goal_record.duration_ms,
                        goal_record.tokens_used,
                        goal_record.started_at.isoformat(),
                        goal_record.completed_at.isoformat() if goal_record.completed_at else None,
                    ),
                )

            await db.commit()

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

    async def finalize_goal(self, goal_record: GoalExecutionRecord, final_report: str) -> None:
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

        await self.save(checkpoint)

        logger.info(
            "Finalized goal %s on thread %s (loop %s)",
            goal_record.goal_id,
            goal_record.thread_id,
            self.loop_id,
        )

    async def execute_thread_switch(self, new_thread_id: str) -> None:
        """Execute thread switch: update checkpoint with new thread (RFC-608, RFC-609).

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

        # RFC-609: Set thread switch flag for Execute briefing injection
        checkpoint.thread_switch_pending = True

        # Reset thread health metrics for new thread
        checkpoint.thread_health_metrics = ThreadHealthMetrics(
            thread_id=new_thread_id, last_updated=datetime.now(UTC)
        )

        await self.save(checkpoint)

        logger.info(
            "Thread switch executed: loop %s → thread %s (switch count: %d, briefing flag set)",
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

    async def record_iteration(
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
        await self.save(self._checkpoint)

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

    async def finalize_loop(self, status: str) -> None:
        """Mark loop finalized (no more goals accepted).

        Args:
            status: Final status (finalized, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        await self.save(self._checkpoint)

        logger.info("Finalized loop %s (status: %s)", self.loop_id, status)

    def _derive_prior_step_outputs(self, goal_record: GoalExecutionRecord | None) -> list[str]:
        """Get prior step outputs from goal's previous Act waves."""
        if not goal_record or not goal_record.act_history:
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
