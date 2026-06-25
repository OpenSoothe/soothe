"""WebSocket command client for daemon command endpoints.

Provides synchronous and async clients for sending commands over WebSocket
and receiving responses. Replaces HTTP REST clients for autopilot, cron,
and memory profiling operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from soothe_sdk.client.helpers import websocket_url_from_config

logger = logging.getLogger(__name__)

# Command message types
_AUTOPilot_COMMANDS = {
    "status": "autopilot_status",
    "submit": "autopilot_submit",
    "list_goals": "autopilot_list_goals",
    "get_goal": "autopilot_get_goal",
    "cancel_goal": "autopilot_cancel_goal",
    "wake": "autopilot_wake",
    "dream": "autopilot_dream",
    "approve": "autopilot_approve",
    "reject": "autopilot_reject",
    "resume": "autopilot_resume",
    "list_jobs": "autopilot_list_jobs",
    "get_job": "autopilot_get_job",
}

_CRON_COMMANDS = {
    "add": "cron_add",
    "list_jobs": "cron_list_jobs",
    "show": "cron_show",
    "cancel": "cron_cancel",
}

_MEMORY_COMMANDS = {
    "stats": "memory_stats",
}


class WsCommandClient:
    """Async WebSocket client for daemon command endpoints.

    Connects to daemon WebSocket, sends command messages, and waits for
    response messages with a request/response pattern.

    Usage:
        client = WsCommandClient(ws_url)
        result = await client.autopilot_status()
        result = await client.cron_add("in 1 hour remind me to deploy")

    Args:
        ws_url: WebSocket URL (e.g. ``ws://127.0.0.1:8765``).
        timeout: Command timeout in seconds.
    """

    def __init__(self, ws_url: str, *, timeout: float = 30.0) -> None:
        self._ws_url = ws_url.rstrip("/")
        self._timeout = timeout
        self._request_id = 0

    async def _send_command(
        self, command_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send command and wait for response.

        Args:
            command_type: Command type string.
            payload: Command payload dict.

        Returns:
            Response dict from daemon.

        Raises:
            RuntimeError: If command fails or times out.
        """
        import websockets

        self._request_id += 1
        request_id = f"cmd_{self._request_id}"

        message = {
            "type": "command",
            "command": command_type,
            "request_id": request_id,
            "payload": payload or {},
        }

        try:
            async with websockets.connect(self._ws_url, open_timeout=self._timeout) as ws:
                # Send command
                await ws.send(json.dumps(message))

                # Wait for response
                response_str = await asyncio.wait_for(ws.recv(), timeout=self._timeout)
                response = json.loads(response_str)

                # Validate response
                if response.get("type") != "command_response":
                    raise RuntimeError(f"Unexpected response type: {response.get('type')}")

                if response.get("request_id") != request_id:
                    raise RuntimeError(
                        f"Response request_id mismatch: {response.get('request_id')}"
                    )

                if response.get("error"):
                    raise RuntimeError(response.get("error"))

                return response.get("result", {})

        except TimeoutError:
            raise RuntimeError(f"Command timeout after {self._timeout}s") from None
        except websockets.exceptions.ConnectionClosedError as exc:
            raise RuntimeError(f"WebSocket connection closed: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Command failed: {exc}") from exc

    # Autopilot commands

    async def autopilot_status(self) -> dict[str, Any]:
        """Get autopilot status."""
        return await self._send_command("autopilot_status")

    async def autopilot_submit(
        self, description: str, *, priority: int = 50, workspace: str | None = None
    ) -> dict[str, Any]:
        """Submit a new autopilot task."""
        payload = {"description": description, "priority": priority}
        if workspace:
            payload["workspace"] = workspace
        return await self._send_command("autopilot_submit", payload)

    async def autopilot_list_goals(self) -> dict[str, Any]:
        """List all goals."""
        return await self._send_command("autopilot_list_goals")

    async def autopilot_get_goal(self, goal_id: str) -> dict[str, Any]:
        """Get goal details."""
        return await self._send_command("autopilot_get_goal", {"goal_id": goal_id})

    async def autopilot_cancel_goal(self, goal_id: str) -> dict[str, Any]:
        """Cancel a goal."""
        return await self._send_command("autopilot_cancel_goal", {"goal_id": goal_id})

    async def autopilot_wake(self) -> dict[str, Any]:
        """Exit dreaming mode."""
        return await self._send_command("autopilot_wake")

    async def autopilot_dream(self) -> dict[str, Any]:
        """Force dreaming mode."""
        return await self._send_command("autopilot_dream")

    async def autopilot_approve(self, confirmation_id: str) -> dict[str, Any]:
        """Approve a confirmation."""
        return await self._send_command("autopilot_approve", {"confirmation_id": confirmation_id})

    async def autopilot_reject(self, confirmation_id: str) -> dict[str, Any]:
        """Reject a confirmation."""
        return await self._send_command("autopilot_reject", {"confirmation_id": confirmation_id})

    async def autopilot_resume(self, goal_id: str) -> dict[str, Any]:
        """Resume a suspended/blocked goal."""
        return await self._send_command("autopilot_resume", {"goal_id": goal_id})

    async def autopilot_list_jobs(self) -> dict[str, Any]:
        """List root goals (jobs) only."""
        return await self._send_command("autopilot_list_jobs")

    async def autopilot_get_job(self, job_id: str) -> dict[str, Any]:
        """Get job status with DAG snapshot."""
        return await self._send_command("autopilot_get_job", {"job_id": job_id})

    async def job_pause(self, job_id: str) -> dict[str, Any]:
        """Pause a running autopilot job."""
        return await self._send_command("autopilot_pause", {"job_id": job_id})

    async def job_guidance(
        self, job_id: str, text: str, *, goal_id: str | None = None
    ) -> dict[str, Any]:
        """Send guidance to an autopilot job or specific goal."""
        payload = {"job_id": job_id, "text": text}
        if goal_id:
            payload["goal_id"] = goal_id
        return await self._send_command("autopilot_guidance", payload)

    async def autopilot_subscribe(self) -> dict[str, Any]:
        """Subscribe to autopilot worker events."""
        return await self._send_command("autopilot_subscribe")

    async def autopilot_unsubscribe(self) -> dict[str, Any]:
        """Unsubscribe from autopilot worker events."""
        return await self._send_command("autopilot_unsubscribe")

    # Cron commands

    async def cron_add(self, text: str, *, priority: int | None = None) -> dict[str, Any]:
        """Submit a natural-language scheduled job."""
        payload = {"text": text}
        if priority is not None:
            payload["priority"] = priority
        return await self._send_command("cron_add", payload)

    async def cron_list_jobs(self, *, status: str | None = None) -> dict[str, Any]:
        """List scheduled jobs."""
        payload = {}
        if status:
            payload["status"] = status
        return await self._send_command("cron_list_jobs", payload)

    async def cron_show(self, job_id: str) -> dict[str, Any]:
        """Get job details."""
        return await self._send_command("cron_show", {"job_id": job_id})

    async def cron_cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a scheduled job."""
        return await self._send_command("cron_cancel", {"job_id": job_id})

    # Memory commands

    async def memory_stats(self, mode: str = "daemon") -> dict[str, Any]:
        """Query daemon memory profiling stats."""
        return await self._send_command("memory_stats", {"mode": mode})


class SyncWsCommandClient:
    """Synchronous wrapper for WsCommandClient.

    Provides a synchronous interface for CLI commands that need to call
    daemon endpoints without async context.

    Args:
        ws_url: WebSocket URL.
        timeout: Command timeout in seconds.
    """

    def __init__(self, ws_url: str, *, timeout: float = 30.0) -> None:
        self._client = WsCommandClient(ws_url, timeout=timeout)

    def _run_async(self, coro: Any) -> Any:
        """Run async coroutine in sync context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Already in async context - create task
            return asyncio.ensure_future(coro)
        else:
            # Not in async context - run in new loop
            return asyncio.run(coro)

    def autopilot_status(self) -> dict[str, Any]:
        """Get autopilot status (sync)."""
        return self._run_async(self._client.autopilot_status())

    def autopilot_submit(
        self, description: str, *, priority: int = 50, workspace: str | None = None
    ) -> dict[str, Any]:
        """Submit a new autopilot task (sync)."""
        return self._run_async(
            self._client.autopilot_submit(description, priority=priority, workspace=workspace)
        )

    def autopilot_list_goals(self) -> dict[str, Any]:
        """List all goals (sync)."""
        return self._run_async(self._client.autopilot_list_goals())

    def autopilot_get_goal(self, goal_id: str) -> dict[str, Any]:
        """Get goal details (sync)."""
        return self._run_async(self._client.autopilot_get_goal(goal_id))

    def autopilot_cancel_goal(self, goal_id: str) -> dict[str, Any]:
        """Cancel a goal (sync)."""
        return self._run_async(self._client.autopilot_cancel_goal(goal_id))

    def autopilot_wake(self) -> dict[str, Any]:
        """Exit dreaming mode (sync)."""
        return self._run_async(self._client.autopilot_wake())

    def autopilot_dream(self) -> dict[str, Any]:
        """Force dreaming mode (sync)."""
        return self._run_async(self._client.autopilot_dream())

    def autopilot_approve(self, confirmation_id: str) -> dict[str, Any]:
        """Approve a confirmation (sync)."""
        return self._run_async(self._client.autopilot_approve(confirmation_id))

    def autopilot_reject(self, confirmation_id: str) -> dict[str, Any]:
        """Reject a confirmation (sync)."""
        return self._run_async(self._client.autopilot_reject(confirmation_id))

    def autopilot_resume(self, goal_id: str) -> dict[str, Any]:
        """Resume a suspended/blocked goal (sync)."""
        return self._run_async(self._client.autopilot_resume(goal_id))

    def autopilot_list_jobs(self) -> dict[str, Any]:
        """List root goals (jobs) only (sync)."""
        return self._run_async(self._client.autopilot_list_jobs())

    def autopilot_get_job(self, job_id: str) -> dict[str, Any]:
        """Get job status with DAG snapshot (sync)."""
        return self._run_async(self._client.autopilot_get_job(job_id))

    def job_pause(self, job_id: str) -> dict[str, Any]:
        """Pause a running autopilot job (sync)."""
        return self._run_async(self._client.job_pause(job_id))

    def job_guidance(self, job_id: str, text: str, *, goal_id: str | None = None) -> dict[str, Any]:
        """Send guidance to an autopilot job or specific goal (sync)."""
        return self._run_async(self._client.job_guidance(job_id, text, goal_id=goal_id))

    def autopilot_subscribe(self) -> dict[str, Any]:
        """Subscribe to autopilot worker events (sync)."""
        return self._run_async(self._client.autopilot_subscribe())

    def autopilot_unsubscribe(self) -> dict[str, Any]:
        """Unsubscribe from autopilot worker events (sync)."""
        return self._run_async(self._client.autopilot_unsubscribe())

    def cron_add(self, text: str, *, priority: int | None = None) -> dict[str, Any]:
        """Submit a natural-language scheduled job (sync)."""
        return self._run_async(self._client.cron_add(text, priority=priority))

    def cron_list_jobs(self, *, status: str | None = None) -> dict[str, Any]:
        """List scheduled jobs (sync)."""
        return self._run_async(self._client.cron_list_jobs(status=status))

    def cron_show(self, job_id: str) -> dict[str, Any]:
        """Get job details (sync)."""
        return self._run_async(self._client.cron_show(job_id))

    def cron_cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a scheduled job (sync)."""
        return self._run_async(self._client.cron_cancel(job_id))

    def memory_stats(self, mode: str = "daemon") -> dict[str, Any]:
        """Query daemon memory profiling stats (sync)."""
        return self._run_async(self._client.memory_stats(mode))


def ws_command_client_from_config(cfg: Any) -> SyncWsCommandClient:
    """Build a WebSocket command client from CLI or soothe config.

    Args:
        cfg: CLI, daemon, or soothe config exposing websocket host/port.

    Returns:
        SyncWsCommandClient instance.
    """
    ws_url = websocket_url_from_config(cfg)
    return SyncWsCommandClient(ws_url)


def async_ws_command_client_from_config(cfg: Any) -> WsCommandClient:
    """Build an async WebSocket command client from config.

    Args:
        cfg: CLI, daemon, or soothe config exposing websocket host/port.

    Returns:
        WsCommandClient instance.
    """
    ws_url = websocket_url_from_config(cfg)
    return WsCommandClient(ws_url)


__all__ = [
    "WsCommandClient",
    "SyncWsCommandClient",
    "ws_command_client_from_config",
    "async_ws_command_client_from_config",
]
