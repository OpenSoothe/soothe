"""Unix domain socket transport implementation (RFC-0013).

This transport wraps the existing Unix socket functionality to provide
backward-compatible IPC for local clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soothe.config.daemon_config import UnixSocketConfig
from soothe.daemon.protocol import decode, encode
from soothe.daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)


@dataclass
class _ClientConn:
    """Internal client connection state."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    client_id: str | None = None  # Set by session manager


class UnixSocketTransport(TransportServer):
    """Unix domain socket transport server.

    This transport implements the RFC-0013 protocol over Unix domain sockets.
    It uses newline-delimited JSON (JSONL) framing.

    Args:
        config: Unix socket configuration.
    """

    def __init__(self, config: UnixSocketConfig) -> None:
        """Initialize Unix socket transport.

        Args:
            config: Unix socket configuration.
        """
        self._config = config
        self._server: asyncio.AbstractServer | None = None
        self._clients: list[_ClientConn] = []
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._session_manager: Any = None  # Set by daemon

    async def start(self, message_handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Start the Unix socket server.

        Args:
            message_handler: Callback to handle incoming messages.
                Takes (client_id, message) as arguments.
        """
        if not self._config.enabled:
            logger.info("Unix socket transport disabled by configuration")
            return

        self._message_handler = message_handler
        sock_path = Path(self._config.path).expanduser()  # noqa: ASYNC240
        # Sync operations before async context are acceptable for initialization
        sock_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale socket file if it exists
        if sock_path.exists():
            # Check if socket is live
            if await self._is_socket_live(sock_path):
                msg = f"Another daemon is already listening on {sock_path}"
                raise RuntimeError(msg)
            sock_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(sock_path),
            limit=10 * 1024 * 1024,  # 10MB limit for large events
        )

        # Set socket permissions (user read/write only)
        sock_path.chmod(0o600)

        logger.info("Unix socket transport listening on %s", sock_path)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients.

        Args:
            message: Message dict to broadcast.
        """
        if not self._server:
            logger.warning("Unix socket server is None, cannot broadcast")
            return

        data = encode(message)
        dead_clients: list[_ClientConn] = []

        logger.debug("Unix socket broadcasting to %d clients", len(self._clients))
        for client in self._clients:
            try:
                client.writer.write(data)
                await client.writer.drain()
            except Exception as e:
                logger.warning("Failed to write to Unix socket client: %s", e, exc_info=True)
                dead_clients.append(client)

        # Remove dead clients (safe removal in case already removed)
        for dead in dead_clients:
            with contextlib.suppress(ValueError):
                self._clients.remove(dead)

    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Args:
            client: Client connection object (_ClientConn)
            message: Message dictionary to send

        Raises:
            ConnectionError: If write fails
        """
        if not isinstance(client, _ClientConn):
            msg = f"Expected _ClientConn, got {type(client).__name__}"
            raise TypeError(msg)

        try:
            data = encode(message)
            client.writer.write(data)
            await client.writer.drain()
        except Exception as e:
            logger.exception("Failed to send to Unix socket client")
            msg = f"Failed to send: {e}"
            raise ConnectionError(msg) from e

    async def stop(self) -> None:
        """Stop the Unix socket server and close all connections."""
        if not self._server:
            return

        # Close all client connections
        for client in self._clients:
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception:  # noqa: S110
                pass  # Best effort cleanup

        self._clients.clear()

        # Close server
        self._server.close()
        await self._server.wait_closed()
        self._server = None

        # Clean up socket file
        sock_path = Path(self._config.path).expanduser()  # noqa: ASYNC240
        # Synchronous file operations for cleanup are acceptable
        if sock_path.exists():
            sock_path.unlink()

        logger.info("Unix socket transport stopped")

    @property
    def transport_type(self) -> str:
        """Return transport type identifier."""
        return "unix_socket"

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        return len(self._clients)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new client connection.

        Args:
            reader: Stream reader for the client.
            writer: Stream writer for the client.
        """
        client = _ClientConn(reader=reader, writer=writer)
        self._clients.append(client)

        # Session manager should be set by daemon before start
        # For now, we'll handle it in the message flow
        logger.info("Unix socket client connected (total=%d)", len(self._clients))

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                msg = decode(line)
                if msg is None:
                    continue

                # Pass message to handler with client_id
                # For initial implementation, client_id will be set after first message
                if self._message_handler:
                    try:
                        client_id = client.client_id or "pending"
                        self._message_handler(client_id, msg)
                    except Exception:
                        logger.exception("Error handling Unix socket message")

        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            # Safe removal in case client was already removed during broadcast
            with contextlib.suppress(ValueError):
                self._clients.remove(client)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: S110
                pass  # Best effort cleanup
            logger.info("Unix socket client disconnected (total=%d)", len(self._clients))

    @staticmethod
    async def _is_socket_live(sock_path: Path) -> bool:
        """Check if a Unix socket is accepting connections.

        Args:
            sock_path: Path to the socket file.

        Returns:
            True if socket is live, False otherwise.
        """
        import socket as sock_mod

        try:
            s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(str(sock_path))
            s.close()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            return False
        else:
            return True
