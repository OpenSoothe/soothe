"""RunArtifactStore -- structured run output directory (RFC-0010).

Manages ``$SOOTHE_HOME/runs/{thread_id}/`` with hierarchical goal/step
layout, atomic checkpoint writes, and a manifest tracking all artifacts.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.core import FrameworkFilesystem

logger = logging.getLogger(__name__)

# Serialize writes when multiple goals share the same run directory (parallel autonomous goals).
_run_dir_locks: dict[str, threading.RLock] = {}
_run_dir_locks_guard = threading.Lock()


def _lock_for_run_dir(run_dir: Path) -> threading.RLock:
    key = str(run_dir.resolve())
    with _run_dir_locks_guard:
        lock = _run_dir_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _run_dir_locks[key] = lock
        return lock


class ArtifactEntry(BaseModel):
    """A single artifact tracked in the run manifest.

    Args:
        path: Path relative to the run directory.
        source: Whether the file was produced (copied) or referenced.
        original_path: Absolute workspace path for referenced artifacts.
        tool_name: Tool that created the artifact.
        step_id: Step that produced this artifact.
        goal_id: Goal that owns this artifact.
        size_bytes: File size in bytes.
    """

    path: str
    source: Literal["produced", "reference"]
    original_path: str = ""
    tool_name: str = ""
    step_id: str = ""
    goal_id: str = ""
    size_bytes: int = 0


class RunManifest(BaseModel):
    """Index of all artifacts and metadata for a run.

    Args:
        version: Schema version.
        thread_id: Thread identifier.
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
        query: Original user query.
        mode: Execution mode.
        status: Current run status.
        goals: Goal IDs in this run.
        artifacts: Tracked artifacts.
    """

    version: int = 1
    thread_id: str
    created_at: str
    updated_at: str
    query: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
    goals: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactEntry] = Field(default_factory=list)


class RunArtifactStore:
    """Manages run artifact directory under ``$SOOTHE_HOME/runs/{thread_id}/``.

    Provides atomic checkpoint writes, structured step/goal reports in
    both JSON and Markdown, and a manifest of all tracked artifacts.

    Always uses the durability thread id (not synthetic per-goal ids). Parallel
    goals sharing one run dir coordinate via a per-directory lock.

    Args:
        thread_id: Thread identifier for this run (canonical thread id).
        config: Soothe configuration (optional; reserved for future use).
        soothe_home: Root Soothe home directory (fallback when config=None).
    """

    def __init__(
        self,
        thread_id: str,
        config: SootheConfig | None = None,
        soothe_home: str = SOOTHE_HOME,
    ) -> None:
        """Initialize the artifact store for a run.

        Args:
            thread_id: Thread identifier for this run.
            config: Soothe configuration (optional).
            soothe_home: Root Soothe home directory (fallback when config=None).
        """
        self._thread_id = thread_id
        self._config = config
        self._run_dir = Path(soothe_home).expanduser() / "runs" / thread_id
        self._file_lock = _lock_for_run_dir(self._run_dir)

        self._run_dir.mkdir(parents=True, exist_ok=True)

        # Reset FrameworkFilesystem to avoid test pollution (IG-181)
        # Tests may initialize FrameworkFilesystem with a different workspace,
        # causing path resolution issues in write methods
        FrameworkFilesystem.reset()

        existing = self.load_manifest()
        if existing:
            self._manifest = existing
            logger.info("Artifact store loaded existing manifest for %s", self._run_dir)
        else:
            now = datetime.now(UTC).isoformat()
            self._manifest = RunManifest(
                thread_id=thread_id,
                created_at=now,
                updated_at=now,
            )
            logger.info("Artifact store initialized at %s", self._run_dir)

    @property
    def run_dir(self) -> Path:
        """Root directory for this run."""
        return self._run_dir

    @property
    def conversation_log_path(self) -> Path:
        """Path to the conversation JSONL log."""
        return self._run_dir / "conversation.jsonl"

    @property
    def manifest(self) -> RunManifest:
        """Current run manifest."""
        return self._manifest

    def _resolve_artifact_path(self, relative_path: str) -> str:
        """Resolve artifact path for FrameworkFilesystem (absolute under run dir).

        Args:
            relative_path: Path like "goals/{goal_id}/steps/{step_id}/report.json".

        Returns:
            Absolute filesystem path under ``self._run_dir``.
        """
        return str(self._run_dir / relative_path)

    def ensure_step_dir(self, goal_id: str, step_id: str) -> Path:
        """Create and return the step directory.

        Args:
            goal_id: Goal identifier.
            step_id: Step identifier.

        Returns:
            Path to the step directory.
        """
        d = self._run_dir / "goals" / goal_id / "steps" / step_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_step_report(
        self,
        goal_id: str,
        step_id: str,
        description: str,
        status: str,
        result: str,
        duration_ms: int,
        depends_on: list[str] | None = None,
    ) -> None:
        """Write step report as JSON and Markdown.

        Args:
            goal_id: Goal identifier.
            step_id: Step identifier.
            description: Step description.
            status: Final step status.
            result: Step output text.
            duration_ms: Execution time in milliseconds.
            depends_on: Step dependency IDs.
        """
        from soothe.protocols.planner import StepReport

        with self._file_lock:
            # Ensure step directory exists
            self.ensure_step_dir(goal_id, step_id)
            deps = depends_on or []

            report = StepReport(
                step_id=step_id,
                description=description,
                status=status if status in ("completed", "failed") else "skipped",
                result=result,
                duration_ms=duration_ms,
                depends_on=deps,
            )

            # Try FrameworkFilesystem first, fallback to direct Path operations
            try:
                backend = FrameworkFilesystem.get()

                # Write JSON report
                json_path = self._resolve_artifact_path(
                    f"goals/{goal_id}/steps/{step_id}/report.json"
                )
                backend.write(json_path, report.model_dump_json(indent=2))

                # Write Markdown report
                md_parts = [
                    f"# Step: {description}\n",
                    f"**Status**: {report.status}  \n**Duration**: {duration_ms}ms\n",
                ]
                if deps:
                    md_parts.append(f"**Depends on**: {', '.join(deps)}\n")
                md_parts.append(f"\n## Result\n\n{result}\n")

                md_path = self._resolve_artifact_path(f"goals/{goal_id}/steps/{step_id}/report.md")
                backend.write(md_path, "\n".join(md_parts))
            except RuntimeError:
                # FrameworkFilesystem not initialized - use direct Path writes
                step_dir = self._run_dir / "goals" / goal_id / "steps" / step_id
                step_dir.mkdir(parents=True, exist_ok=True)

                (step_dir / "report.json").write_text(
                    report.model_dump_json(indent=2), encoding="utf-8"
                )

                md_parts = [
                    f"# Step: {description}\n",
                    f"**Status**: {report.status}  \n**Duration**: {duration_ms}ms\n",
                ]
                if deps:
                    md_parts.append(f"**Depends on**: {', '.join(deps)}\n")
                md_parts.append(f"\n## Result\n\n{result}\n")
                (step_dir / "report.md").write_text("\n".join(md_parts), encoding="utf-8")
            logger.debug(
                "Step report written: goal=%s step=%s status=%s duration=%dms",
                goal_id,
                step_id,
                report.status,
                duration_ms,
            )

    def write_goal_report(self, report: Any) -> None:
        """Write goal report as JSON and Markdown.

        Args:
            report: A ``GoalReport`` instance.
        """
        with self._file_lock:
            goal_dir = self._run_dir / "goals" / report.goal_id
            goal_dir.mkdir(parents=True, exist_ok=True)

            # Build Markdown report
            md_parts = [
                f"# Goal: {report.description}\n",
                f"**Status**: {report.status}  \n**Duration**: {report.duration_ms}ms\n",
                f"\n## Summary\n\n{report.summary}\n",
            ]
            if getattr(report, "reflection_assessment", ""):
                md_parts.append(f"\n## Reflection\n\n{report.reflection_assessment}\n")
            if getattr(report, "cross_validation_notes", ""):
                md_parts.append(f"\n## Cross-Validation\n\n{report.cross_validation_notes}\n")
            step_reports = getattr(report, "step_reports", [])
            if step_reports:
                md_parts.append("\n## Steps\n")
                for sr in step_reports:
                    icon = "+" if sr.status == "completed" else "x"
                    md_parts.append(f"- [{icon}] **{sr.step_id}**: {sr.description} ({sr.status})")
                md_parts.append("")

            # Try FrameworkFilesystem first, fallback to direct Path operations
            try:
                backend = FrameworkFilesystem.get()

                # Write JSON report
                json_path = self._resolve_artifact_path(f"goals/{report.goal_id}/report.json")
                backend.write(json_path, report.model_dump_json(indent=2))

                # Write Markdown report
                md_path = self._resolve_artifact_path(f"goals/{report.goal_id}/report.md")
                backend.write(md_path, "\n".join(md_parts))
            except RuntimeError:
                # FrameworkFilesystem not initialized - use direct Path writes
                (goal_dir / "report.json").write_text(
                    report.model_dump_json(indent=2), encoding="utf-8"
                )
                (goal_dir / "report.md").write_text("\n".join(md_parts), encoding="utf-8")

            step_count = len(getattr(report, "step_reports", []))
            logger.info(
                "Goal report written: goal=%s status=%s steps=%d",
                report.goal_id,
                report.status,
                step_count,
            )

            if report.goal_id not in self._manifest.goals:
                self._manifest.goals.append(report.goal_id)
            self._save_manifest_unlocked()

    def record_artifact(self, entry: ArtifactEntry) -> None:
        """Track an artifact in the manifest.

        Args:
            entry: Artifact metadata to record.
        """
        with self._file_lock:
            self._manifest.artifacts.append(entry)
            logger.debug("Artifact recorded: path=%s source=%s", entry.path, entry.source)
            self._save_manifest_unlocked()

    def save_checkpoint(self, envelope: dict[str, Any]) -> None:
        """Write checkpoint atomically (tmp + rename).

        Args:
            envelope: CheckpointEnvelope data as a dict.
        """
        with self._file_lock:
            # Try FrameworkFilesystem first, fallback to direct Path operations
            try:
                backend = FrameworkFilesystem.get()

                # Write to temp file first
                tmp_path = self._resolve_artifact_path("checkpoint.json.tmp")
                backend.write(tmp_path, json.dumps(envelope, default=str, indent=2))

                # Atomic rename using resolved paths
                try:
                    tmp_resolved = backend._resolve_path(tmp_path)
                    target_path = self._resolve_artifact_path("checkpoint.json")
                    target_resolved = backend._resolve_path(target_path)
                    tmp_resolved.rename(target_resolved)
                    n_completed = len(envelope.get("completed_step_ids", []))
                    logger.debug(
                        "Checkpoint saved: status=%s completed_steps=%d",
                        envelope.get("status"),
                        n_completed,
                    )
                except Exception:
                    logger.debug("Checkpoint write failed", exc_info=True)
                    # Clean up temp file
                    try:
                        tmp_resolved = backend._resolve_path(tmp_path)
                        tmp_resolved.unlink(missing_ok=True)
                    except Exception:
                        logger.debug("Failed to cleanup temp file: %s", tmp_path)
            except RuntimeError:
                # FrameworkFilesystem not initialized - use direct Path writes
                tmp_file = self._run_dir / "checkpoint.json.tmp"
                target_file = self._run_dir / "checkpoint.json"
                try:
                    tmp_file.write_text(
                        json.dumps(envelope, default=str, indent=2), encoding="utf-8"
                    )
                    tmp_file.rename(target_file)
                    logger.debug(
                        "Checkpoint saved via direct Path: status=%s", envelope.get("status")
                    )
                except Exception:
                    logger.debug("Checkpoint write failed", exc_info=True)
                    tmp_file.unlink(missing_ok=True)

    def load_checkpoint(self) -> dict[str, Any] | None:
        """Load checkpoint from disk.

        Returns:
            Parsed checkpoint dict, or None if not found.
        """
        with self._file_lock:
            target = self._run_dir / "checkpoint.json"
            if not target.exists():
                logger.debug("No checkpoint found at %s", target)
                return None
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                logger.debug("Checkpoint read failed", exc_info=True)
                return None
            else:
                logger.debug("Checkpoint loaded: status=%s", data.get("status"))
                return data  # type: ignore[no-any-return]

    def _save_manifest_unlocked(self) -> None:
        """Persist manifest; caller must hold ``self._file_lock``."""
        self._manifest.updated_at = datetime.now(UTC).isoformat()

        # Try FrameworkFilesystem first, fallback to direct Path operations
        try:
            backend = FrameworkFilesystem.get()
            manifest_path = self._resolve_artifact_path("manifest.json")
            backend.write(manifest_path, self._manifest.model_dump_json(indent=2))
        except RuntimeError:
            # FrameworkFilesystem not initialized - use direct Path writes
            manifest_file = self._run_dir / "manifest.json"
            manifest_file.write_text(self._manifest.model_dump_json(indent=2), encoding="utf-8")

        logger.debug(
            "Manifest saved: goals=%d artifacts=%d",
            len(self._manifest.goals),
            len(self._manifest.artifacts),
        )

    def save_manifest(self) -> None:
        """Persist the current manifest to disk."""
        with self._file_lock:
            self._save_manifest_unlocked()

    def load_manifest(self) -> RunManifest | None:
        """Load manifest from disk.

        Returns:
            Parsed RunManifest, or None if not found.
        """
        with self._file_lock:
            target = self._run_dir / "manifest.json"
            if not target.exists():
                return None
            try:
                return RunManifest.model_validate_json(target.read_text(encoding="utf-8"))
            except Exception:
                logger.debug("Manifest read failed", exc_info=True)
                return None

    def update_status(self, status: str) -> None:
        """Update manifest status and save.

        Args:
            status: New status value.
        """
        with self._file_lock:
            old_status = self._manifest.status
            self._manifest.status = status  # type: ignore[assignment]
            logger.info("Run status: %s -> %s", old_status, status)
            self._save_manifest_unlocked()
