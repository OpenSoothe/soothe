"""Async client for connecting to SootheDaemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any, Literal

from soothe.daemon.paths import socket_path
from soothe.daemon.protocol import decode, encode

# Type alias for verbosity levels (RFC-0015, RFC-0022)
VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]

logger = logging.getLogger(__name__)


class DaemonClient:
    """Async client for connecting to a running SootheDaemon.

    Args:
        sock: Path to the Unix socket.
    """

    def __init__(self, sock: Path | None = None) -> None:
        """Initialize the daemon client.

        Args:
            sock: Path to the Unix socket.
        """
        self._sock = sock or socket_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Open a connection to the daemon."""
        # Set limit to 10MB to handle large events (e.g., search results)
        self._reader, self._writer = await asyncio.open_unix_connection(str(self._sock), limit=10 * 1024 * 1024)

    async def close(self) -> None:
        """Close the connection."""
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def send_input(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
    ) -> None:
        """Send user input to the daemon.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
        """
        payload: dict[str, Any] = {"type": "input", "text": text}
        if autonomous:
            payload["autonomous"] = True
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
        if subagent is not None:
            payload["subagent"] = subagent
        await self._send(payload)

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon."""
        await self._send({"type": "command", "cmd": cmd})

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self._send({"type": "detach"})

    async def send_resume_thread(self, thread_id: str) -> None:
        """Request the daemon to resume a specific thread.

        Args:
            thread_id: The thread ID to resume.
        """
        await self._send({"type": "resume_thread", "thread_id": thread_id})

    async def send_new_thread(self) -> None:
        """Request the daemon to start a new thread."""
        await self._send({"type": "new_thread"})

    async def subscribe_thread(
        self,
        thread_id: str,
        verbosity: VerbosityLevel = "normal",
    ) -> None:
        """Subscribe to receive events for a thread.

        Args:
            thread_id: Thread identifier to subscribe to
            verbosity: Verbosity preference (quiet|minimal|normal|detailed|debug)

        Raises:
            ConnectionError: If not connected
        """
        if not self._writer:
            raise ConnectionError("Not connected to daemon")

        msg = {
            "type": "subscribe_thread",
            "thread_id": thread_id,
            "verbosity": verbosity,
        }
        await self._send(msg)
        logger.info("Subscribed to thread %s with verbosity=%s", thread_id, verbosity)

    async def wait_for_subscription_confirmed(
        self,
        thread_id: str,
        verbosity: VerbosityLevel = "normal",
        timeout: float = 5.0,  # noqa: ASYNC109
    ) -> None:
        """Wait for subscription confirmation message.

        Args:
            thread_id: Expected thread ID
            verbosity: Expected verbosity level
            timeout: Maximum seconds to wait

        Raises:
            TimeoutError: If confirmation not received
            ValueError: If confirmation has different thread_id or verbosity
        """
        async with asyncio.timeout(timeout):
            event = await self.read_event()

        if not event:
            raise ValueError("No event received")

        if event.get("type") != "subscription_confirmed":
            msg = f"Expected subscription_confirmed, got {event.get('type')}"
            raise ValueError(msg)

        if event.get("thread_id") != thread_id:
            msg = f"Subscription thread_id mismatch: expected {thread_id}, got {event.get('thread_id')}"
            raise ValueError(msg)

        echoed_verbosity = event.get("verbosity", "normal")
        if echoed_verbosity != verbosity:
            logger.warning(
                "Verbosity mismatch: requested=%s, received=%s",
                verbosity,
                echoed_verbosity,
            )

        logger.debug("Subscription confirmed for thread %s with verbosity=%s", thread_id, echoed_verbosity)

    # Thread management methods (RFC-0017)

    async def send_thread_list(
        self,
        thread_filter: dict[str, Any] | None = None,
        *,
        include_stats: bool = False,
    ) -> None:
        """Request list of threads with optional filtering.

        Args:
            thread_filter: Optional filter criteria (status, tags, labels, etc.)
            include_stats: Whether to include execution statistics
        """
        msg: dict[str, Any] = {"type": "thread_list", "include_stats": include_stats}
        if thread_filter:
            msg["filter"] = thread_filter
        await self._send(msg)

    async def send_thread_create(
        self,
        initial_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create a new thread.

        Args:
            initial_message: Optional initial message for the thread
            metadata: Optional thread metadata (tags, labels, priority, etc.)
        """
        msg: dict[str, Any] = {"type": "thread_create"}
        if initial_message:
            msg["initial_message"] = initial_message
        if metadata:
            msg["metadata"] = metadata
        await self._send(msg)

    async def send_thread_get(self, thread_id: str) -> None:
        """Get details for a specific thread.

        Args:
            thread_id: Thread ID to retrieve
        """
        await self._send({"type": "thread_get", "thread_id": thread_id})

    async def send_thread_archive(self, thread_id: str) -> None:
        """Archive a thread.

        Args:
            thread_id: Thread ID to archive
        """
        await self._send({"type": "thread_archive", "thread_id": thread_id})

    async def send_thread_delete(self, thread_id: str) -> None:
        """Permanently delete a thread.

        Args:
            thread_id: Thread ID to delete
        """
        await self._send({"type": "thread_delete", "thread_id": thread_id})

    async def send_thread_messages(
        self,
        thread_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> None:
        """Get conversation messages for a thread.

        Args:
            thread_id: Thread ID
            limit: Maximum number of messages to return
            offset: Pagination offset
        """
        await self._send(
            {
                "type": "thread_messages",
                "thread_id": thread_id,
                "limit": limit,
                "offset": offset,
            }
        )

    async def send_thread_artifacts(self, thread_id: str) -> None:
        """Get artifacts for a thread.

        Args:
            thread_id: Thread ID
        """
        await self._send({"type": "thread_artifacts", "thread_id": thread_id})

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.

        Raises:
            asyncio.CancelledError: If the read operation was cancelled.
        """
        if not self._reader:
            return None
        try:
            line = await self._reader.readline()
            if not line:
                return None
            return decode(line)
        except asyncio.CancelledError:
            # Re-raise CancelledError so asyncio.wait_for() can handle timeouts properly
            raise
        except ConnectionError:
            return None

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._writer:
            return
        self._writer.write(encode(msg))
        await self._writer.drain()
