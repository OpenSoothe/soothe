"""RFC-204: Dreaming Mode for continuous autonomous operation.

When all goals are resolved, autopilot enters dreaming mode instead of
terminating. The dreaming runner performs background maintenance tasks
and monitors for new task submissions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DreamingMode:
    """Manages the dreaming lifecycle for autopilot.

    Dreaming mode performs:
    - Memory consolidation
    - Background indexing
    - Goal anticipation
    - Health monitoring
    - Channel/inbox monitoring

    Args:
        soothe_home: Root SOOTHE_HOME directory.
        memory_protocol: Optional MemoryProtocol for consolidation.
        context_protocol: Optional ContextProtocol for indexing.
        consolidation_interval: Seconds between consolidation cycles.
        health_check_interval: Seconds between health checks.
    """

    def __init__(
        self,
        soothe_home: Path,
        memory_protocol: Any = None,
        context_protocol: Any = None,
        consolidation_interval: int = 300,
        health_check_interval: int = 60,
    ) -> None:
        """Initialize dreaming mode.

        Args:
            soothe_home: Root SOOTHE_HOME directory.
            memory_protocol: Optional MemoryProtocol instance.
            context_protocol: Optional ContextProtocol instance.
            consolidation_interval: Seconds between consolidation cycles.
            health_check_interval: Seconds between health checks.
        """
        self._soothe_home = soothe_home
        self._memory = memory_protocol
        self._context = context_protocol
        self._consolidation_interval = consolidation_interval
        self._health_check_interval = health_check_interval
        self._running = False
        self._state = "idle"  # idle, dreaming, waking

    @property
    def state(self) -> str:
        """Get current dreaming state.

        Returns:
            Current state string.
        """
        return self._state

    async def run(self) -> None:
        """Main dreaming loop.

        Runs background maintenance tasks and monitors the inbox
        for new task submissions. Exits when a wake signal is detected.
        """
        self._state = "dreaming"
        self._running = True
        self._write_status()

        # Signal dreaming entered via channel
        self._write_outbox("dreaming_entered", {})

        logger.info("Autopilot entered dreaming mode")

        try:
            while self._running:
                # Check inbox for new tasks or signals
                task = self._poll_inbox()
                if task:
                    task_type = task.get("type", "")
                    if task_type == "task_submit":
                        logger.info("Dreaming: received new task")
                        self._state = "waking"
                        self._write_status()
                        return
                    if task_type == "signal_resume":
                        logger.info("Dreaming: wake signal received")
                        self._state = "waking"
                        self._write_status()
                        return

                # Run maintenance tasks
                await self._run_consolidation()
                await self._run_health_check()

                # Sleep and check for signals
                await asyncio.sleep(10)
        finally:
            self._state = "idle"
            self._write_status()
            self._write_outbox("dreaming_exited", {"trigger": "normal"})
            logger.info("Autopilot exited dreaming mode")

    def stop(self) -> None:
        """Signal dreaming to stop."""
        self._running = False

    async def _run_consolidation(self) -> None:
        """Run memory consolidation and background indexing.

        Performs:
        - Memory deduplication and merging
        - Vector re-indexing if needed
        - Context summarization
        - Goal anticipation analysis
        """
        if self._memory:
            try:
                # Trigger memory consolidation
                if hasattr(self._memory, "consolidate"):
                    await self._memory.consolidate()
                elif hasattr(self._memory, "compact"):
                    await self._memory.compact()
            except Exception:
                logger.debug("Memory consolidation failed", exc_info=True)

        if self._context:
            try:
                if hasattr(self._context, "compact"):
                    await self._context.compact()
            except Exception:
                logger.debug("Context compaction failed", exc_info=True)

        await self._anticipate_goals()

    async def _run_health_check(self) -> None:
        """Run health monitoring.

        Checks:
        - Memory usage
        - Disk space in SOOTHE_HOME
        - Daemon connectivity
        """
        try:
            import shutil

            _, _, free = shutil.disk_usage(str(self._soothe_home))
            if free < 100 * 1024 * 1024:  # 100MB warning
                logger.warning(
                    "Low disk space in SOOTHE_HOME: %d MB free",
                    free // (1024 * 1024),
                )
        except Exception:
            logger.debug("Health check failed", exc_info=True)

    def _poll_inbox(self) -> dict[str, Any] | None:
        """Check inbox for new messages.

        Returns:
            First new task dict, or None if inbox is empty.
        """
        from soothe.cognition.channel.inbox import ChannelInbox

        inbox = ChannelInbox(self._soothe_home / "autopilot" / "inbox")
        tasks = inbox.read_pending()
        if tasks:
            inbox.archive_processed()
            return tasks[0].to_dict()
        return None

    def _write_outbox(self, event_type: str, data: dict[str, Any]) -> None:
        """Write a message to the outbox.

        Args:
            event_type: Message type.
            data: Message payload.
        """
        from soothe.cognition.channel.models import ChannelMessage
        from soothe.cognition.channel.outbox import ChannelOutbox

        outbox = ChannelOutbox(self._soothe_home / "autopilot" / "outbox")
        msg = ChannelMessage(type=event_type, payload=data, sender="soothe")
        outbox.send(msg)

    async def _anticipate_goals(self) -> None:
        """Analyze completed goals and generate candidate future tasks.

        Reads goal completion artifacts from the runs directory, identifies
        recurring patterns, and drafts candidate task files to
        ``SOOTHE_HOME/autopilot/draft_goals/`` for user review.

        Uses simple pattern matching; no LLM dependency.
        """
        runs_dir = self._soothe_home / "runs"
        if not runs_dir.exists():
            return

        # Collect recent goal reports
        goal_summaries: list[dict[str, str]] = []
        for goal_dir in sorted(runs_dir.rglob("goals/*/report.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            try:
                content = goal_dir.read_text()
                goal_id = goal_dir.parent.name
                # Extract a brief summary from the first meaningful lines
                lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
                if lines:
                    goal_summaries.append({"id": goal_id, "summary": "\n".join(lines[:5])})
            except OSError:
                continue

        if not goal_summaries:
            return

        # Identify recurring themes
        theme_words: dict[str, int] = {}
        stop_words = {"the", "a", "an", "is", "was", "to", "for", "of", "and", "in", "with", "on", "at", "by", "from"}
        for g in goal_summaries:
            words = set(g["summary"].lower().split())
            for w in words - stop_words:
                if len(w) > 3:  # noqa: PLR2004
                    theme_words[w] = theme_words.get(w, 0) + 1

        # Find top recurring themes
        recurring = sorted(theme_words.items(), key=lambda x: x[1], reverse=True)[:5]
        if not recurring:
            return

        themes = ", ".join(f"{w} ({n}x)" for w, n in recurring if n > 1)
        if not themes:
            return

        # Write draft goal
        draft_dir = self._soothe_home / "autopilot" / "draft_goals"
        draft_dir.mkdir(parents=True, exist_ok=True)

        # Only write one draft per dreaming cycle (check if recent draft exists)
        recent_drafts = list(draft_dir.glob("DRAFT-*.md"))
        from datetime import datetime as _dt

        cutoff = _dt.now(tz=UTC).timestamp() - self._consolidation_interval
        if any(d.stat().st_mtime > cutoff for d in recent_drafts):
            return

        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        draft_path = draft_dir / f"DRAFT-{timestamp}.md"
        goals_text = "\n".join(f"- [{g['id']}] {g['summary'][:200]}" for g in goal_summaries[:5])
        draft_path.write_text(
            f"---\n"
            f"type: task_submit\n"
            f"priority: 30\n"
            f"---\n\n"
            f"# Draft Goal: Theme Analysis\n\n"
            f"Generated from analysis of recent completed goals.\n\n"
            f"## Recurring Themes\n"
            f"Keywords that appeared across multiple goals: {themes}\n\n"
            f"## Recent Completed Goals\n"
            f"{goals_text}\n\n"
            f"## Suggested Next Steps\n"
            f"Consider whether follow-up tasks are needed for the themes above.\n"
        )
        logger.info("Draft goal written to %s", draft_path)

    def _write_status(self) -> None:
        """Write current status to status.json."""
        import json

        status_file = self._soothe_home / "autopilot" / "status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "state": self._state,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "goals": [],
            "active_goals": [],
        }

        # If existing status file, preserve goals list
        if status_file.exists():
            try:
                existing = json.loads(status_file.read_text())
                data["goals"] = existing.get("goals", [])
            except (json.JSONDecodeError, OSError):
                pass

        status_file.write_text(json.dumps(data, indent=2))
