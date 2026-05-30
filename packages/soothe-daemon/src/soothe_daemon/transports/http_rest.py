"""HTTP REST transport implementation (RFC-0013).

HTTP endpoints for health, status, and auxiliary APIs. Conversation control
uses the WebSocket loop protocol (IG-408); thread CRUD routes are not exposed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from soothe_daemon import __version__
from soothe_daemon.config.models import HttpRestConfig
from soothe_daemon.transports.base import TransportServer


def _get_client_id(request: Request) -> str:
    """Generate client ID from request."""
    client_host = request.client.host if request.client else "unknown"
    return f"http:{client_host}"


logger = logging.getLogger(__name__)

# Pydantic models for request/response validation


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    updates: dict[str, Any]


class HttpRestTransport(TransportServer):
    """HTTP REST transport server.

    This transport implements the RFC-0013 protocol over HTTP REST.
    It provides health, status, and auxiliary routes.

    Args:
        config: HTTP REST configuration.
    """

    def __init__(
        self,
        config: HttpRestConfig,
        runner: Any | None = None,
        soothe_config: Any | None = None,
        session_manager: Any | None = None,
        *,
        unified_app: FastAPI | None = None,
        autopilot_service: Any | None = None,
    ) -> None:
        """Initialize HTTP REST transport.

        Args:
            config: HTTP REST configuration.
            runner: Optional SootheRunner instance.
            soothe_config: Optional SootheConfig instance.
            session_manager: Optional ClientSessionManager for queue metrics.
            unified_app: When set, routes and middleware attach to this shared ASGI app
                and this transport does not start its own uvicorn process.
            autopilot_service: Optional daemon-owned AutopilotService. When
                provided, the ``/api/v1/autopilot/*`` endpoints route through
                it. When ``None``, autopilot endpoints return 503.
        """
        self._config = config
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._autopilot_service = autopilot_service
        self._unified_mode = unified_app is not None
        self._app = unified_app or FastAPI(
            title="Soothe Daemon API",
            description="REST API for Soothe multi-agent assistant",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )
        self._server: Any = None
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._client_count = 0

        self._setup_middleware()
        self._setup_routes()

    def _require_autopilot_service(self) -> Any:
        """Return the daemon-owned AutopilotService or raise HTTP 503."""
        if self._autopilot_service is None:
            raise HTTPException(
                status_code=503,
                detail="Autopilot service unavailable; ensure autopilot is enabled and the daemon started cleanly",
            )
        return self._autopilot_service

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
        async def health_check() -> dict[str, Any]:
            """Health check endpoint with queue metrics (IG-258)."""
            queue_metrics = {}

            # Get event queue depths (if session manager available)
            if self._session_manager and hasattr(self._session_manager, "_sessions"):
                event_queues = []
                for session in self._session_manager._sessions.values():
                    if hasattr(session, "event_queue"):
                        event_queues.append(session.event_queue.qsize())

                if event_queues:
                    queue_metrics["event_queues"] = {
                        "max_depth": max(event_queues),
                        "avg_depth": round(sum(event_queues) / len(event_queues), 2),
                        "clients_near_capacity": sum(
                            1 for d in event_queues if d > 8000
                        ),  # >80% of 10000
                    }

            return {
                "status": "healthy",
                "transport": "http_rest",
                "queues": queue_metrics,
            }

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
            return {"version": __version__, "protocol": "soothe-rest-v1"}

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
        async def shutdown_daemon(http_request: Request) -> dict[str, Any]:
            """Request daemon shutdown.

            Note:
                The current transport command bridge routes through `/exit`, whose
                runtime semantics are daemon-lifecycle dependent elsewhere in the
                stack. This endpoint should be treated as a thin compatibility shim
                until the HTTP transport gets a dedicated shutdown command path.
            """
            if self._message_handler:
                client_id = _get_client_id(http_request)
                self._message_handler(client_id, {"type": "command", "cmd": "/exit"})
            return {"status": "shutting_down"}

        # ----------------------------------------------------------------
        # Autopilot endpoints (RFC-204 / RFC-222)
        # ----------------------------------------------------------------

        @self._app.get("/api/v1/autopilot/status")
        async def autopilot_status() -> dict[str, Any]:
            """Get overall autopilot state."""
            service = self._require_autopilot_service()
            status = service.status()
            return {
                "state": "dreaming" if status.get("dreaming") else "active",
                "running": status.get("running", False),
                "dreaming": status.get("dreaming", False),
                "loop_pool": status.get("loop_pool", {}),
            }

        @self._app.get("/api/v1/autopilot/goals")
        async def autopilot_list_goals() -> dict[str, Any]:
            """List all goals."""
            service = self._require_autopilot_service()
            goals = await service.list_goals()
            return {
                "goals": [g.model_dump(mode="json") for g in goals],
                "source": "autopilot_service",
            }

        @self._app.get("/api/v1/autopilot/goals/{goal_id}")
        async def autopilot_get_goal(goal_id: str) -> dict[str, Any]:
            """Get details for a specific goal."""
            service = self._require_autopilot_service()
            goal = await service.get_goal(goal_id)
            if goal:
                return {"goal": goal.model_dump(mode="json"), "source": "autopilot_service"}
            raise HTTPException(status_code=404, detail="Goal not found")

        @self._app.post("/api/v1/autopilot/submit")
        async def autopilot_submit(request: Request) -> dict[str, Any]:
            """Submit a new task to autopilot.

            Request body:
                {"description": "task text", "priority": 50, "workspace": "/path/to/project"}
            """
            body = await request.json()
            description = body.get("description", "")
            priority = int(body.get("priority", 50))
            workspace_raw = body.get("workspace")
            workspace: str | None = None
            if isinstance(workspace_raw, str) and workspace_raw.strip():
                from soothe.core.workspace import validate_client_workspace

                try:
                    workspace = str(validate_client_workspace(workspace_raw))
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

            if not description:
                raise HTTPException(status_code=400, detail="description is required")

            service = self._require_autopilot_service()
            goal = await service.submit_task(
                description,
                priority=priority,
                workspace=workspace,
            )
            return {
                "status": "submitted",
                "goal_id": goal.id,
            }

        @self._app.delete("/api/v1/autopilot/goals/{goal_id}")
        async def autopilot_cancel_goal(goal_id: str) -> dict[str, Any]:
            """Cancel a goal."""
            service = self._require_autopilot_service()
            cancelled = await service.cancel_goal(goal_id, reason="http_delete")
            if cancelled is None:
                raise HTTPException(status_code=404, detail="Goal not found")
            return {
                "status": "cancelled",
                "goal_id": cancelled.id,
                "new_status": cancelled.status,
            }

        @self._app.post("/api/v1/autopilot/goals/{goal_id}/approve")
        async def autopilot_approve_goal(goal_id: str) -> dict[str, Any]:
            """Approve a MUST-confirmation goal."""
            service = self._require_autopilot_service()
            approved = await service.approve_confirmation(goal_id)
            if approved:
                return {"status": "approved", "goal_id": goal_id}
            raise HTTPException(status_code=404, detail="Confirmation not found")

        @self._app.post("/api/v1/autopilot/goals/{goal_id}/reject")
        async def autopilot_reject_goal(goal_id: str) -> dict[str, Any]:
            """Reject a proposed goal."""
            service = self._require_autopilot_service()
            rejected = await service.reject_confirmation(goal_id)
            if rejected:
                return {"status": "rejected", "goal_id": goal_id}
            raise HTTPException(status_code=404, detail="Confirmation not found")

        @self._app.post("/api/v1/autopilot/wake")
        async def autopilot_wake() -> dict[str, Any]:
            """Exit dreaming mode — resume active execution."""
            service = self._require_autopilot_service()
            await service.wake_from_dreaming(trigger="wake_signal")
            return {"status": "wake_sent"}

        @self._app.post("/api/v1/autopilot/dream")
        async def autopilot_dream() -> dict[str, Any]:
            """Force enter dreaming mode."""
            service = self._require_autopilot_service()
            await service.force_dream()
            return {"status": "dream_sent"}

    async def start(
        self,
        message_handler: Callable[[str, dict[str, Any]], None],
        _handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None,
    ) -> None:
        """Start the HTTP REST server.

        Args:
            message_handler: Callback to handle incoming messages. Takes (client_id, message).
            _handshake_callback: Optional callback for initial handshake messages (not used for HTTP).
        """
        if not self._config.enabled:
            logger.info("HTTP REST transport disabled by configuration")
            return

        self._message_handler = message_handler
        # HTTP REST doesn't need handshake callback - each request is independent

        if self._unified_mode:
            logger.debug("HTTP REST routes attached to unified ASGI app (no standalone listener)")
            return

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
