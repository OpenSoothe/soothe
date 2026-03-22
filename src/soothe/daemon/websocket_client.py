"""WebSocket client for daemon connections (RFC-0013)."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

import websockets.asyncio.client
import websockets.exceptions

from soothe.daemon.protocol import decode, encode

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for connecting to the daemon.

    This client connects to the daemon via WebSocket and supports
    the same interface as the Unix socket client.

    Args:
        url: WebSocket URL (e.g., "ws://localhost:8765").
        token: Optional authentication token.
    """

    def __init__(self, url: str = "ws://localhost:8765", token: str | None = None) -> None:
        """Initialize WebSocket client.

        Args:
            url: WebSocket URL.
            token: Optional authentication token.
        """
        self._url = url
        self._token = token
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to the daemon.

        Raises:
            ConnectionError: If connection fails.
        """
        try:
            self._ws = await websockets.asyncio.client.connect(self._url)
            self._connected = True

            # Send auth message if token provided
            if self._token:
                auth_msg = {"type": "auth", "token": self._token}
                await self._ws.send(encode(auth_msg).decode("utf-8").strip())

                # Wait for auth response
                response = await self._ws.recv()
                if isinstance(response, bytes):
                    response = response.decode("utf-8")
                auth_response = decode(response.encode("utf-8"))

                if not auth_response or not auth_response.get("success"):
                    await self.close()
                    raise ConnectionError("Authentication failed")

            logger.info("Connected to daemon via WebSocket at %s", self._url)
        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to daemon: {e}"
            raise ConnectionError(msg) from e

    async def close(self) -> None:
        """Close the connection."""
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
            self._connected = False

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the daemon.

        Args:
            message: Message dict to send.

        Raises:
            ConnectionError: If not connected or send fails.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to daemon")

        try:
            data = encode(message)
            # Remove newline for WebSocket (native framing)
            data = data.rstrip(b"\n")
            await self._ws.send(data.decode("utf-8"))
        except websockets.exceptions.ConnectionClosed as e:
            self._connected = False
            raise ConnectionError("Connection closed") from e
        except Exception as e:
            msg = f"Failed to send message: {e}"
            raise ConnectionError(msg) from e

    async def receive(self) -> AsyncGenerator[dict[str, Any]]:
        """Receive messages from the daemon.

        Yields:
            Message dicts received from the daemon.

        Raises:
            ConnectionError: If not connected or receive fails.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to daemon")

        try:
            async for message in self._ws:
                try:
                    message_str = message.decode("utf-8") if isinstance(message, bytes) else message
                    msg_dict = decode(message_str.encode("utf-8"))
                    if msg_dict:
                        yield msg_dict
                except Exception:
                    logger.exception("Error parsing message")
                    continue
        except websockets.exceptions.ConnectionClosed:
            self._connected = False
        except Exception as e:
            self._connected = False
            msg = f"Connection error: {e}"
            raise ConnectionError(msg) from e

    @property
    def is_connected(self) -> bool:
        """Check if connected to the daemon.

        Returns:
            True if connected, False otherwise.
        """
        return self._connected

    # Convenience methods matching DaemonClient interface

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
        await self.send(payload)

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon.

        Args:
            cmd: Command string.
        """
        await self.send({"type": "command", "cmd": cmd})

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self.send({"type": "detach"})

    async def send_resume_thread(self, thread_id: str) -> None:
        """Request the daemon to resume a specific thread.

        Args:
            thread_id: The thread ID to resume.
        """
        await self.send({"type": "resume_thread", "thread_id": thread_id})

    async def send_new_thread(self) -> None:
        """Request the daemon to start a new thread."""
        await self.send({"type": "new_thread"})

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if not self._ws or not self._connected:
            return None

        try:
            message = await self._ws.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            return decode(message.encode("utf-8"))
        except websockets.exceptions.ConnectionClosed:
            return None
        except Exception:
            logger.exception("Error reading event")
            return None
