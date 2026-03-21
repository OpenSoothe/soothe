"""Async client for connecting to SootheDaemon."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from soothe.cli.daemon.paths import socket_path
from soothe.cli.daemon.protocol import decode, encode


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

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if not self._reader:
            return None
        try:
            line = await self._reader.readline()
            if not line:
                return None
            return decode(line)
        except (asyncio.CancelledError, ConnectionError):
            return None

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._writer:
            return
        self._writer.write(encode(msg))
        await self._writer.drain()
