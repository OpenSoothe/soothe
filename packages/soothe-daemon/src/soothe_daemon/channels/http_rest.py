"""HTTP REST channel implementation (RFC-620).

HTTP REST channel for health checks, status, and autopilot endpoints.
Note: This channel only supports inbound (supports_outbound=False).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from soothe_daemon import __version__
from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config.models import HttpRestConfig

logger = logging.getLogger(__name__)


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    updates: dict[str, Any]


class HttpRestChannel(Channel):
    """HTTP REST channel for health checks and REST API.

    This channel implements the RFC-620 Channel interface for HTTP REST.
    It supports:
    - Inbound requests only (supports_inbound=True, supports_outbound=False)
    - Health check endpoints
    - Autopilot REST API

    Args:
        config: HTTP REST configuration.
        manager: ChannelManager for inbound routing.
        runner: Optional SootheRunner instance.
        soothe_config: Optional SootheConfig instance.
        session_manager: Optional ClientSessionManager for queue metrics.
        unified_app: Optional shared FastAPI app.
        autopilot_service: Optional AutopilotService for autopilot endpoints.
    """

    name = "http_rest"
    display_name = "HTTP REST"
    supports_inbound = True
    supports_outbound = False  # HTTP REST doesn't push to clients
    supports_streaming = False

    def __init__(
        self,
        config: HttpRestConfig,
        manager: Any,
        *,
        runner: Any | None = None,
        soothe_config: Any | None = None,
        session_manager: Any | None = None,
        unified_app: FastAPI | None = None,
        autopilot_service: Any | None = None,
    ) -> None:
        """Initialize HTTP REST channel.

        Args:
            config: HTTP REST configuration.
            manager: ChannelManager for inbound routing.
            runner: Optional SootheRunner instance.
            soothe_config: Optional SootheConfig instance.
            session_manager: Optional ClientSessionManager.
            unified_app: Optional shared FastAPI app.
            autopilot_service: Optional AutopilotService.
        """
        super().__init__(config, manager)
        self._http_config = config
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._autopilot_service = autopilot_service
        self._unified_mode = unified_app is not None

        # Use unified app or create standalone
        self._app = unified_app or FastAPI(
            title="Soothe Daemon API",
            description="REST API for Soothe multi-agent assistant",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )
        self._server: Any = None
        self._message_handler: Any | None = None
        self._client_count = 0

        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self) -> None:
        """Setup CORS middleware."""
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=self._http_config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self) -> None:
        """Setup all REST API routes."""
        # Import routes from existing HttpRestTransport

        # Use existing route setup but with channel context
        self._setup_health_routes()
        self._setup_config_routes()
        self._setup_autopilot_routes()

    def _setup_health_routes(self) -> None:
        """Setup health and status routes."""

        @self._app.get("/api/v1/health")
        async def health_check() -> dict[str, Any]:
            """Health check endpoint with queue metrics."""
            queue_metrics = {}

            if self._session_manager and hasattr(self._session_manager, "_sessions"):
                event_queues = []
                for session in self._session_manager._sessions.values():
                    if hasattr(session, "event_queue"):
                        event_queues.append(session.event_queue.qsize())

                if event_queues:
                    queue_metrics["event_queues"] = {
                        "max_depth": max(event_queues),
                        "avg_depth": round(sum(event_queues) / len(event_queues), 2),
                        "clients_near_capacity": sum(1 for d in event_queues if d > 8000),
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

    def _setup_config_routes(self) -> None:
        """Setup configuration routes."""

        @self._app.get("/api/v1/config")
        async def get_config() -> dict[str, Any]:
            """Get current configuration."""
            return {"config": {}}

        @self._app.put("/api/v1/config")
        async def update_config(request: ConfigUpdateRequest) -> dict[str, Any]:
            """Update configuration."""
            return {"status": "updated", "updates": request.updates}

        @self._app.get("/api/v1/config/schema")
        async def get_config_schema() -> dict[str, Any]:
            """Get configuration schema."""
            return {"schema": {}}

    def _setup_autopilot_routes(self) -> None:
        """Setup autopilot REST API routes."""
        # Delegate to existing implementation for complex autopilot routes
        from soothe_daemon.transports.http_rest import HttpRestTransport

        # Create transport to add routes to unified_app (side effect in constructor)
        HttpRestTransport(
            self._http_config,
            runner=self._runner,
            soothe_config=self._soothe_config,
            session_manager=self._session_manager,
            unified_app=self._app,  # Routes added to our app
            autopilot_service=self._autopilot_service,
        )

    async def start(self) -> None:
        """Start the HTTP REST server.

        Note: In unified mode, routes are already attached to the shared app
        and no standalone listener is needed.
        """
        if not self._http_config.enabled:
            logger.info("HTTP REST channel disabled by configuration")
            return

        self._message_handler = getattr(self._manager, "_message_handler", None)

        if self._unified_mode:
            logger.debug("HTTP REST routes attached to unified ASGI app")
            self._running = True
            return

        # Standalone mode: start uvicorn
        import uvicorn

        ssl_keyfile = None
        ssl_certfile = None
        if self._http_config.tls_enabled and self._http_config.tls_cert and self._http_config.tls_key:
            ssl_certfile = self._http_config.tls_cert
            ssl_keyfile = self._http_config.tls_key

        config = uvicorn.Config(
            app=self._app,
            host=self._http_config.host,
            port=self._http_config.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        task = asyncio.create_task(self._server.serve())
        _ = task  # Intentionally not tracked

        protocol = "https" if self._http_config.tls_enabled else "http"
        logger.info(
            "HTTP REST channel listening on %s://%s:%d",
            protocol,
            self._http_config.host,
            self._http_config.port,
        )
        self._running = True

    async def stop(self) -> None:
        """Stop the HTTP REST server."""
        if self._server:
            self._server.should_exit = True
            await asyncio.sleep(0.5)
            self._server = None

        self._running = False
        logger.info("HTTP REST channel stopped")

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send message to client - not supported for HTTP REST.

        Args:
            chat_id: Not used for HTTP REST.
            message: Not used for HTTP REST.

        Raises:
            NotImplementedError: HTTP REST doesn't support outbound messages.
        """
        raise NotImplementedError("HTTP REST channel doesn't support outbound messages")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message - no-op for HTTP REST.

        Args:
            message: Message dict (ignored).
        """
        # HTTP REST doesn't maintain persistent connections for broadcasting
        pass

    @property
    def transport_type(self) -> str:
        """Return transport type (compatibility alias)."""
        return self.name

    @property
    def client_count(self) -> int:
        """Return client count (requests are ephemeral)."""
        return self._client_count
