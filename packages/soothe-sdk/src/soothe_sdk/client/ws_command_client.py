"""WebSocket command client for daemon command endpoints.

Provides synchronous and async clients for sending commands over WebSocket
and receiving responses. Replaces HTTP REST clients for autopilot, cron,
and memory profiling operations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from soothe_sdk.client.helpers import websocket_url_from_config
from soothe_sdk.client.wire import (
    ConnectionInitEnvelope,
    ConnectionInitParams,
    ErrorEnvelope,
    MessageType,
    WireEnvelope,
    decode_envelope,
    encode_envelope,
)

logger = logging.getLogger(__name__)

_TRANSITIONAL_DAEMON_READY_STATES = frozenset({"starting", "warming"})
_DAEMON_READY_POLL_INTERVAL_S = 0.05

try:
    from soothe_sdk import __version__ as _client_version
except Exception:  # pragma: no cover
    _client_version = "0.0.0"


def _normalize_cron_add_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize daemon cron_add payloads to ``{"job": {...}}`` for CLI callers."""
    if "job" in result:
        return result
    job_id = result.get("job_id") or result.get("id")
    if not job_id:
        return result
    job = dict(result)
    job["id"] = job_id
    job.pop("job_id", None)
    return {"job": job}


def _normalize_cron_show_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize daemon cron_show payloads to ``{"job": {...}}`` for CLI callers."""
    if "job" in result:
        return result
    job_id = result.get("job_id") or result.get("id")
    if not job_id:
        return {"job": None}
    job = dict(result)
    job["id"] = job_id
    job.pop("job_id", None)
    return {"job": job}


async def _perform_handshake(ws: Any, *, timeout: float) -> None:
    """Complete protocol-1 ``connection_init`` / ``connection_ack`` (RFC-450 §8.2).

    Args:
        ws: Connected WebSocket.
        timeout: Maximum seconds to wait for a ready ``connection_ack``.

    Raises:
        RuntimeError: If the handshake fails or times out.
    """
    init = ConnectionInitEnvelope(
        params=ConnectionInitParams(
            client_version=_client_version,
            client_name="soothe-sdk",
            accept_proto=["1"],
            capabilities=["streaming", "batch", "heartbeat"],
        )
    )

    async with asyncio.timeout(timeout):
        await ws.send(encode_envelope(init))
        while True:
            response_str = await ws.recv()
            response = decode_envelope(response_str)
            if not isinstance(response, dict):
                continue

            msg_type = response.get("type")
            if msg_type == "status":
                continue

            if msg_type == MessageType.ERROR.value:
                err = ErrorEnvelope.from_wire_dict(response)
                raise RuntimeError(
                    f"[{err.code}] {err.message}" + (f" ({err.data})" if err.data else "")
                )

            if msg_type != "connection_ack":
                continue

            result = response.get("result") or {}
            state = result.get("readiness_state")
            if state == "incompatible":
                raise RuntimeError(
                    "Protocol version incompatible: "
                    f"daemon returned {result.get('protocol_version')!r}"
                )
            if state == "ready":
                return
            if state == "error":
                raise RuntimeError("Daemon startup failed")
            if state == "degraded":
                raise RuntimeError("Daemon is degraded")
            if state in _TRANSITIONAL_DAEMON_READY_STATES:
                await asyncio.sleep(_DAEMON_READY_POLL_INTERVAL_S)
                await ws.send(encode_envelope(init))
                continue
            raise RuntimeError(f"Daemon state is {state}")


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
    "list": "cron_list",
    "list_jobs": "cron_list",
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

    async def _send_command(
        self, command_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a protocol-1 request envelope and wait for the response.

        Builds a ``WireEnvelope`` with ``type='request'``, ``method=command_type``,
        ``params=payload``, and a UUID4 correlation ``id`` (RFC-450 §5, IG-522
        Phase 6). The envelope is serialized with :func:`encode_envelope` and the
        reply is parsed with :func:`decode_envelope`. Responses are matched by
        ``id``; ``response`` envelopes return their ``result`` and ``error``
        envelopes raise :class:`RuntimeError` carrying the daemon's code/message.

        Args:
            command_type: RPC method name (e.g. ``"autopilot_status"``).
            payload: Structured parameters object for the method.

        Returns:
            The ``result`` dict from the matching ``response`` envelope.

        Raises:
            RuntimeError: If the daemon replies with an ``error`` envelope, the
                connection fails, or the command times out.
        """
        import websockets

        req_id = str(uuid4())
        envelope = WireEnvelope(
            type=MessageType.REQUEST.value,
            method=command_type,
            params=payload or {},
            id=req_id,
        )

        try:
            async with websockets.connect(self._ws_url, open_timeout=self._timeout) as ws:
                await _perform_handshake(ws, timeout=self._timeout)

                # Send the protocol-1 request envelope.
                await ws.send(encode_envelope(envelope))

                # Wait for the matching response/error envelope.
                while True:
                    response_str = await asyncio.wait_for(ws.recv(), timeout=self._timeout)
                    response = decode_envelope(response_str)
                    if not isinstance(response, dict):
                        raise RuntimeError(f"Unexpected response: {response_str!r}")

                    msg_type = response.get("type")

                    # Error envelope: raise with the daemon's code/message.
                    if msg_type == MessageType.ERROR.value:
                        err = ErrorEnvelope.from_wire_dict(response)
                        raise RuntimeError(
                            f"[{err.code}] {err.message}" + (f" ({err.data})" if err.data else "")
                        )

                    # Success: return the result payload.
                    if msg_type == MessageType.RESPONSE.value:
                        if response.get("id") != req_id:
                            # Not our response; keep waiting for the match.
                            continue
                        return response.get("result") or {}

                    # Other message types (next/complete/etc.) are unexpected
                    # for a blocking request; keep reading.
                    continue

        except TimeoutError:
            raise RuntimeError(f"Command timeout after {self._timeout}s") from None
        except websockets.exceptions.ConnectionClosedError as exc:
            raise RuntimeError(f"WebSocket connection closed: {exc}") from exc
        except RuntimeError:
            raise
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

    async def autopilot_subscribe(self) -> dict[str, Any]:
        """Subscribe to autopilot worker events."""
        return await self._send_command("autopilot_subscribe")

    async def autopilot_unsubscribe(self) -> dict[str, Any]:
        """Unsubscribe from autopilot worker events."""
        return await self._send_command("autopilot_unsubscribe")

    # RFC-228 canonical job commands (recommended)

    async def job_create(
        self,
        goal: str,
        *,
        workspace: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        guidance: str | None = None,
    ) -> dict[str, Any]:
        """Create a new autopilot job (RFC-228 canonical method).

        Args:
            goal: Job goal text (required).
            workspace: Optional workspace path.
            autonomous: Whether to run autonomously.
            max_iterations: Optional iteration limit.
            guidance: Optional initial guidance.

        Returns:
            Dict with job_id and status.
        """
        payload = {"goal": goal}
        if workspace:
            payload["workspace"] = workspace
        if autonomous:
            payload["autonomous"] = autonomous
        if max_iterations:
            payload["max_iterations"] = max_iterations
        if guidance:
            payload["guidance"] = guidance
        return await self._send_command("job_create", payload)

    async def job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status with goal counts and workers (RFC-228 canonical method).

        Args:
            job_id: Job identifier.

        Returns:
            Dict with job_id, status, active_goals, completed_goals, workers.
        """
        return await self._send_command("job_status", {"job_id": job_id})

    async def job_pause(self, job_id: str) -> dict[str, Any]:
        """Pause a running job (RFC-228 canonical method).

        Args:
            job_id: Job identifier.

        Returns:
            Dict with job_id and status="suspended".
        """
        return await self._send_command("job_pause", {"job_id": job_id})

    async def job_resume(self, job_id: str) -> dict[str, Any]:
        """Resume a paused job (RFC-228 canonical method).

        Args:
            job_id: Job identifier.

        Returns:
            Dict with job_id and status="pending".
        """
        return await self._send_command("job_resume", {"job_id": job_id})

    async def job_cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a job (RFC-228 canonical method).

        Args:
            job_id: Job identifier.

        Returns:
            Dict with job_id and status="cancelled".
        """
        return await self._send_command("job_cancel", {"job_id": job_id})

    async def job_dag(self, job_id: str) -> dict[str, Any]:
        """Get job DAG snapshot for visualization (RFC-228 canonical method).

        Args:
            job_id: Job identifier.

        Returns:
            Dict with job_id and dag (nodes/edges).
        """
        return await self._send_command("job_dag", {"job_id": job_id})

    async def job_guidance(
        self, job_id: str, content: str, *, goal_id: str | None = None
    ) -> dict[str, Any]:
        """Send guidance to a job or specific goal (RFC-228 canonical method).

        Args:
            job_id: Job identifier.
            content: Guidance text.
            goal_id: Optional specific goal to target.

        Returns:
            Dict with job_id, goal_id, absorbed.
        """
        payload = {"job_id": job_id, "content": content}
        if goal_id:
            payload["goal_id"] = goal_id
        return await self._send_command("job_guidance", payload)

    # Cron commands

    async def cron_add(self, text: str, *, priority: int | None = None) -> dict[str, Any]:
        """Submit a natural-language scheduled job."""
        payload = {"text": text}
        if priority is not None:
            payload["priority"] = priority
        result = await self._send_command("cron_add", payload)
        return _normalize_cron_add_result(result)

    async def cron_list(self, *, status: str | None = None) -> dict[str, Any]:
        """List scheduled jobs (RFC-229 canonical method).

        Sends the ``cron_list`` method, which the daemon routes to
        ``_handle_cron_list``. The former ``cron_list_jobs`` method name is
        deprecated; it sent a method the daemon did not handle.

        Args:
            status: Optional status filter.

        Returns:
            Dict with jobs list.
        """
        payload = {}
        if status:
            payload["status"] = status
        return await self._send_command("cron_list", payload)

    async def cron_show(self, job_id: str) -> dict[str, Any]:
        """Get job details."""
        result = await self._send_command("cron_show", {"job_id": job_id})
        return _normalize_cron_show_result(result)

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

    def job_create(
        self,
        goal: str,
        *,
        workspace: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        guidance: str | None = None,
    ) -> dict[str, Any]:
        """Create a new autopilot job (sync, RFC-228 canonical)."""
        return self._run_async(
            self._client.job_create(
                goal,
                workspace=workspace,
                autonomous=autonomous,
                max_iterations=max_iterations,
                guidance=guidance,
            )
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status with goal counts and workers (sync, RFC-228 canonical)."""
        return self._run_async(self._client.job_status(job_id))

    def job_resume(self, job_id: str) -> dict[str, Any]:
        """Resume a paused autopilot job (sync, RFC-228 canonical)."""
        return self._run_async(self._client.job_resume(job_id))

    def job_cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel an autopilot job (sync, RFC-228 canonical)."""
        return self._run_async(self._client.job_cancel(job_id))

    def job_dag(self, job_id: str) -> dict[str, Any]:
        """Get job DAG snapshot for visualization (sync, RFC-228 canonical)."""
        return self._run_async(self._client.job_dag(job_id))

    def autopilot_subscribe(self) -> dict[str, Any]:
        """Subscribe to autopilot worker events (sync)."""
        return self._run_async(self._client.autopilot_subscribe())

    def autopilot_unsubscribe(self) -> dict[str, Any]:
        """Unsubscribe from autopilot worker events (sync)."""
        return self._run_async(self._client.autopilot_unsubscribe())

    def cron_add(self, text: str, *, priority: int | None = None) -> dict[str, Any]:
        """Submit a natural-language scheduled job (sync)."""
        return self._run_async(self._client.cron_add(text, priority=priority))

    def cron_list(self, *, status: str | None = None) -> dict[str, Any]:
        """List scheduled jobs (sync)."""
        return self._run_async(self._client.cron_list(status=status))

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
