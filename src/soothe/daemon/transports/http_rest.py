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
        thread_manager: Optional ThreadContextManager for thread operations (RFC-0017).
    """

    def __init__(
        self,
        config: HttpRestConfig,
        thread_manager: Any | None = None,
        runner: Any | None = None,
        soothe_config: Any | None = None,
    ) -> None:
        """Initialize HTTP REST transport.

        Args:
            config: HTTP REST configuration.
            thread_manager: Optional ThreadContextManager for thread operations.
            runner: Optional SootheRunner instance.
            soothe_config: Optional SootheConfig instance.
        """
        self._config = config
        self._thread_manager = thread_manager
        self._runner = runner
        self._soothe_config = soothe_config
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

        # Thread management (RFC-0017)
        @self._app.get("/api/v1/threads")
        async def list_threads(
            status: str | None = None,
            tags: str | None = None,
            labels: str | None = None,
            priority: str | None = None,
            category: str | None = None,
            created_after: str | None = None,
            created_before: str | None = None,
            updated_after: str | None = None,
            updated_before: str | None = None,
            limit: int = 50,
            offset: int = 0,
            include_stats: bool = False,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """List threads with filtering.

            Query params:
            - status: Filter by status (idle|running|suspended|archived|error)
            - tags: Comma-separated tags
            - labels: Comma-separated labels
            - priority: Filter by priority (low|normal|high)
            - category: Filter by category
            - created_after: ISO 8601 datetime
            - created_before: ISO 8601 datetime
            - updated_after: ISO 8601 datetime
            - updated_before: ISO 8601 datetime
            - limit: Max results (default: 50)
            - offset: Pagination offset
            - include_stats: Include execution stats
            """
            if not self._thread_manager or not self._runner or not self._soothe_config:
                raise HTTPException(status_code=503, detail="Thread management not available")

            from datetime import datetime

            from soothe.core.thread import ThreadFilter

            thread_filter = None
            if any(
                [status, tags, labels, priority, category, created_after, created_before, updated_after, updated_before]
            ):
                thread_filter = ThreadFilter(
                    status=status,
                    tags=tags.split(",") if tags else None,
                    labels=labels.split(",") if labels else None,
                    priority=priority,
                    category=category,
                    created_after=datetime.fromisoformat(created_after) if created_after else None,
                    created_before=datetime.fromisoformat(created_before) if created_before else None,
                    updated_after=datetime.fromisoformat(updated_after) if updated_after else None,
                    updated_before=datetime.fromisoformat(updated_before) if updated_before else None,
                )

            threads = await self._thread_manager.list_threads(
                thread_filter,
                include_stats=include_stats,
                include_last_message=True,
            )

            # Apply pagination
            paginated = threads[offset : offset + limit]

            return {
                "threads": [t.model_dump(mode="json") for t in paginated],
                "total": len(threads),
                "limit": limit,
                "offset": offset,
            }

        @self._app.get("/api/v1/threads/{thread_id}")
        async def get_thread(thread_id: str) -> dict[str, Any]:
            """Get thread details."""
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            try:
                thread = await self._thread_manager.get_thread(thread_id)
                return {"thread": thread.model_dump(mode="json")}
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found") from None

        @self._app.post("/api/v1/threads")
        async def create_thread(request: ThreadCreateRequest) -> dict[str, Any]:
            """Create new thread with optional initial message.

            Request body:
            {
              "initial_message": "Analyze code",  // optional
              "metadata": {                       // optional
                "tags": ["research"],
                "priority": "high",
                "category": "code-review"
              }
            }
            """
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            thread = await self._thread_manager.create_thread(
                initial_message=request.initial_message,
                metadata=request.metadata,
            )

            return {
                "thread_id": thread.thread_id,
                "status": thread.status,
                "created_at": thread.created_at.isoformat(),
            }

        @self._app.delete("/api/v1/threads/{thread_id}")
        async def archive_thread(
            thread_id: str,
            archive: bool = True,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """Delete or archive thread.

            Query params:
            - archive: If true, archive; if false, permanently delete (default: true)
            """
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            try:
                if archive:
                    await self._thread_manager.archive_thread(thread_id)
                    action = "archived"
                else:
                    await self._thread_manager.delete_thread(thread_id)
                    action = "deleted"
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found") from None
            else:
                return {"thread_id": thread_id, "status": action}

        @self._app.post("/api/v1/threads/{thread_id}/resume")
        async def resume_thread(
            thread_id: str,
            request: ThreadResumeRequest,
        ) -> dict[str, Any]:
            """Resume thread with new message.

            Request body:
            {
              "message": "Continue analysis"  // required
            }
            """
            if not self._thread_manager or not self._runner:
                raise HTTPException(status_code=503, detail="Thread management not available")

            # Resume thread context
            await self._thread_manager.resume_thread(thread_id)

            # Send message to daemon for execution
            if self._message_handler:
                self._message_handler(
                    {
                        "type": "resume_thread",
                        "thread_id": thread_id,
                    }
                )
                self._message_handler(
                    {
                        "type": "input",
                        "text": request.message,
                    }
                )

            return {
                "thread_id": thread_id,
                "status": "resumed",
                "message": "Thread resumed and processing message",
            }

        @self._app.get("/api/v1/threads/{thread_id}/messages")
        async def get_thread_messages(
            thread_id: str,
            limit: int = 100,
            offset: int = 0,
        ) -> dict[str, Any]:
            """Get thread conversation messages."""
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            try:
                messages = await self._thread_manager.get_thread_messages(
                    thread_id,
                    limit=limit,
                    offset=offset,
                )
                return {
                    "thread_id": thread_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "limit": limit,
                    "offset": offset,
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found") from None

        @self._app.get("/api/v1/threads/{thread_id}/artifacts")
        async def get_thread_artifacts(thread_id: str) -> dict[str, Any]:
            """Get thread artifacts."""
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            try:
                artifacts = await self._thread_manager.get_thread_artifacts(thread_id)
                return {
                    "thread_id": thread_id,
                    "artifacts": [a.model_dump(mode="json") for a in artifacts],
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found") from None

        @self._app.get("/api/v1/threads/{thread_id}/stats")
        async def get_thread_stats(thread_id: str) -> dict[str, Any]:
            """Get thread execution statistics."""
            if not self._thread_manager:
                raise HTTPException(status_code=503, detail="Thread management not available")

            try:
                stats = await self._thread_manager.get_thread_stats(thread_id)
                return {
                    "thread_id": thread_id,
                    "stats": stats.model_dump(mode="json"),
                }
            except KeyError:
                raise HTTPException(status_code=404, detail="Thread not found") from None

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
            """Request daemon shutdown.

            Note:
                The current transport command bridge routes through `/exit`, whose
                runtime semantics are daemon-lifecycle dependent elsewhere in the
                stack. This endpoint should be treated as a thin compatibility shim
                until the HTTP transport gets a dedicated shutdown command path.
            """
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

    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Note: HTTP REST doesn't maintain persistent connections, so this
        is a no-op. Streaming responses use different mechanisms.

        Args:
            client: Client identifier (not used for HTTP REST)
            message: Message dictionary to send

        Raises:
            NotImplementedError: HTTP REST doesn't support persistent messaging
        """
        # HTTP REST doesn't maintain persistent connections
        # Streaming is handled via SSE endpoints

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
