"""HTTP REST transport implementation (RFC-0013).

This transport implements REST API endpoints for thread management,
configuration, file operations, and system status.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from soothe.config.daemon_config import HttpRestConfig
from soothe.daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)

# Pydantic models for request/response validation


class ThreadCreateRequest(BaseModel):
    """Thread creation request."""

    initial_message: str | None = None
    metadata: dict[str, Any] | None = None


class ThreadResumeRequest(BaseModel):
    """Thread resume request."""

    message: str


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    updates: dict[str, Any]


class HttpRestTransport(TransportServer):
    """HTTP REST transport server.

    This transport implements the RFC-0013 protocol over HTTP REST.
    It provides CRUD operations for threads, configuration, and files.

    Args:
        config: HTTP REST configuration.
    """

    def __init__(self, config: HttpRestConfig) -> None:
        """Initialize HTTP REST transport.

        Args:
            config: HTTP REST configuration.
        """
        self._config = config
        self._app = FastAPI(
            title="Soothe Daemon API",
            description="REST API for Soothe multi-agent assistant",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )
        self._server: Any = None
        self._message_handler: Callable[[dict[str, Any]], None] | None = None
        self._client_count = 0

        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self) -> None:
        """Setup CORS middleware."""
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=self._config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self) -> None:
        """Setup all REST API routes."""

        @self._app.get("/api/v1/health")
        async def health_check() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "healthy", "transport": "http_rest"}

        @self._app.get("/api/v1/status")
        async def get_status() -> dict[str, Any]:
            """Get daemon status."""
            return {
                "status": "running",
                "transport": "http_rest",
                "client_count": self._client_count,
            }

        @self._app.get("/api/v1/version")
        async def get_version() -> dict[str, str]:
            """Get daemon version."""
            return {"version": "1.0.0", "protocol": "RFC-0013"}

        # Thread management
        @self._app.get("/api/v1/threads")
        async def list_threads() -> dict[str, Any]:
            """List all threads."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            return {"threads": [], "total": 0}

        @self._app.get("/api/v1/threads/{thread_id}")
        async def get_thread(thread_id: str) -> dict[str, Any]:
            """Get thread details."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            _ = thread_id  # Unused for now
            raise HTTPException(status_code=404, detail="Thread not found")

        @self._app.post("/api/v1/threads")
        async def create_thread(_request: ThreadCreateRequest) -> dict[str, Any]:
            """Create a new thread."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            return {"thread_id": "thread_001", "status": "created"}

        @self._app.delete("/api/v1/threads/{thread_id}")
        async def archive_thread(thread_id: str) -> dict[str, Any]:
            """Archive a thread."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            return {"thread_id": thread_id, "status": "archived"}

        @self._app.post("/api/v1/threads/{thread_id}/resume")
        async def resume_thread(thread_id: str, request: ThreadResumeRequest) -> dict[str, Any]:
            """Resume a thread with a new message."""
            if self._message_handler:
                msg = {
                    "type": "resume_thread",
                    "thread_id": thread_id,
                    "text": request.message,
                }
                self._message_handler(msg)
            return {"thread_id": thread_id, "status": "resumed"}

        @self._app.get("/api/v1/threads/{thread_id}/messages")
        async def get_thread_messages(thread_id: str) -> dict[str, Any]:
            """Get thread messages."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            return {"thread_id": thread_id, "messages": []}

        @self._app.get("/api/v1/threads/{thread_id}/artifacts")
        async def get_thread_artifacts(thread_id: str) -> dict[str, Any]:
            """Get thread artifacts."""
            # NOTE: Placeholder implementation - thread storage not yet implemented
            return {"thread_id": thread_id, "artifacts": []}

        # Configuration
        @self._app.get("/api/v1/config")
        async def get_config() -> dict[str, Any]:
            """Get current configuration."""
            # NOTE: Placeholder implementation - config API not yet implemented
            return {"config": {}}

        @self._app.put("/api/v1/config")
        async def update_config(request: ConfigUpdateRequest) -> dict[str, Any]:
            """Update configuration."""
            # NOTE: Placeholder implementation - config API not yet implemented
            return {"status": "updated", "updates": request.updates}

        @self._app.get("/api/v1/config/schema")
        async def get_config_schema() -> dict[str, Any]:
            """Get configuration schema."""
            # NOTE: Placeholder implementation - config API not yet implemented
            return {"schema": {}}

        # File operations
        @self._app.post("/api/v1/files/upload")
        async def upload_file(_request: Request) -> dict[str, Any]:
            """Upload a file."""
            # NOTE: Placeholder implementation - file storage not yet implemented
            return {"file_id": "file_001", "status": "uploaded"}

        @self._app.get("/api/v1/files/{file_id}")
        async def download_file(file_id: str) -> dict[str, Any]:
            """Download a file."""
            # NOTE: Placeholder implementation - file storage not yet implemented
            _ = file_id  # Unused for now
            raise HTTPException(status_code=404, detail="File not found")

        @self._app.delete("/api/v1/files/{file_id}")
        async def delete_file(file_id: str) -> dict[str, Any]:
            """Delete a file."""
            # NOTE: Placeholder implementation - file storage not yet implemented
            return {"file_id": file_id, "status": "deleted"}

        # System shutdown
        @self._app.post("/api/v1/system/shutdown")
        async def shutdown_daemon() -> dict[str, Any]:
            """Shutdown the daemon."""
            if self._message_handler:
                self._message_handler({"type": "command", "cmd": "/exit"})
            return {"status": "shutting_down"}

    async def start(self, message_handler: Callable[[dict[str, Any]], None]) -> None:
        """Start the HTTP REST server.

        Args:
            message_handler: Callback to handle incoming messages.
        """
        if not self._config.enabled:
            logger.info("HTTP REST transport disabled by configuration")
            return

        self._message_handler = message_handler

        # Import uvicorn here to avoid import errors if not installed
        import uvicorn

        # Configure SSL
        ssl_keyfile = None
        ssl_certfile = None
        if self._config.tls_enabled and self._config.tls_cert and self._config.tls_key:
            ssl_certfile = self._config.tls_cert
            ssl_keyfile = self._config.tls_key

        # Start server in background
        config = uvicorn.Config(
            app=self._app,
            host=self._config.host,
            port=self._config.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        # Run server in background task
        task = asyncio.create_task(self._server.serve())
        _ = task  # Suppress RUF006 warning - we intentionally don't track the task

        protocol = "https" if self._config.tls_enabled else "http"
        logger.info(
            "HTTP REST transport listening on %s://%s:%d",
            protocol,
            self._config.host,
            self._config.port,
        )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients.

        Note: HTTP REST doesn't maintain persistent connections,
        so this is a no-op for this transport.

        Args:
            message: Message dict to broadcast.
        """
        # HTTP REST doesn't maintain persistent connections for broadcasting

    async def stop(self) -> None:
        """Stop the HTTP REST server."""
        if self._server:
            self._server.should_exit = True
            await asyncio.sleep(0.5)  # Give server time to shutdown
            self._server = None

        logger.info("HTTP REST transport stopped")

    @property
    def transport_type(self) -> str:
        """Return transport type identifier."""
        return "http_rest"

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        # HTTP REST doesn't maintain persistent connections
        return self._client_count
