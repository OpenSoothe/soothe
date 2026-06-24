"""HTTP REST channel implementation (RFC-620).

HTTP REST channel for health checks, status, autopilot, cron, and auxiliary endpoints.
Note: This channel only supports inbound (supports_outbound=False).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from soothe_daemon import __version__
from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config.models import HttpRestConfig

logger = logging.getLogger(__name__)


def _get_client_id(request: Request) -> str:
    """Generate client ID from request."""
    client_host = request.client.host if request.client else "unknown"
    return f"http:{client_host}"


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
        cron_service: Any | None = None,
        memory_profiler: Any | None = None,
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
            cron_service: Optional CronService for scheduled job endpoints.
            memory_profiler: Optional MemoryProfiler for memory diagnostics.
        """
        super().__init__(config, manager)
        self._http_config = config
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._autopilot_service = autopilot_service
        self._cron_service = cron_service
        self._memory_profiler = memory_profiler
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

    def _require_autopilot_service(self) -> Any:
        """Return the daemon-owned AutopilotService or raise HTTP 503."""
        if self._autopilot_service is None:
            raise HTTPException(
                status_code=503,
                detail="Autopilot service unavailable; ensure autopilot is enabled and the daemon started cleanly",
            )
        return self._autopilot_service

    def _require_cron_service(self) -> Any:
        """Return the daemon-owned CronService or raise HTTP 503."""
        if self._cron_service is None:
            raise HTTPException(
                status_code=503,
                detail="Cron service unavailable; ensure cron.enabled is true and the daemon started cleanly",
            )
        return self._cron_service

    def _setup_routes(self) -> None:
        """Setup all REST API routes."""
        self._setup_health_routes()
        self._setup_config_routes()
        self._setup_file_routes()
        self._setup_system_routes()
        self._setup_autopilot_routes()
        self._setup_cron_routes()
        self._setup_memory_routes()

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
        """Setup autopilot REST API routes (RFC-204 / RFC-222)."""

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

        @self._app.get("/api/v1/autopilot/jobs")
        async def autopilot_list_jobs() -> dict[str, Any]:
            """List root goals (jobs) only.

            A job is a root goal submitted by user (parent_id=None).
            Subgoals created during autonomous execution are excluded.
            """
            service = self._require_autopilot_service()
            goals = await service.list_goals()
            jobs = [g for g in goals if g.parent_id is None]
            return {
                "jobs": [j.model_dump(mode="json") for j in jobs],
                "source": "autopilot_service",
            }

        @self._app.get("/api/v1/autopilot/jobs/{job_id}")
        async def autopilot_get_job(job_id: str) -> dict[str, Any]:
            """Get job status with DAG snapshot.

            Returns job details plus complete goal DAG for visualization.
            """
            service = self._require_autopilot_service()
            job = await service.get_goal(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            if job.parent_id is not None:
                raise HTTPException(
                    status_code=404, detail="Not a root goal (job). Use /goals/{id} instead."
                )

            dag = await service.dag_snapshot(job_id)
            # Count goals by status
            nodes = dag.get("nodes", [])
            active = sum(1 for n in nodes if n.get("status") == "active")
            completed = sum(1 for n in nodes if n.get("status") in ("completed", "validated"))
            return {
                "job": job.model_dump(mode="json"),
                "dag": dag,
                "active_goals": active,
                "completed_goals": completed,
                "total_goals": len(nodes),
                "source": "autopilot_service",
            }

        @self._app.post("/api/v1/autopilot/submit")
        async def autopilot_submit(request: Request) -> dict[str, Any]:
            """Submit a new task to autopilot."""
            body = await request.json()
            description = body.get("description", "")
            priority = int(body.get("priority", 50))
            workspace_raw = body.get("workspace")
            workspace: str | None = None
            if isinstance(workspace_raw, str) and workspace_raw.strip():
                from soothe.foundation.workspace import validate_client_workspace

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

        @self._app.post("/api/v1/autopilot/goals/{goal_id}/resume")
        async def autopilot_resume_goal(goal_id: str) -> dict[str, Any]:
            """Resume a suspended/blocked goal.

            Reactivates a suspended or blocked goal back to pending status
            so the scheduler can pick it up for execution.
            """
            service = self._require_autopilot_service()
            goal_engine = service._goal_engine

            # Check goal exists
            goal = await goal_engine.get_goal(goal_id)
            if goal is None:
                raise HTTPException(status_code=404, detail="Goal not found")

            # Check goal is in a resumable state
            if goal.status not in ("suspended", "blocked"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Goal is not paused (status: {goal.status})",
                )

            # Reactivate the goal
            try:
                reactivated = await goal_engine.reactivate_goal(goal_id)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to reactivate goal: {exc}",
                )

            return {
                "status": "reactivated",
                "goal_id": goal_id,
                "new_status": reactivated.status,
            }

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

    def _setup_cron_routes(self) -> None:
        """Setup cron REST API routes (RFC-229)."""

        @self._app.get("/api/v1/cron/jobs")
        async def cron_list_jobs(status: str | None = None) -> dict[str, Any]:
            """List scheduled cron jobs.

            Args:
                status: Optional status filter (pending, running, completed, failed, cancelled).
            """
            service = self._require_cron_service()
            # Default user_id for HTTP API (no per-user isolation in basic mode)
            user_id = "http_api"
            jobs = await service.list_jobs(user_id, status=status)
            return {
                "jobs": [j.to_dict() for j in jobs],
                "source": "cron_service",
            }

        @self._app.get("/api/v1/cron/jobs/{job_id}")
        async def cron_get_job(job_id: str) -> dict[str, Any]:
            """Get details for a specific cron job."""
            service = self._require_cron_service()
            user_id = "http_api"
            job = await service.show_job(job_id, user_id)
            if job:
                return {"job": job.to_dict(), "source": "cron_service"}
            raise HTTPException(status_code=404, detail="Job not found")

        @self._app.delete("/api/v1/cron/jobs/{job_id}")
        async def cron_cancel_job(job_id: str) -> dict[str, Any]:
            """Cancel a scheduled cron job."""
            service = self._require_cron_service()
            user_id = "http_api"
            cancelled = await service.cancel_job(job_id, user_id)
            if cancelled:
                return {"cancelled": True, "job_id": job_id}
            raise HTTPException(status_code=404, detail="Job not found or cannot be cancelled")

    def _setup_file_routes(self) -> None:
        """Setup file operation routes."""

        @self._app.post("/api/v1/files/upload")
        async def upload_file(_request: Request) -> dict[str, Any]:
            """Upload a file."""
            return {"file_id": "file_001", "status": "uploaded"}

        @self._app.get("/api/v1/files/{file_id}")
        async def download_file(file_id: str) -> dict[str, Any]:
            """Download a file."""
            _ = file_id
            raise HTTPException(status_code=404, detail="File not found")

        @self._app.delete("/api/v1/files/{file_id}")
        async def delete_file(file_id: str) -> dict[str, Any]:
            """Delete a file."""
            return {"file_id": file_id, "status": "deleted"}

    def _setup_system_routes(self) -> None:
        """Setup system routes."""

        @self._app.post("/api/v1/system/shutdown")
        async def shutdown_daemon(http_request: Request) -> dict[str, Any]:
            """Request daemon shutdown."""
            if self._message_handler:
                client_id = _get_client_id(http_request)
                self._message_handler(client_id, {"type": "command", "cmd": "/exit"})
            return {"status": "shutting_down"}

    def _setup_memory_routes(self) -> None:
        """Setup memory profiling routes."""

        profiler = self._memory_profiler

        @self._app.get("/api/v1/memory")
        async def memory_stats(mode: str = "daemon") -> dict[str, Any]:
            """Query daemon memory profiling stats.

            Args:
                mode: One of daemon, gc, snapshot, objects, compare, queues, large.
            """
            if profiler is None:
                raise HTTPException(
                    status_code=503,
                    detail="Memory profiling not enabled. "
                    "Set memory_profiling.enabled=true in daemon_config.yml",
                )

            loop = asyncio.get_running_loop()

            if mode == "daemon":
                stats = await loop.run_in_executor(None, profiler.get_current_stats)
                return {"memory_stats": stats}
            elif mode == "gc":
                stats = await loop.run_in_executor(None, profiler.force_gc_and_report)
                return {"memory_stats": stats}
            elif mode == "snapshot":
                await loop.run_in_executor(None, profiler.update_last_snapshot)
                stats = await loop.run_in_executor(None, profiler.get_current_stats)
                return {"memory_stats": stats}
            elif mode == "objects":
                counts = await loop.run_in_executor(None, profiler.get_object_counts)
                return {"memory_stats": {"object_counts": counts}}
            elif mode == "compare":
                try:
                    stats = await loop.run_in_executor(None, profiler.compare_snapshots)
                    return {"memory_stats": stats}
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
            elif mode == "queues":
                # IG-477: Queue depth metrics for backpressure debugging
                metrics = await loop.run_in_executor(None, profiler.get_queue_metrics)
                return {"memory_stats": {"queue_metrics": metrics}}
            elif mode == "large":
                # IG-477: Large allocations (>100KB) ranked by size
                large = await loop.run_in_executor(None, profiler.get_large_allocations)
                return {"memory_stats": {"large_allocations": large}}
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown mode: {mode!r}. "
                    "Expected one of: daemon, gc, snapshot, objects, compare, queues, large",
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
        if (
            self._http_config.tls_enabled
            and self._http_config.tls_cert
            and self._http_config.tls_key
        ):
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
    def client_count(self) -> int:
        """Return client count (requests are ephemeral)."""
        return self._client_count
