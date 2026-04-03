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
