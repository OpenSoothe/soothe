"""Abstract base classes for transport implementations (RFC-0013)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from typing import Any


class TransportServer(ABC):
    """Abstract base class for transport servers.

    A transport server handles incoming connections from clients and
    broadcasts messages to all connected clients.

    Each transport implementation (Unix socket, WebSocket, HTTP REST)
    must implement this interface.
    """

    @abstractmethod
    async def start(self, message_handler: Callable[[dict[str, Any]], None]) -> None:
        """Start the transport server and begin accepting connections.

        Args:
            message_handler: Callback function to handle incoming messages
                from clients. The handler receives a decoded message dict.
        """

    @abstractmethod
    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients.

        Used for events without thread_id that should reach all clients.

        Args:
            message: Message dict to broadcast to all clients.
        """

    @abstractmethod
    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Args:
            client: Transport-specific client object
            message: Message dictionary to send

        Raises:
            ConnectionError: If client connection is broken
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the server and close all client connections.

        This method should:
        1. Stop accepting new connections
        2. Close all existing client connections
        3. Release all resources (sockets, file descriptors, etc.)
        """

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Return transport type identifier.

        Returns:
            Transport type string (e.g., "unix_socket", "websocket", "http_rest").
        """

    @property
    @abstractmethod
    def client_count(self) -> int:
        """Return the number of currently connected clients.

        Returns:
            Number of active client connections.
        """


class TransportClient(ABC):
    """Abstract base class for transport clients.

    A transport client connects to a daemon server and exchanges
    messages over a persistent connection.

    Each transport implementation (Unix socket, WebSocket) must
    implement this interface.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the server.

        Raises:
            ConnectionError: If connection fails.
        """

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the server.

        Args:
            message: Message dict to send.

        Raises:
            ConnectionError: If not connected or send fails.
        """

    @abstractmethod
    async def receive(self) -> AsyncGenerator[dict[str, Any]]:
        """Receive messages from the server.

        Yields:
            Message dicts received from the server.

        Raises:
            ConnectionError: If not connected or receive fails.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the connection to the server.

        This method should release all resources and close the connection
        gracefully.
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected to the server.

        Returns:
            True if connected, False otherwise.
        """
