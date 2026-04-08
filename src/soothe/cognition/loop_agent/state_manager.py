"""Layer 2 State Manager (RFC-205).

Manages checkpoint lifecycle: initialize, save, load, recovery.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.checkpoint import (
    ActWaveRecord,
    Layer2Checkpoint,
    ReasonStepRecord,
    StepExecutionRecord,
    WorkingMemoryState,
)
from soothe.config import SOOTHE_HOME

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, ReasonResult, StepResult
    from soothe.cognition.loop_working_memory import LoopWorkingMemory

logger = logging.getLogger(__name__)


class Layer2StateManager:
    """Manages Layer 2 checkpoint lifecycle."""

    def __init__(self, thread_id: str, workspace: Path | None = None) -> None:  # noqa: ARG002
        """Initialize with thread context.

        Args:
            thread_id: Thread identifier
            workspace: Optional workspace path (not used for checkpoint storage)
        """
        self.thread_id = thread_id
        # Checkpoint is ALWAYS stored in SOOTHE_HOME, not project workspace (IG-134)
        sothe_home = Path(SOOTHE_HOME).expanduser()
        self.run_dir = sothe_home / "runs" / thread_id
        self.checkpoint_path = self.run_dir / "layer2_checkpoint.json"
        self._checkpoint: Layer2Checkpoint | None = None

    def initialize(self, goal: str, max_iterations: int = 10) -> Layer2Checkpoint:
        """Create new checkpoint for goal execution.

        Args:
            goal: Goal description
            max_iterations: Maximum loop iterations

        Returns:
            New Layer2Checkpoint instance
        """
        now = datetime.now(UTC)
        checkpoint = Layer2Checkpoint(
            thread_id=self.thread_id,
            goal=goal,
            created_at=now,
            updated_at=now,
            max_iterations=max_iterations,
        )
        self._checkpoint = checkpoint
        self.save(checkpoint)
        logger.info(
            "[Layer2] Initialized checkpoint for thread %s (goal: %s)",
            self.thread_id,
            goal[:50],
        )
        return checkpoint

    def load(self) -> Layer2Checkpoint | None:
        """Load existing checkpoint for recovery.

        Returns:
            Layer2Checkpoint if exists and valid, None otherwise
        """
        if not self.checkpoint_path.exists():
            return None

        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            checkpoint = Layer2Checkpoint.model_validate(data)
            self._checkpoint = checkpoint
            logger.info(
                "[Layer2] Loaded checkpoint for thread %s (iteration %d, status %s)",
                self.thread_id,
                checkpoint.iteration,
                checkpoint.status,
            )
        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "[Layer2] Failed to load checkpoint for thread %s",
                self.thread_id,
            )
            return None
        else:
            return checkpoint

    def save(self, checkpoint: Layer2Checkpoint) -> None:
        """Persist checkpoint to disk atomically.

        Write to temp file, then rename to avoid partial writes.

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

        logger.debug(
            "[Layer2] Saved checkpoint for thread %s (iteration %d)",
            self.thread_id,
            checkpoint.iteration,
        )

    def record_iteration(
        self,
        iteration: int,
        reason_result: ReasonResult,
        decision: AgentDecision,
        step_results: list[StepResult],
        state: LoopState,
        working_memory: LoopWorkingMemory | None,
    ) -> None:
        """Update checkpoint after each iteration.

        Args:
            iteration: Current iteration number
            reason_result: Reason phase result
            decision: AgentDecision that was executed
            step_results: Step execution results
            state: LoopState with metrics
            working_memory: Current working memory state (optional)
        """
        if self._checkpoint is None:
            logger.error("[Layer2] No checkpoint to update")
            return

        # Record Reason step
        reason_record = ReasonStepRecord(
            iteration=iteration,
            timestamp=datetime.now(UTC),
            goal_text=state.goal,
            prior_step_outputs=self._derive_prior_step_outputs(),
            reasoning=reason_result.reasoning,
            status=reason_result.status,
            goal_progress=reason_result.goal_progress,
            decision=decision.model_dump() if decision else None,
            user_summary=reason_result.user_summary,
            soothe_next_action=reason_result.soothe_next_action,
        )
        self._checkpoint.reason_history.append(reason_record)

        # Record Act wave
        act_record = self._build_act_wave_record(iteration, decision, step_results, state)
        self._checkpoint.act_history.append(act_record)

        # Record working memory state
        if working_memory is not None:
            self._checkpoint.working_memory_state = self._serialize_working_memory(working_memory)

        # Update metrics
        self._checkpoint.iteration = iteration + 1
        self._checkpoint.total_duration_ms += act_record.duration_ms
        self._checkpoint.total_tokens_used = state.total_tokens_used

        # Save checkpoint
        self.save(self._checkpoint)

    def derive_reason_conversation(self, limit: int = 10) -> list[str]:
        """Derive prior conversation from step outputs.

        Args:
            limit: Maximum step outputs to include

        Returns:
            List of XML-formatted assistant turns
        """
        if self._checkpoint is None:
            return []

        conversation = []
        conversation = [
            f"<assistant>\n{step.output}\n</assistant>"
            for act_wave in self._checkpoint.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

        return conversation[-limit:]

    def finalize(self, status: str) -> None:
        """Mark checkpoint as completed/failed.

        Args:
            status: Final status (completed, failed, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        self.save(self._checkpoint)
        logger.info(
            "[Layer2] Finalized checkpoint for thread %s (status: %s)",
            self.thread_id,
            status,
        )

    def _derive_prior_step_outputs(self) -> list[str]:
        """Get prior step outputs from previous Act waves."""
        if not self._checkpoint or not self._checkpoint.act_history:
            return []

        return [
            step.output
            for act_wave in self._checkpoint.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

    def _build_act_wave_record(
        self,
        iteration: int,
        decision: AgentDecision,
        step_results: list[StepResult],
        state: LoopState,  # noqa: ARG002 - Required for future metrics extraction
    ) -> ActWaveRecord:
        """Convert execution results to ActWaveRecord.

        Args:
            iteration: Current iteration number
            decision: AgentDecision that was executed
            step_results: Execution results
            state: LoopState with metrics (reserved for future use)

        Returns:
            ActWaveRecord for checkpoint
        """
        # Build step execution records
        step_records = []
        step_desc_map = {s.id: s.description for s in decision.steps}

        for result in step_results:
            # Use step description as input (what was sent to execution)
            step_input = step_desc_map.get(result.step_id, "")

            step_record = StepExecutionRecord(
                step_id=result.step_id,
                description=step_desc_map.get(result.step_id, ""),
                step_input=step_input,
                success=result.success,
                output=result.output or "",
                error=result.error,
                tool_calls=[],  # TODO(@chenxm): Extract from result if available
                subagent_calls=[],  # TODO(@chenxm): Extract from result if available
            )
            step_records.append(step_record)

        # Aggregate metrics from state
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)
        hit_cap = any(r.hit_subagent_cap for r in step_results)
        error_count = sum(1 for r in step_results if not r.success)

        # Calculate duration from step results
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
        """Serialize working memory state to checkpoint.

        Args:
            working_memory: LoopWorkingMemory instance

        Returns:
            WorkingMemoryState for checkpoint
        """
        spill_files = []

        # Extract working memory lines and spill file references
        lines = working_memory._lines if hasattr(working_memory, "_lines") else []

        for line in lines:
            # Parse line format: "[step_id] ✓ description — output/spill"
            # This is a simplified serialization - actual working memory entries
            # are reconstructed from step results during execution
            if "— full output in" in line and ".md`" in line:
                # Extract spill file path
                import re

                match = re.search(r"`([^`]+\.md)`", line)
                if match:
                    spill_files.append(match.group(1))

        return WorkingMemoryState(
            entries=[],  # Entries are reconstructed from step results
            spill_files=spill_files,
        )
